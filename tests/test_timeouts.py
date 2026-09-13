import asyncio
from pathlib import Path
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
