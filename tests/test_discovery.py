import json
from pathlib import Path
import pytest
from automation.discovery import discover
from automation.provider import FakeProvider
from automation.runner import replay
from automation.models import AutomationError


def scripted():
    return FakeProvider(
        json.loads(Path("tests/fixtures/fake_decisions.json").read_text())
    )


@pytest.mark.browser
async def test_simulated_discovery_compiles_and_replays_new_inputs(
    bank, inputs, monkeypatch
):
    result, artifact = await discover(
        "Read requested active account balances",
        inputs,
        scripted(),
        bank["tenant"],
        bank["config"],
        bank["policy"],
    )
    assert result.status == "success", result
    assert artifact.provenance.kind == "simulated_discovery"
    serialized = artifact.model_dump_json()
    for raw in ("10001", "teller", "DemoBank!2026", "4250.75", bank["origin"]):
        assert raw not in serialized
    assert '"input_ref":"member_id"' in serialized
    inputs.member_id = "10002"
    artifact.lifecycle = "approved"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await replay(
        artifact, inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.status == "success", result
    assert result.outputs.available_balance == "9000.00"


class BadProvider:
    identifier = "invalid-offline-test"
    simulated = True
    calls = 0

    async def decide(self, goal, observation):
        self.calls += 1
        raise AutomationError("INVALID_MODEL_RESPONSE")


@pytest.mark.browser
async def test_invalid_model_response_is_bounded(bank, inputs):
    provider = BadProvider()
    result, artifact = await discover(
        "test", inputs, provider, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "INVALID_MODEL_RESPONSE"
    assert provider.calls == 3
    assert artifact is None


@pytest.mark.browser
async def test_redundant_fill_retries_with_feedback(bank, inputs):
    provider = FakeProvider(
        [
            {
                "action": "fill",
                "description": "Editable field: Staff username; value omitted",
                "input_ref": "staff_username",
            },
            {
                "action": "fill",
                "description": "Editable field: Staff username; value omitted",
                "input_ref": "staff_username",
            },
            {
                "action": "fill",
                "description": "Editable field: Password; value omitted",
                "input_ref": "staff_password",
            },
            *json.loads(Path("tests/fixtures/fake_decisions.json").read_text())[2:],
        ]
    )
    result, artifact = await discover(
        "test", inputs, provider, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.status == "success", result
    assert artifact is not None


@pytest.mark.browser
async def test_model_finish_is_not_success(bank, inputs):
    result, artifact = await discover(
        "test",
        inputs,
        FakeProvider([{"action": "finish"}]),
        bank["tenant"],
        bank["config"],
        bank["policy"],
    )
    assert result.status == "failure"
    assert result.code == "CHECKPOINT_FAILED"
    assert artifact is None


@pytest.mark.browser
async def test_repeated_no_progress_stops(bank, inputs):
    provider = FakeProvider([{"action": "check", "screen": "sign_in"}] * 10)
    result, artifact = await discover(
        "test", inputs, provider, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "NO_PROGRESS"
    assert artifact is None


@pytest.mark.browser
async def test_max_steps_stops(bank, inputs):
    bank["config"].max_steps = 1
    result, artifact = await discover(
        "test", inputs, scripted(), bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "MAX_STEPS"
    assert artifact is None
