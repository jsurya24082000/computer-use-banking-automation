import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import time
import pytest
from automation.discovery import discover
from automation.runner import replay
from banking_app.app import set_scenario
from .artifacts import executor_artifact


class SlowTestProvider:
    simulated = True
    identifier = "slow-offline-test"

    async def decide(self, *args):
        await asyncio.Event().wait()


@pytest.mark.browser
async def test_overall_discovery_timeout(bank, inputs):
    bank["config"].overall_timeout_seconds = 1
    start = time.monotonic()
    result, artifact = await discover(
        "test",
        inputs,
        SlowTestProvider(),
        bank["tenant"],
        bank["config"],
        bank["policy"],
    )
    assert result.code == "OVERALL_TIMEOUT"
    assert time.monotonic() - start < 8
    assert artifact is None


@pytest.mark.browser
async def test_action_timeout_not_blind_retry(bank, inputs):
    set_scenario("slow_account_loading", str(bank["scenario"]))
    bank["config"].action_timeout_ms = 600
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "ACTION_TIMEOUT", result
    events = Path(
        bank["config"].evidence_dir, result.run_id, "events.jsonl"
    ).read_text()
    assert '"event": "recovery"' not in events


@pytest.mark.browser
async def test_recovery_disabled_stops(bank, inputs):
    set_scenario("fail_once", str(bank["scenario"]))
    artifact = executor_artifact()
    artifact.recovery[0].max_attempts = 0
    result = await replay(
        artifact, inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "RECOVERY_EXHAUSTED"


async def test_failure_diagnostics_are_bounded_and_preserve_original_code(tmp_path, inputs, monkeypatch):
    from automation.evidence import Evidence
    from automation.models import AutomationError
    from automation.runner import failure_result

    real_wait_for = asyncio.wait_for

    async def short_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.02)

    async def unavailable_snapshot():
        await asyncio.Event().wait()

    monkeypatch.setattr("automation.runner.asyncio.wait_for", short_wait)
    surface = SimpleNamespace(snapshot=unavailable_snapshot)
    evidence = Evidence(str(tmp_path), "abcdefabcdef", inputs)
    result = await real_wait_for(
        failure_result(AutomationError("OPERATOR_UNAVAILABLE"), surface, evidence, "s007"),
        timeout=0.5,
    )
    assert result.code == "OPERATOR_UNAVAILABLE"
    assert result.status == "intervention_required"


async def test_teardown_cancellation_still_stops_driver():
    from automation.surface import BrowserSurface

    surface = BrowserSurface.__new__(BrowserSurface)
    surface.browser = SimpleNamespace(close=AsyncMock(side_effect=asyncio.CancelledError))
    surface.pw = SimpleNamespace(stop=AsyncMock())
    surface.evidence = Mock()
    with pytest.raises(asyncio.CancelledError):
        await surface.__aexit__(None, None, None)
    surface.pw.stop.assert_awaited_once()


async def test_teardown_timeout_does_not_leave_close_task_running(monkeypatch):
    from automation.surface import BrowserSurface

    real_wait_for = asyncio.wait_for
    finished = asyncio.Event()

    async def short_wait(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.02)

    async def wedged_close():
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    surface = BrowserSurface.__new__(BrowserSurface)
    surface.browser = SimpleNamespace(close=wedged_close)
    surface.pw = SimpleNamespace(stop=AsyncMock())
    surface.evidence = Mock()
    monkeypatch.setattr("automation.surface.asyncio.wait_for", short_wait)
    previous_tasks = asyncio.all_tasks()
    try:
        await surface.__aexit__(None, None, None)
        assert finished.is_set(), "browser close must not outlive teardown"
        surface.pw.stop.assert_awaited_once()
    finally:
        leaked = asyncio.all_tasks() - previous_tasks
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)


@pytest.mark.browser
@pytest.mark.parametrize("repetition", range(3))
@pytest.mark.parametrize(
    "member,product,scenario",
    [
        ("10002", "Primary Savings", "session_expiry"),
        ("10004", "Education Savings", "session_expiry"),
        ("10004", "Education Savings", "blocking_dialog"),
    ],
)
async def test_matrix_intervention_regression(bank, inputs, repetition, member, product, scenario):
    from automation.models import Capability

    artifact = Capability.model_validate_json(
        Path("evidence/discovery-attempts/balances/attempt-2-capability.json").read_text()
    )
    set_scenario(scenario, str(bank["scenario"]))
    inputs.member_id = member
    inputs.product_name = product
    bank["config"].overall_timeout_seconds = 30
    result = await replay(artifact, inputs, bank["tenant"], bank["config"], bank["policy"])
    assert (result.status, result.code) == ("intervention_required", "OPERATOR_UNAVAILABLE"), result
