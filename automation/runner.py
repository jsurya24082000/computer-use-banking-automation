"""Deterministic execution; this module does not import an LLM provider."""

import asyncio
import re
import uuid

from .evidence import Evidence, capability_sha256
from .models import (
    Action,
    AutomationError,
    Capability,
    FINAL,
    Inputs,
    Ownership,
    Result,
    RuntimeConfig,
    Tenant,
    WORKFLOW_FINAL_CHECKPOINT,
)
from .policy import Policy, PolicyConfig
from .surface import BrowserSurface, role_target


class TerminalOutcome(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Execution:
    """Shared by discovery and replay, including all recovery and policy checks."""

    def __init__(self, surface, evidence, capability=None, operator=None):
        self.surface, self.evidence, self.capability, self.operator = (
            surface,
            evidence,
            capability,
            operator,
        )
        self.step_id = "s000"
        self.retries = 0
        self.human_completed = False

    async def inspect(self):
        self.surface.assert_safe()
        signal = await self.surface.signal()
        rules = self.capability.business_outcomes if self.capability else []
        outcomes = (
            {r.signal: r.code for r in rules}
            if self.capability
            else {
                "invalid_input": "INVALID_INPUT",
                "member_not_found": "MEMBER_NOT_FOUND",
                "no_eligible_account": "NO_ELIGIBLE_ACCOUNT",
            }
        )
        if signal in outcomes:
            raise TerminalOutcome("business_outcome", outcomes[signal])
        if signal == "permission_denied":
            raise AutomationError(
                "PERMISSION_DENIED", "authorized account", "staff access denied"
            )
        if signal == "wrong_member":
            raise AutomationError("MEMBER_MISMATCH")
        if signal == "ambiguous_account":
            raise AutomationError("AMBIGUOUS_TARGET")
        if signal == "invalid_credentials":
            raise AutomationError("INVALID_CREDENTIALS")
        if signal == "temporary_failure":
            limit = (
                sum(r.max_attempts for r in self.capability.recovery)
                if self.capability
                else 1
            )
            if self.retries >= limit:
                raise AutomationError("RECOVERY_EXHAUSTED")
            self.retries += 1
            self.evidence.event(
                "recovery",
                step_id=self.step_id,
                code="RETRY_VISIBLE_READ_LINK",
                attempt=self.retries,
            )
            await self.surface.execute(
                Action(kind="click", target=role_target("Retry account load", "link"))
            )
            await self.inspect()
        elif signal in ("session_expired", "blocking_dialog"):
            await self.intervene(
                "SESSION_EXPIRED"
                if signal == "session_expired"
                else "UNEXPECTED_DIALOG"
            )

    async def intervene(self, code):
        from .handoff import HandoffController

        controller = HandoffController(self.surface, self.evidence, self.operator)
        if self.capability:
            checkpoint = self.capability.resume_checkpoint
        else:
            # Discovery has no compiled capability yet; the resume checkpoint
            # must still verify the workflow actually being recorded.
            checkpoint = WORKFLOW_FINAL_CHECKPOINT.get(
                self.surface.workflow, FINAL
            )
        await controller.takeover(self.step_id, code, checkpoint)
        self.human_completed = True

    async def step(self, step):
        self.step_id = step.id
        await self.inspect()
        if self.human_completed:
            return
        if step.before:
            await self.surface.verify(step.before)
        self.evidence.event(
            "action_started",
            step_id=step.id,
            action=step.action.kind,
            rationale={
                "click": "Activate uniquely resolved authorized control.",
                "fill": "Fill declared input through an explicit binding.",
                "select": "Select declared input through an explicit binding.",
                "navigate": "Open approved tenant entry point.",
                "extract": "Read and verify declared account fields.",
                "check": "Verify declared page state.",
                "finish": "Independently verify complete result.",
            }[step.action.kind],
        )
        await self.surface.execute(step.action)
        await self.inspect()
        if not self.human_completed and step.after:
            await self.surface.verify(step.after)
        self.evidence.event(
            "action_verified",
            step_id=step.id,
            action=step.action.kind,
            screen=await self.surface.screen(),
        )


async def failure_result(exc, surface, evidence, step_id):
    try:
        snap = await asyncio.wait_for(surface.snapshot(), timeout=2)
    except Exception:
        snap = {"screen": "unavailable", "signal": "unknown"}
    ref = evidence.snapshot(snap)
    if isinstance(exc, TerminalOutcome):
        status, code = exc.status, exc.code
        expected = observed = None
    elif isinstance(exc, AutomationError):
        status = (
            "intervention_required"
            if exc.code
            in {
                "OPERATOR_UNAVAILABLE",
                "OPERATOR_TIMEOUT",
                "OPERATOR_ABORTED",
                "RESUME_CHECKPOINT_FAILED",
                "REVIEW_REQUIRED",
            }
            else "failure"
        )
        code = exc.code
        expected = evidence.sanitizer.text(exc.expected)
        observed = evidence.sanitizer.text(exc.observed)
    else:
        evidence.event("runtime_error", code=type(exc).__name__, step_id=step_id)
        status = "failure"
        code = (
            "OVERALL_TIMEOUT"
            if isinstance(exc, TimeoutError)
            else "UNEXPECTED_RUNTIME_ERROR"
        )
        expected = "bounded successful execution"
        observed = "runtime stopped; raw exception omitted"
    evidence.event("run_finished", status=status, code=code, step_id=step_id)
    return Result(
        status=status,
        code=code,
        run_id=evidence.run_id,
        step_id=step_id,
        expected=expected,
        observed=observed,
        evidence_ref=ref,
    )


async def replay(
    capability: Capability,
    inputs: Inputs,
    tenant: Tenant | None = None,
    config: RuntimeConfig | None = None,
    policy_config: PolicyConfig | None = None,
    operator=None,
) -> Result:
    tenant = tenant or Tenant()
    config = config or RuntimeConfig()
    capability = Capability.model_validate(capability.model_dump())
    if capability.lifecycle in {"draft", "qualifying", "rejected"}:
        return Result(
            status="failure",
            code="ARTIFACT_NOT_APPROVED",
            run_id=uuid.uuid4().hex[:12],
        )
    inputs = Inputs.model_validate(inputs.model_dump())
    run_id = uuid.uuid4().hex[:12]
    evidence = Evidence(config.evidence_dir, run_id, inputs)
    evidence.event("run_started", provenance="deterministic_replay")
    evidence.event(
        "replay_started",
        provenance="deterministic_replay",
        capability_sha256=capability_sha256(capability),
    )
    if not re.fullmatch(r"[0-9]{5}", inputs.member_id):
        evidence.event("run_finished", status="business_outcome", code="INVALID_INPUT")
        return Result(status="business_outcome", code="INVALID_INPUT", run_id=run_id)
    if tenant.compatibility != capability.compatibility:
        return Result(status="failure", code="INCOMPATIBLE_BINDING", run_id=run_id)
    surface = BrowserSurface(
        tenant,
        inputs,
        config,
        Policy(policy_config or PolicyConfig()),
        evidence,
        workflow=capability.name,
    )
    execution = Execution(surface, evidence, capability, operator)
    try:
        async with asyncio.timeout(config.overall_timeout_seconds), surface:
            try:
                async with asyncio.timeout(config.overall_timeout_seconds):
                    for pre in capability.preconditions:
                        await surface.verify(pre)
                    for step in capability.steps:
                        try:
                            await execution.step(step)
                        except AutomationError as exc:
                            if config.interactive and exc.code in {
                                "AMBIGUOUS_TARGET",
                                "TARGET_NOT_FOUND",
                                "ACTION_TIMEOUT",
                                "CHECKPOINT_FAILED",
                            }:
                                await execution.intervene(exc.code)
                            else:
                                raise
                        if execution.human_completed:
                            break
                    await surface.verify(capability.final_checkpoint)
                    outputs = await surface.extract_outputs()
                    surface.ownership = Ownership.COMPLETED
                    evidence.event("run_finished", status="success", code="SUCCESS")
                    return Result(
                        status="success",
                        code="SUCCESS",
                        run_id=run_id,
                        step_id=execution.step_id,
                        outputs=outputs,
                    )
            except Exception as exc:
                return await failure_result(exc, surface, evidence, execution.step_id)
    except Exception as exc:
        return await failure_result(exc, surface, evidence, execution.step_id)
