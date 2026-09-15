import pytest
import json
import os
import subprocess
import sys
from pathlib import Path

from automation.models import (
    BalanceOutputs,
    Inputs,
    RecentTransaction,
    Result,
    Tenant,
    TransactionsOutputs,
)
from automation.evidence import capability_sha256
from automation.qualification import (
    WORKFLOW_CASES,
    approval_matches,
    digest_json,
    qualify,
)
from automation.qualification_matrix import (
    EXPECTED_BALANCES,
    EXPECTED_TRANSACTIONS,
)
from automation.policy import PolicyConfig
from automation.runner import replay
from .artifacts import executor_artifact, transactions_artifact


@pytest.mark.asyncio
async def test_draft_artifact_is_rejected_before_browser_work(bank):
    artifact = executor_artifact()
    artifact.lifecycle = "draft"
    result = await replay(
        artifact,
        Inputs(
            member_id="10001",
            product_name="Primary Savings",
            staff_username="teller",
            staff_password="DemoBank!2026",
        ),
        bank["tenant"],
        bank["config"],
        bank["policy"],
    )
    assert result.code == "ARTIFACT_NOT_APPROVED"


def test_approval_rejects_missing_tampered_and_stale_bindings(tmp_path):
    artifact = executor_artifact()
    artifact.provenance.kind = "llm_discovery"
    artifact.provenance.run_id = "abcdefabcdef"
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    assert not approval_matches(artifact_path, artifact)
    approved = artifact.model_copy(update={"lifecycle": "approved"})
    record = {
        "status": "approved",
        "artifact_sha256": capability_sha256(approved),
        "schema_version": artifact.schema_version,
        "capability_version": artifact.version,
        "compatibility": artifact.compatibility.model_dump(mode="json"),
        "policy_digest": digest_json("read-only-v1"),
        "tenant_digest": digest_json("1.0"),
    }
    Path(f"{artifact_path}.approval.json").write_text(json.dumps(record))
    assert approval_matches(artifact_path, artifact)
    artifact.description = "tampered"
    assert not approval_matches(artifact_path, artifact)
    assert not approval_matches(artifact_path, artifact, Tenant())


def test_capability_can_be_reapproved_per_tenant_but_binding_changes_invalidate(
    tmp_path,
):
    artifact = executor_artifact()
    artifact.provenance.kind = "llm_discovery"
    artifact.provenance.run_id = "abcdefabcdef"
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    secondary = Tenant(tenant_id="secondary", binding_version="1.1")
    approved = artifact.model_copy(update={"lifecycle": "approved"})

    def write_approval(tenant, policy, compatibility=None, status="approved"):
        record = {
            "status": status,
            "artifact_sha256": capability_sha256(approved),
            "schema_version": artifact.schema_version,
            "capability_version": artifact.version,
            "compatibility": (
                compatibility or artifact.compatibility
            ).model_dump(mode="json"),
            "policy_digest": digest_json(policy),
            "tenant_digest": digest_json(tenant),
        }
        Path(f"{artifact_path}.approval.json").write_text(json.dumps(record))

    primary = Tenant()
    policy = PolicyConfig()
    write_approval(primary.model_dump(mode="json"), policy.model_dump(mode="json"))
    assert approval_matches(artifact_path, artifact, primary, policy)
    assert not approval_matches(artifact_path, artifact, secondary, policy)
    write_approval(
        secondary.model_dump(mode="json"),
        policy.model_dump(mode="json"),
    )
    assert approval_matches(artifact_path, artifact, secondary, policy)
    changed_policy = PolicyConfig(version="read-only-v2")
    assert not approval_matches(artifact_path, artifact, secondary, changed_policy)
    changed_compatibility = artifact.compatibility.model_copy(update={"ui_version": "2.0"})
    stale_artifact = artifact.model_copy(update={"compatibility": changed_compatibility})
    assert not approval_matches(
        artifact_path, stale_artifact, secondary, policy
    )
    write_approval(
        secondary.model_dump(mode="json"),
        policy.model_dump(mode="json"),
        compatibility=changed_compatibility,
    )
    assert not approval_matches(artifact_path, artifact, secondary, policy)
    write_approval(
        secondary.model_dump(mode="json"),
        policy.model_dump(mode="json"),
        status="rejected",
    )
    assert not approval_matches(artifact_path, artifact, secondary, policy)


def test_internal_environment_marker_does_not_bypass_normal_replay(tmp_path):
    artifact = executor_artifact()
    artifact.provenance.kind = "llm_discovery"
    artifact.provenance.run_id = "abcdefabcdef"
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "automation.cli",
            "replay",
            "--artifact",
            str(artifact_path),
            "--member",
            "10001",
            "--product",
            "Primary Savings",
        ],
        env={
            **os.environ,
            "AUTOMATION_QUALIFICATION_INTERNAL": "1",
            "BANK_STAFF_USER": "teller",
            "BANK_STAFF_PASSWORD": "x",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert "MISSING_APPROVAL" in process.stdout


def test_cli_rejects_missing_approval_before_browser(tmp_path):
    artifact = executor_artifact()
    artifact.provenance.kind = "llm_discovery"
    artifact.provenance.run_id = "abcdefabcdef"
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "automation.cli",
            "replay",
            "--artifact",
            str(artifact_path),
            "--member",
            "10001",
            "--product",
            "Primary Savings",
        ],
        env={**os.environ, "BANK_STAFF_USER": "teller", "BANK_STAFF_PASSWORD": "x"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert "MISSING_APPROVAL" in process.stdout


def test_qualification_rejects_semantically_wrong_outputs(tmp_path, monkeypatch):
    artifact = executor_artifact()
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "status": "success",
                "code": "SUCCESS",
                "run_id": "abcdefabcdef",
                "outputs": {
                    "member_id": "10001",
                    "product_name": "Primary Savings",
                    "account_status": "Active",
                    "current_balance": "1.00",
                    "available_balance": "1.00",
                    "active_holds": "0.00",
                },
            }
        )

    monkeypatch.setattr("automation.qualification.subprocess.run", lambda *a, **k: Completed())
    record = qualify(artifact_path)
    assert record["status"] == "rejected"
    assert record["results"][0]["run_recorded"] is True


