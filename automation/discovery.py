"""Goal-driven controller: workflow choices come exclusively from the provider."""

import asyncio
import json
import re
import uuid

from .compiler import compile_action, observed_checkpoint
from .evidence import Evidence, utcnow
from .models import (
    AutomationError,
    Action,
    Capability,
    FINAL,
    Ownership,
    Provenance,
    Result,
    RuntimeConfig,
    Step,
    Tenant,
)
from .policy import Policy, PolicyConfig
from .runner import Execution, failure_result
from .surface import BrowserSurface


async def discover(
    goal, inputs, provider, tenant=None, config=None, policy_config=None, operator=None
):
    tenant = tenant or Tenant()
    config = config or RuntimeConfig()
    run_id = uuid.uuid4().hex[:12]
    evidence = Evidence(config.evidence_dir, run_id, inputs)
    kind = "simulated_discovery" if provider.simulated else "llm_discovery"
    evidence.event("run_started", provenance=kind, provider=provider.identifier)
    surface = BrowserSurface(
        tenant, inputs, config, Policy(policy_config or PolicyConfig()), evidence
    )
    execution = Execution(surface, evidence, operator=operator)
    steps = []
    if not re.fullmatch(r"[0-9]{5}", inputs.member_id):
        return Result(
            status="business_outcome", code="INVALID_INPUT", run_id=run_id
        ), None
    try:
        async with asyncio.timeout(config.overall_timeout_seconds), surface:
            try:
                async with asyncio.timeout(config.overall_timeout_seconds):
                    seen = {}
                    for n in range(1, config.max_steps + 1):
                        execution.step_id = f"s{n:03d}"
                        await execution.inspect()
                        if execution.human_completed:
                            raise AutomationError(
                                "REVIEW_REQUIRED",
                                "fully compiled automated workflow",
                                "human-completed discovery needs a new recording",
                            )
                        observation = await surface.observe()
                        before = observed_checkpoint(observation["screen"])
                        for attempt in range(config.invalid_response_retries + 1):
                            try:
                                decision = await provider.decide(
                                    evidence.sanitizer.text(goal), observation
                                )
                                action = compile_action(decision, surface.controls)
                                if action.kind == "fill":
                                    control = next(
                                        (
                                            item
                                            for item in observation["controls"]
                                            if item["control_ref"] == decision.control_ref
                                        ),
                                        None,
                                    )
                                    if control and control.get("value_matches_input"):
                                        raise AutomationError(
                                            "INVALID_MODEL_RESPONSE",
                                            "a different visible action",
                                            "repeated fill whose value already matches input",
                                        )
                                candidate_fingerprint = json.dumps(
                                    {
                                        "action": action.model_dump(),
                                        "screen": observation["screen"],
                                        "checks": observation["checks"],
                                    },
                                    sort_keys=True,
                                )
                                if (
                                    action.kind == "extract"
                                    and seen.get(candidate_fingerprint, 0) > 0
                                ):
                                    action = Action(kind="finish")
                                    evidence.event(
                                        "repeated_extract_recovered",
                                        step_id=execution.step_id,
                                    )
                                break
                            except AutomationError as exc:
                                if (
                                    exc.code != "INVALID_MODEL_RESPONSE"
                                    or attempt == config.invalid_response_retries
                                ):
                                    raise
                                observation["retry_feedback"] = (
                                    "The previous action was rejected. Choose a different "
                                    "visible action; do not repeat a fill whose value already "
                                    "matches its input binding or repeat extract without a "
                                    "state change."
                                )
                                evidence.event(
                                    "model_response_rejected",
                                    code=exc.code,
                                    attempt=attempt + 1,
                                )
                        fingerprint = json.dumps(
                            {
                                "action": action.model_dump(),
                                "screen": observation["screen"],
                                "checks": observation["checks"],
                            },
                            sort_keys=True,
                        )
                        seen[fingerprint] = seen.get(fingerprint, 0) + 1
                        if seen[fingerprint] > config.max_no_progress:
                            if config.interactive:
                                await execution.intervene("NO_PROGRESS")
                            raise AutomationError(
                                "NO_PROGRESS",
                                "new verifiable state",
                                "repeated action without progress",
                            )
                        step = Step(id=execution.step_id, action=action, before=before)
                        await execution.step(step)
                        if execution.human_completed:
                            raise AutomationError("REVIEW_REQUIRED")
                        step.after = observed_checkpoint(await surface.screen())
                        steps.append(step)
                        if action.kind == "finish":
                            await surface.verify(FINAL)
                            capability = Capability(
                                steps=steps,
                                provenance=Provenance(
                                    kind=kind,
                                    run_id=run_id,
                                    provider=provider.identifier,
                                    created_at=utcnow(),
                                ),
                            )
                            capability.lifecycle = "draft"
                            # Artifact contains structure/bindings only. A static default
                            # description replaces potentially sensitive natural-language goals.
                            text = capability.model_dump_json(indent=2)
                            for secret in evidence.sanitizer.secrets:
                                if secret and secret in text:
                                    raise AutomationError("ARTIFACT_SENSITIVE_DATA")
                            (evidence.directory / "capability.json").write_text(text)
                            outputs = await surface.balances()
                            surface.ownership = Ownership.COMPLETED
                            evidence.event("artifact_compiled", provenance=kind)
                            evidence.event(
                                "run_finished", status="success", code="SUCCESS"
                            )
                            return Result(
                                status="success",
                                code="SUCCESS",
                                run_id=run_id,
                                step_id=step.id,
                                outputs=outputs,
                            ), capability
                    if config.interactive:
                        await execution.intervene("MAX_STEPS")
                    raise AutomationError(
                        "MAX_STEPS",
                        "verified completion within step budget",
                        "budget exhausted",
                    )
            except Exception as exc:
                return await failure_result(
                    exc, surface, evidence, execution.step_id
                ), None
    except Exception as exc:
        return await failure_result(exc, surface, evidence, execution.step_id), None
