"""Terminal ownership protocol. Operator works in the existing visible browser."""

import asyncio
import threading
from typing import Protocol
from .models import AutomationError, FINAL, Ownership


class Operator(Protocol):
    async def command(self, prompt: str) -> str: ...


class TerminalOperator:
    async def command(self, prompt):
        # A daemon reader avoids keeping asyncio.run alive after an operator timeout.
        # The browser/event loop continues servicing manual UI interaction meanwhile.
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def deliver(value):
            if not future.done():
                future.set_result(value)

        def read():
            try:
                value = input(prompt).strip().lower()
            except EOFError:
                value = "abort"
            try:
                loop.call_soon_threadsafe(deliver, value)
            except RuntimeError:
                pass

        threading.Thread(target=read, daemon=True).start()
        return await future


class HandoffController:
    def __init__(self, surface, evidence, operator=None):
        self.surface, self.evidence = surface, evidence
        self.operator = operator or TerminalOperator()

    def transition(self, state):
        old = self.surface.ownership
        allowed = {
            Ownership.AUTOMATION: {Ownership.PAUSED, Ownership.COMPLETED},
            Ownership.PAUSED: {Ownership.HUMAN},
            Ownership.HUMAN: {Ownership.AUTOMATION, Ownership.COMPLETED},
            Ownership.COMPLETED: set(),
        }
        if state not in allowed[old]:
            raise AutomationError("INVALID_CONTROL_TRANSITION")
        self.surface.ownership = state
        self.evidence.event(
            "control_transition", from_state=old.value, to_state=state.value
        )

    async def takeover(self, step_id, code, checkpoint=None):
        # Called only after the awaited action has settled/failed, never concurrently.
        self.transition(Ownership.PAUSED)
        self.evidence.intervention(step_id, code, await self.surface.snapshot())
        if not self.surface.config.interactive or self.surface.config.headless:
            raise AutomationError(
                "OPERATOR_UNAVAILABLE",
                "visible browser and interactive terminal",
                "intervention recorded; noninteractive run ends",
            )
        checkpoint = checkpoint or FINAL
        try:
            async with asyncio.timeout(self.surface.config.operator_timeout_seconds):
                while True:
                    command = await self.operator.command(
                        f"Run {self.evidence.run_id} paused ({code}). Type claim or abort: "
                    )
                    if command == "abort":
                        raise AutomationError("OPERATOR_ABORTED")
                    if command == "claim":
                        break
                self.transition(Ownership.HUMAN)
                while True:
                    command = await self.operator.command(
                        "Use the SAME browser. Resolve the issue and reach the requested account. Type resume or abort: "
                    )
                    if command == "abort":
                        raise AutomationError("OPERATOR_ABORTED")
                    if command != "resume":
                        continue
                    # Read-only inspection is allowed during HUMAN; no automated clicks/fills.
                    try:
                        await self.surface.settle()
                        await self.surface.compatible()
                        if await self.surface.signal() == "permission_denied":
                            raise AutomationError("PERMISSION_DENIED")
                        await self.surface.verify(checkpoint)
                    except AutomationError as exc:
                        if exc.code in {
                            "PERMISSION_DENIED",
                            "FORBIDDEN_ORIGIN",
                            "FORBIDDEN_ROUTE",
                            "BANKING_WRITE_BLOCKED",
                        }:
                            raise
                        self.evidence.event(
                            "resume_rejected",
                            step_id=step_id,
                            code="RESUME_CHECKPOINT_FAILED",
                        )
                        continue
                    self.evidence.event(
                        "resume_verified",
                        step_id=step_id,
                        checkpoint="requested active account and balances",
                    )
                    self.transition(Ownership.AUTOMATION)
                    return
        except TimeoutError:
            raise AutomationError("OPERATOR_TIMEOUT") from None
