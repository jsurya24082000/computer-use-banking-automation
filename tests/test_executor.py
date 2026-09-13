from pathlib import Path
import pytest
from automation.runner import replay
from automation.evidence import capability_sha256
from banking_app.app import set_scenario
from .artifacts import executor_artifact


@pytest.mark.browser
async def test_hand_authored_executor_primary(bank, inputs):
    artifact = executor_artifact()
    result = await replay(artifact, inputs, bank["tenant"], bank["config"], bank["policy"])
    assert result.status == "success", result
    assert result.outputs.current_balance == "4250.75"
    assert result.outputs.available_balance == "4000.75"
    assert result.outputs.active_holds == "250.00"
    events = (
        Path(bank["config"].evidence_dir) / result.run_id / "events.jsonl"
    ).read_text()
    assert f'"event": "replay_started"' in events
    assert f'"capability_sha256": "{capability_sha256(artifact)}"' in events


@pytest.mark.browser
async def test_executor_second_member_without_model(bank, inputs, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    inputs.member_id = "10002"
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.status == "success", result
    assert result.outputs.current_balance == "9123.45"
    assert result.outputs.available_balance == "9000.00"


@pytest.mark.browser
async def test_product_parameter_selects_different_savings_product(bank, inputs):
    inputs.member_id = "10004"
    inputs.product_name = "Education Savings"
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.status == "success", result
    assert result.outputs.product_name == "Education Savings"
    assert result.outputs.current_balance == "7000.00"


@pytest.mark.browser
async def test_closed_requested_product_is_business_outcome(bank, inputs):
    inputs.product_name = "Holiday Savings"
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.code == "NO_ELIGIBLE_ACCOUNT"


@pytest.mark.browser
@pytest.mark.parametrize(
    "member,scenario,expected_status,code",
    [
        ("99999", "normal", "business_outcome", "MEMBER_NOT_FOUND"),
        ("bad", "normal", "business_outcome", "INVALID_INPUT"),
        ("10005", "normal", "business_outcome", "NO_ELIGIBLE_ACCOUNT"),
        ("10006", "normal", "business_outcome", "NO_ELIGIBLE_ACCOUNT"),
        ("10007", "normal", "failure", "PERMISSION_DENIED"),
        ("10001", "permission_denied", "failure", "PERMISSION_DENIED"),
        ("10001", "session_expiry", "intervention_required", "OPERATOR_UNAVAILABLE"),
        ("10001", "blocking_dialog", "intervention_required", "OPERATOR_UNAVAILABLE"),
        (
            "10001",
            "no_matching_active_account",
            "business_outcome",
            "NO_ELIGIBLE_ACCOUNT",
        ),
        ("10001", "invalid_member_id", "business_outcome", "INVALID_INPUT"),
        ("10001", "member_not_found", "business_outcome", "MEMBER_NOT_FOUND"),
    ],
)
async def test_outcomes(bank, inputs, member, scenario, expected_status, code):
    inputs.member_id = member
    set_scenario(scenario, str(bank["scenario"]))
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert (result.status, result.code) == (expected_status, code), result


@pytest.mark.browser
@pytest.mark.parametrize("scenario", ["slow_account_loading", "fail_once"])
async def test_recovery(bank, inputs, scenario):
    set_scenario(scenario, str(bank["scenario"]))
    result = await replay(
        executor_artifact(), inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert result.status == "success", result
    assert result.outputs.available_balance == "4000.75"
    if scenario == "fail_once":
        from pathlib import Path

        log = Path(
            bank["config"].evidence_dir, result.run_id, "events.jsonl"
        ).read_text()
        assert '"event": "recovery"' in log
