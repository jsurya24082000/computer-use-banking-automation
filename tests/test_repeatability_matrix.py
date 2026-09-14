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
from automation.models import Provenance, Tenant
from automation.policy import PolicyConfig
from tests.artifacts import executor_artifact

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
