"""Bounded artifact qualification and sanitized approval records."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .evidence import capability_sha256
from .models import BalanceOutputs, Capability, Result, Tenant, TransactionsOutputs
from .policy import PolicyConfig
from .qualification_matrix import (
    BALANCE_CASES,
    TRANSACTION_CASES,
    validate_balance_result,
    validate_transaction_result,
)

SUITE_VERSION = "qualification-v1"

# Workflow-specific declared scenario matrices. Each capability's declared
# `name` selects which independent qualification suite runs against it — a
# transactions capability is never checked against balance expectations
# (and vice versa), and neither suite accepts an unrestricted bypass.
WORKFLOW_CASES = {
    "read_account_balances": BALANCE_CASES,
    "read_recent_transactions": TRANSACTION_CASES,
}
WORKFLOW_VALIDATORS = {
    "read_account_balances": validate_balance_result,
    "read_recent_transactions": validate_transaction_result,
}
WORKFLOW_OUTPUT_TYPES = {
    "read_account_balances": BalanceOutputs,
    "read_recent_transactions": TransactionsOutputs,
}


def digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def approval_path(artifact_path):
    return Path(f"{artifact_path}.approval.json")


def approval_matches(artifact_path, capability, tenant=None, policy=None):
    path = approval_path(artifact_path)
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    approved = capability.model_copy(update={"lifecycle": "approved"})
    binding_match = (
        record.get("tenant_digest") == digest_json(
            tenant.model_dump(mode="json") if tenant else "1.0"
        )
        and record.get("policy_digest") == digest_json(
            policy.model_dump(mode="json") if policy else "read-only-v1"
        )
    )
    return binding_match and (
        record.get("status") == "approved"
        and record.get("artifact_sha256") == capability_sha256(approved)
        and record.get("schema_version") == capability.schema_version
        and record.get("capability_version") == capability.version
        and record.get("compatibility") == capability.compatibility.model_dump(mode="json")
    )


def _result(stdout):
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "status" in value and "code" in value:
            return value
    return None


def qualify(
    artifact_path,
    members=("10001", "10002"),
    product="Primary Savings",
    tenant=None,
    policy=None,
    tenant_path=None,
    policy_path=None,
):
    path = Path(artifact_path)
    capability = Capability.model_validate_json(path.read_text())
    tenant = tenant or Tenant()
    policy = policy or PolicyConfig()
    workflow = capability.name
    declared = WORKFLOW_CASES[workflow]
    validator = WORKFLOW_VALIDATORS[workflow]
    output_type = WORKFLOW_OUTPUT_TYPES[workflow]
    # The declared suite fixes expectations independently of the caller; the
    # requested inputs only select which declared success cases must run.
    # Qualification exists to prove replay across different inputs, so an empty
    # or duplicate-only member list can never approve an artifact.
    requested = [m.strip() for m in members if m and m.strip()]
    unique = list(dict.fromkeys(requested))
    declared_success = {
        (case.member_id, case.product_name): case
        for case in declared
        if case.expected_status == "success"
    }
    undeclared = [
        m for m in unique if (m, product) not in declared_success
    ]
    cases = [
        declared_success[(m, product)]
        for m in unique
        if (m, product) in declared_success
    ] + [case for case in declared if case.expected_status != "success"]
    candidate = Capability.model_validate(
        {**capability.model_dump(), "lifecycle": "approved"}
    )
    suite_error = None
    if not unique:
        suite_error = "empty_input_suite"
    elif len(unique) < 2:
        suite_error = "duplicate_or_single_member_inputs"
    elif undeclared:
        suite_error = "undeclared_expectations"
    results = []
    if suite_error is None:
        with tempfile.TemporaryDirectory(prefix="qualification-") as tmp:
            tenant_file = Path(tmp) / "tenant.json"
            policy_file = Path(tmp) / "policy.json"
            tenant_file.write_text(
                json.dumps(tenant.model_dump(mode="json"))
            )
            policy_file.write_text(
                json.dumps(policy.model_dump(mode="json"))
            )
            candidate_path = Path(tmp) / "candidate.json"
            candidate_path.write_text(candidate.model_dump_json(indent=2))
            for index, case in enumerate(cases, 1):
                evidence_dir = Path(tmp) / f"evidence-{index}"
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "automation.qualification_worker",
                        "--artifact",
                        str(candidate_path),
                        "--member",
                        case.member_id,
                        "--product",
                        case.product_name,
                        "--evidence-dir",
                        str(evidence_dir),
                        "--tenant",
                        str(tenant_path or tenant_file),
                        "--policy",
                        str(policy_path or policy_file),
                    ],
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                parsed = _result(result.stdout)
                run = None
                if parsed and result.returncode == 0:
                    try:
                        run = Result.model_validate(parsed)
                    except ValidationError:
                        run = None
                # The produced output must have this workflow's declared type:
                # a transactions capability can never pass with balance-only
                # output, and a non-success outcome must not carry outputs.
                if run is not None:
                    shape_ok = (
                        isinstance(run.outputs, output_type)
                        if case.expected_status == "success"
                        else run.outputs is None
                    )
                    semantic = shape_ok and validator(run, case)
                else:
                    semantic = False
                results.append(
                    {
                        "slot": index,
                        "case": case.name,
                        "status": "success" if semantic else "failure",
                        "code": "SUCCESS" if semantic else "QUALIFICATION_FAILED",
                        "run_recorded": bool(parsed and parsed.get("run_id")),
                    }
                )
    approved = suite_error is None and bool(results) and all(
        item["status"] == "success" for item in results
    )
    record = {
        "qualification_suite": SUITE_VERSION,
        "capability_name": workflow,
        "status": "approved" if approved else "rejected",
        "suite_error": suite_error,
        "artifact_sha256": capability_sha256(candidate),
        "schema_version": capability.schema_version,
        "capability_version": capability.version,
        "compatibility": capability.compatibility.model_dump(mode="json"),
        "policy_digest": digest_json(
            policy.model_dump(mode="json") if policy else "read-only-v1"
        ),
        "tenant_digest": digest_json(
            tenant.model_dump(mode="json") if tenant else "1.0"
        ),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "provenance": capability.provenance.model_dump(mode="json"),
        "results": results,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    approval_path(path).write_text(json.dumps(record, indent=2) + "\n")
    if approved:
        # Approve in place only when the validated model differs from the file
        # (e.g. a draft). An already-approved historical artifact whose parse is
        # identical keeps its original bytes; the sidecar hash binds the model,
        # so schema additions with defaults do not require rewriting evidence.
        if Capability.model_validate_json(path.read_text()) != candidate:
            path.write_text(candidate.model_dump_json(indent=2) + "\n")
    return record
