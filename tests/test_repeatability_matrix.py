"""Focused, model-free unit tests for tools/repeatability_matrix.py.

These tests exercise the pure decision logic (expected-outcome prediction,
artifact acceptance/rejection, outcome bucketing, and the model-import guard)
without starting a browser or the synthetic bank server, and without ever
importing automation.provider.
"""

import builtins
import importlib.util
from pathlib import Path

import pytest

from automation.evidence import utcnow
from automation.models import (
    BalanceOutputs,
    Provenance,
    RecentTransaction,
    Result,
    Tenant,
    TransactionsOutputs,
)
from automation.policy import PolicyConfig
from tests.artifacts import executor_artifact, transactions_artifact

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "repeatability_matrix.py"


def _load_module():
    """Import the tool as an isolated module, restoring the real __import__
    immediately afterward so its defense-in-depth guard doesn't leak into
    unrelated tests in this same process."""
    original_import = builtins.__import__
    spec = importlib.util.spec_from_file_location(
        "repeatability_matrix_under_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        builtins.__import__ = original_import
    return module


@pytest.fixture(scope="module")
def rm():
    return _load_module()


def test_module_never_imports_provider_and_blocks_it(rm):
    # The module itself must not have imported automation.provider as a
    # side effect of loading, and its guard must actively reject it.
    assert "automation.provider" not in rm.__dict__
    with pytest.raises(RuntimeError):
        rm._guarded_import("automation.provider", {}, {}, (), 0)
    with pytest.raises(RuntimeError):
        rm._guarded_import("automation.provider.fake", {}, {}, (), 0)


@pytest.mark.parametrize(
    "member_id,product,scenario,expected",
    [
        ("10001", "Primary Savings", "normal", ("success", "SUCCESS")),
        ("10001", "Everyday Checking", "normal", ("success", "SUCCESS")),
        ("bad", "Primary Savings", "normal", ("business_outcome", "INVALID_INPUT")),
        ("123456", "Primary Savings", "normal", ("business_outcome", "INVALID_INPUT")),
        ("10001", "Primary Savings", "invalid_member_id", ("business_outcome", "INVALID_INPUT")),
        ("99999", "Primary Savings", "normal", ("business_outcome", "MEMBER_NOT_FOUND")),
        ("10001", "Primary Savings", "member_not_found", ("business_outcome", "MEMBER_NOT_FOUND")),
        ("10005", "Primary Savings", "normal", ("business_outcome", "NO_ELIGIBLE_ACCOUNT")),
        ("10006", "Primary Savings", "normal", ("business_outcome", "NO_ELIGIBLE_ACCOUNT")),
        ("10001", "Primary Savings", "no_matching_active_account", ("business_outcome", "NO_ELIGIBLE_ACCOUNT")),
        ("10007", "Primary Savings", "normal", ("failure", "PERMISSION_DENIED")),
        ("10001", "Primary Savings", "permission_denied", ("failure", "PERMISSION_DENIED")),
        ("10001", "Primary Savings", "session_expiry", ("intervention_required", "OPERATOR_UNAVAILABLE")),
        ("10001", "Primary Savings", "blocking_dialog", ("intervention_required", "OPERATOR_UNAVAILABLE")),
        ("10001", "Primary Savings", "fail_once", ("success", "SUCCESS")),
        ("10001", "Primary Savings", "slow_account_loading", ("success", "SUCCESS")),
    ],
)
def test_expected_outcome_matches_seed_data(rm, member_id, product, scenario, expected):
    assert rm.expected_outcome(member_id, product, scenario) == expected


def test_bucket_for_maps_each_status(rm):
    assert rm.bucket_for("success") == "extraction_success"
    assert rm.bucket_for("business_outcome") == "business_outcome"
    assert rm.bucket_for("intervention_required") == "intervention_required"
    assert rm.bucket_for("failure") == "failure"
    assert rm.bucket_for("something_unexpected") == "failure"


def test_evaluate_artifact_rejects_missing_file(rm, tmp_path):
    tenant = Tenant()
    policy = PolicyConfig()
    capability, info = rm.evaluate_artifact(str(tmp_path / "nope.json"), tenant, policy)
    assert capability is None
    assert info["accepted"] is False
    assert info["reason"] == "artifact_file_not_found"


def test_evaluate_artifact_rejects_invalid_schema(rm, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    capability, info = rm.evaluate_artifact(str(bad), Tenant(), PolicyConfig())
    assert capability is None
    assert info["accepted"] is False
    assert info["reason"].startswith("invalid_capability_schema:")


def test_evaluate_artifact_rejects_llm_discovery_without_approval_sidecar(rm, tmp_path):
    cap = executor_artifact()
    cap = cap.model_copy(
        update={
            "provenance": Provenance(
                kind="llm_discovery",
                run_id="abcdef012345",
                provider="fake",
                created_at=utcnow(),
            )
        }
    )
    path = tmp_path / "artifact.json"
    path.write_text(cap.model_dump_json(indent=2))
    capability, info = rm.evaluate_artifact(str(path), Tenant(), PolicyConfig())
    assert capability is None
    assert info["accepted"] is False
    assert info["reason"] == "missing_or_stale_qualification_approval"
    assert "PRIOR LLM DISCOVERY" in info["label"]


def test_evaluate_artifact_rejects_non_approved_lifecycle(rm, tmp_path):
    cap = executor_artifact().model_copy(update={"lifecycle": "draft"})
    path = tmp_path / "artifact.json"
    path.write_text(cap.model_dump_json(indent=2))
    capability, info = rm.evaluate_artifact(str(path), Tenant(), PolicyConfig())
    assert capability is None
    assert info["accepted"] is False
    assert info["reason"] == "lifecycle_not_approved:draft"


def test_evaluate_artifact_accepts_hand_authored_executor_artifact(rm, tmp_path):
    cap = executor_artifact()
    path = tmp_path / "artifact.json"
    path.write_text(cap.model_dump_json(indent=2))
    capability, info = rm.evaluate_artifact(str(path), Tenant(), PolicyConfig())
    assert capability is not None
    assert info["accepted"] is True
    assert "HAND-AUTHORED" in info["label"]
    assert info["reason"] is None


def test_combo_generation_preserves_every_requested_run(rm):
    combo_template = [
        ("artifactA", "10001", "Primary Savings", "normal"),
        ("artifactB", "10002", "Everyday Checking", "member_not_found"),
    ]
    import itertools

    cases = list(itertools.islice(itertools.cycle(combo_template), 5))
    assert len(cases) == 5
    # Cycling must repeat deterministically, never drop or randomize attempts.
    assert cases == [
        combo_template[0],
        combo_template[1],
        combo_template[0],
        combo_template[1],
        combo_template[0],
    ]


def _balance_result():
    return Result(
        status="success",
        code="SUCCESS",
        run_id="abcdefabcdef",
        outputs=BalanceOutputs(
            member_id="10001",
            product_name="Primary Savings",
            account_status="Active",
            currency="USD",
            current_balance="4250.75",
            available_balance="4000.75",
            active_holds="250.00",
            as_of="2026-09-13T12:00:00Z",
        ),
    )


def _transactions_result():
    return Result(
        status="success",
        code="SUCCESS",
        run_id="abcdefabcdef",
        outputs=TransactionsOutputs(
            member_id="10001",
            product_name="Primary Savings",
            account_status="Active",
            transactions=[
                RecentTransaction(
                    posted_at="2026-09-12",
                    description="Synthetic payroll credit",
                    amount="150.00",
                    ledger_balance="4250.75",
                ),
                RecentTransaction(
                    posted_at="2026-09-10",
                    description="Opening ledger balance",
                    amount="4100.75",
                    ledger_balance="4100.75",
                ),
            ],
        ),
    )


def test_verify_outputs_dispatches_on_declared_workflow(rm):
    balances = executor_artifact()
    transactions = transactions_artifact()
    assert rm.verify_outputs(
        balances, "10001", "Primary Savings", _balance_result()
    )
    assert rm.verify_outputs(
        transactions, "10001", "Primary Savings", _transactions_result()
    )
    # The wrong output type must fail verification, never skip it.
    assert not rm.verify_outputs(
        transactions, "10001", "Primary Savings", _balance_result()
    )
    assert not rm.verify_outputs(
        balances, "10001", "Primary Savings", _transactions_result()
    )


def test_verify_outputs_rejects_incorrect_values(rm):
    balances = executor_artifact()
    wrong = _balance_result()
    wrong.outputs.current_balance = "1.00"
    assert not rm.verify_outputs(
        balances, "10001", "Primary Savings", wrong
    )
    reordered = _transactions_result()
    reordered.outputs.transactions.reverse()
    assert not rm.verify_outputs(
        transactions_artifact(), "10001", "Primary Savings", reordered
    )


def _record(iteration, artifact, category, matches=True, verified=None):
    return {
        "iteration": iteration,
        "artifact": artifact,
        "category": category,
        "matches_expectation": matches,
        "outputs_verified_in_memory": verified,
    }


def test_assess_passes_only_clean_complete_runs(rm):
    reports = {"a": {"accepted": True}, "b": {"accepted": True}}
    records = [
        _record(1, "a", "extraction_success", verified=True),
        _record(2, "b", "extraction_success", verified=True),
    ]
    assert rm.assess(records, reports, 2)["ok"] is True


def test_assess_fails_on_incorrect_outputs(rm):
    # Status/code matched expectations but the returned values did not.
    reports = {"a": {"accepted": True}}
    records = [_record(1, "a", "extraction_success", verified=False)]
    verdict = rm.assess(records, reports, 1)
    assert verdict["ok"] is False
    assert verdict["unverified_output_iterations"] == [1]


def test_assess_fails_on_rejected_required_artifact(rm):
    reports = {
        "a": {"accepted": True},
        "b": {"accepted": False, "reason": "missing_or_stale_qualification_approval"},
    }
    records = [
        _record(1, "a", "extraction_success", verified=True),
        _record(2, "b", "rejected_artifact", matches=False),
    ]
    verdict = rm.assess(records, reports, 2)
    assert verdict["ok"] is False
    assert verdict["rejected_required_artifacts"] == ["b"]
    assert verdict["uncovered_artifacts"] == ["b"]


def test_assess_fails_on_incomplete_coverage(rm):
    reports = {"a": {"accepted": True}, "b": {"accepted": True}}
    # Artifact b was requested but never exercised.
    records = [_record(1, "a", "extraction_success", verified=True)]
    verdict = rm.assess(records, reports, 1)
    assert verdict["ok"] is False
    assert verdict["uncovered_artifacts"] == ["b"]
    # Fewer attempts than requested is also incomplete coverage.
    verdict = rm.assess(records, {"a": {"accepted": True}}, 5)
    assert verdict["ok"] is False
