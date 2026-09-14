import pytest
import json
import os
import subprocess
import sys
from pathlib import Path

from automation.models import Inputs, Tenant
from automation.evidence import capability_sha256
from automation.qualification import approval_matches, digest_json, qualify
from automation.runner import replay
from .artifacts import executor_artifact


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