def _fake_worker(case_lookup):
    """Qualification-worker stub returning declared-correct results per case."""
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if "automation.qualification_worker" not in cmd:
            return real_run(cmd, *args, **kwargs)
        member = cmd[cmd.index("--member") + 1]
        product = cmd[cmd.index("--product") + 1]
        case = case_lookup[(member, product)]

        class Completed:
            pass

        completed = Completed()
        completed.returncode = 0
        if case.expected_status == "success":
            if case in WORKFLOW_CASES["read_recent_transactions"]:
                outputs = TransactionsOutputs(
                    member_id=member,
                    product_name=product,
                    account_status="Active",
                    transactions=[
                        RecentTransaction(
                            posted_at=posted,
                            description="Synthetic entry",
                            amount=amount,
                            ledger_balance=balance,
                        )
                        for posted, amount, balance in EXPECTED_TRANSACTIONS[
                            member
                        ]
                    ],
                ).model_dump(mode="json")
            else:
                current, available, holds = EXPECTED_BALANCES[member]
                outputs = BalanceOutputs(
                    member_id=member,
                    product_name=product,
                    account_status="Active",
                    currency="USD",
                    current_balance=current,
                    available_balance=available,
                    active_holds=holds,
                    as_of="2026-09-13T12:00:00Z",
                ).model_dump(mode="json")
            completed.stdout = json.dumps(
                Result(
                    status="success", code="SUCCESS", run_id="abcdefabcdef"
                ).model_dump()
                | {"outputs": outputs}
            )
        else:
            completed.stdout = json.dumps(
                {
                    "status": case.expected_status,
                    "code": case.expected_code,
                    "run_id": "abcdefabcdef",
                }
            )
        return completed

    return run


@pytest.mark.parametrize(
    "artifact_factory,workflow",
    [
        (executor_artifact, "read_account_balances"),
        (transactions_artifact, "read_recent_transactions"),
    ],
)
def test_qualification_approves_declared_suite(
    tmp_path, monkeypatch, artifact_factory, workflow
):
    artifact = artifact_factory()
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json())
    cases = WORKFLOW_CASES[workflow]
    case_lookup = {(c.member_id, c.product_name): c for c in cases}
    monkeypatch.setattr(
        "automation.qualification.subprocess.run", _fake_worker(case_lookup)
    )
    record = qualify(artifact_path)
    assert record["status"] == "approved", record
    assert record["suite_error"] is None
    assert record["capability_name"] == workflow
    assert len(record["results"]) == len(cases)
    assert all(r["status"] == "success" for r in record["results"])
    assert approval_matches(artifact_path, artifact, Tenant(), PolicyConfig())


def test_qualification_rejects_outputs_on_business_outcome(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(executor_artifact().model_dump_json())

    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if "automation.qualification_worker" not in cmd:
            return real_run(cmd, *args, **kwargs)
        member = cmd[cmd.index("--member") + 1]
        product = cmd[cmd.index("--product") + 1]
        case_lookup = {
            (c.member_id, c.product_name): c
            for c in WORKFLOW_CASES["read_account_balances"]
        }
        case = case_lookup[(member, product)]
        outputs = None
        if case.expected_status == "success":
            current, available, holds = EXPECTED_BALANCES[member]
            outputs = BalanceOutputs(
                member_id=member,
                product_name=product,
                account_status="Active",
                currency="USD",
                current_balance=current,
                available_balance=available,
                active_holds=holds,
                as_of="2026-09-13T12:00:00Z",
            ).model_dump(mode="json")
        else:
            # A business outcome must never carry extraction outputs.
            outputs = BalanceOutputs(
                member_id="10001",
                product_name="Primary Savings",
                account_status="Active",
                currency="USD",
                current_balance="4250.75",
                available_balance="4000.75",
                active_holds="250.00",
                as_of="2026-09-13T12:00:00Z",
            ).model_dump(mode="json")

        class Completed:
            pass

        completed = Completed()
        completed.returncode = 0
        completed.stdout = json.dumps(
            {
                "status": case.expected_status,
                "code": case.expected_code,
                "run_id": "abcdefabcdef",
                "outputs": outputs,
            }
        )
        return completed

    monkeypatch.setattr("automation.qualification.subprocess.run", run)
    record = qualify(artifact_path)
    assert record["status"] == "rejected"
    failed = [r for r in record["results"] if r["status"] == "failure"]
    assert {r["case"] for r in failed} == {"missing-member", "closed-product"}
