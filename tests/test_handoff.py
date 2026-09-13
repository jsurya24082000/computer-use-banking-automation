"""SIMULATED operator tests; never presented as real human demonstration evidence."""

from pathlib import Path
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import BrowserType

from automation.evidence import Evidence
from automation.handoff import HandoffController
from automation.models import Action, AutomationError, Ownership, RuntimeConfig
from automation.runner import replay
from automation.surface import BrowserSurface, label_target
from banking_app.app import set_scenario
from .artifacts import executor_artifact


@pytest.mark.browser
async def test_simulated_operator_reauthenticates_same_browser_and_resumes(
    bank, inputs, monkeypatch
):
    set_scenario("session_expiry", str(bank["scenario"]))
    bank["config"].headless = False
    bank["config"].interactive = True
    # CI has no display. Only this test forces the browser launch headless.
    # Production still requires a visible browser; no fake human evidence is published.
    launch = BrowserType.launch

    async def test_launch(self, *args, **kwargs):
        kwargs["headless"] = True
        return await launch(self, *args, **kwargs)

    monkeypatch.setattr(BrowserType, "launch", test_launch)
    surface_holder = {}
    original_enter = BrowserSurface.__aenter__

    async def enter(self):
        surface = await original_enter(self)
        surface_holder["surface"] = surface
        surface_holder["identity"] = (
            id(surface.browser),
            id(surface.context),
            id(surface.page),
        )
        return surface

    monkeypatch.setattr(BrowserSurface, "__aenter__", enter)

    class SimulatedTestOperator:
        calls = 0

        async def command(self, prompt):
            self.calls += 1
            surface = surface_holder["surface"]
            if self.calls == 1:
                assert surface.ownership == Ownership.PAUSED
                return "claim"
            assert surface.ownership == Ownership.HUMAN
            with pytest.raises(AutomationError, match="CONTROL_NOT_OWNED"):
                await surface.execute(
                    Action(
                        kind="fill",
                        target=label_target("Password"),
                        input_ref="staff_password",
                    )
                )
            if self.calls == 2:
                # A stale/early resume signal must not claim success.
                return "resume"
            frame = await surface.frame()
            assert (
                await frame.get_by_role(
                    "heading", name="Staff sign-in", exact=True
                ).count()
                == 1
            )
            # Test harness simulates direct operator actions, NOT automation recovery.
            await frame.get_by_label("Staff username", exact=True).fill(
                inputs.resolve("staff_username")
            )
            await frame.get_by_label("Password", exact=True).fill(
                inputs.resolve("staff_password")
            )
            async with frame.expect_navigation(wait_until="domcontentloaded"):
                await frame.get_by_role("button", name="Sign in", exact=True).click()
            assert (
                id(surface.browser),
                id(surface.context),
                id(surface.page),
            ) == surface_holder["identity"]
            assert await surface.screen() == "account_details"
            return "resume"

    operator = SimulatedTestOperator()
    result = await replay(
        executor_artifact(),
        inputs,
        bank["tenant"],
        bank["config"],
        bank["policy"],
        operator=operator,
    )
    assert result.status == "success", result
    assert result.outputs.available_balance == "4000.75"
    assert operator.calls == 3
    log = Path(bank["config"].evidence_dir, result.run_id, "events.jsonl").read_text()
    assert '"event": "resume_rejected"' in log
    assert '"event": "resume_verified"' in log
    assert '"event": "human_interaction"' in log
    assert '"step_id": "s008"' not in log  # no replay of human-completed work
    for raw in ("10001", "DemoBank!2026", "teller", "4,250.75"):
        assert raw not in log


async def test_operator_timeout_bounded_and_ownership_not_returned(inputs, tmp_path):
    class SilentOperator:
        async def command(self, prompt):
            await asyncio.Event().wait()

    surface = SimpleNamespace(
        ownership=Ownership.AUTOMATION,
        config=RuntimeConfig(
            headless=False, interactive=True, operator_timeout_seconds=1
        ),
        snapshot=AsyncMock(return_value={"screen": "sign_in"}),
    )
    evidence = Evidence(str(tmp_path), "123abc123abc", inputs)
    controller = HandoffController(surface, evidence, SilentOperator())
    with pytest.raises(AutomationError, match="OPERATOR_TIMEOUT"):
        await controller.takeover("s007", "SESSION_EXPIRED")
    assert surface.ownership == Ownership.PAUSED


def test_invalid_ownership_transition(inputs, tmp_path):
    surface = SimpleNamespace(ownership=Ownership.AUTOMATION)
    controller = HandoffController(
        surface, Evidence(str(tmp_path), "abc123abc123", inputs)
    )
    with pytest.raises(AutomationError, match="INVALID_CONTROL_TRANSITION"):
        controller.transition(Ownership.HUMAN)
