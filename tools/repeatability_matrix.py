"""Model-free repeatability matrix across >=100 varied, approved-artifact replays.

This tool never imports or invokes an LLM provider. It reuses the existing
CLI/runner code paths (`automation.runner.replay`, `banking_app.app.set_scenario`,
`banking_app.db.seed`) directly, in-process, to run many bounded, deterministic
replay attempts against a *previously discovered and separately approved*
capability artifact.

It assumes the synthetic bank is already running on the configured tenant
entry point (default: `python -m automation.cli serve`, after
`python -m automation.cli seed`), exactly like the other tools in this
directory (`repeatability.py`, `discovery_attempts.py`).

What this script does NOT do:
  * It never imports `automation.provider` (a guard raises if anything tries).
  * It never fabricates success for an artifact that is not `lifecycle == "approved"`
    or (for `llm_discovery` artifacts) lacks a matching qualification approval
    sidecar (`<artifact>.approval.json`) -- such artifacts are rejected and the
    rejection itself is recorded, not silently skipped.
  * It never claims a `hand_authored_executor_test` or `simulated_discovery`
    artifact is genuine LLM evidence; each artifact's provenance is labeled
    explicitly in the report.

Outcome classification (every attempt is preserved, in this exact order):
  * "rejected_artifact"     -- the artifact itself was not eligible to run.
  * "extraction_success"    -- capability read the requested balances (status=="success").
  * "business_outcome"      -- a correct business decision (invalid input, member
                               not found, no eligible account) -- NOT a failure.
  * "intervention_required" -- automation correctly refused to proceed without a
                               real human operator (status=="intervention_required");
                               this is a safe refusal, never a fabricated handoff.
  * "failure"                -- a genuine failure (e.g. permission denied, or an
                               unexpected runtime problem).
Each record also carries `matches_expectation` comparing the observed
(status, code) against the outcome predicted from the synthetic seed data, so a
mismatch (a real bug) is visible instead of being folded into a raw "failure" count.
"""

import argparse
import asyncio
import itertools
import json
import re
import statistics
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- Defense in depth: this tool must never import a model provider. ---
import builtins

_real_import = builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "automation.provider" or name.startswith("automation.provider."):
        raise RuntimeError(
            "repeatability_matrix must never import automation.provider (model access)"
        )
    return _real_import(name, globals, locals, fromlist, level)


builtins.__import__ = _guarded_import

import httpx

from automation.evidence import capability_sha256
from automation.models import (
    BalanceOutputs,
    Capability,
    Inputs,
    RuntimeConfig,
    Tenant,
    TransactionsOutputs,
)
from automation.policy import PolicyConfig
from automation.qualification import approval_matches
from automation.runner import replay
from banking_app.app import set_scenario
from banking_app.db import seed as seed_bank

# Synthetic seed truth (banking_app/db.py). Used only to predict the correct
# business outcome for a combination, never to fabricate a replay result.
# "transactions" rows are (posted_at, amount, ledger_balance) in the app's
# newest-first display order.
ACCOUNTS = {
    ("10001", "Primary Savings"): {"status": "Active", "balances": ("4250.75", "4000.75", "250.00"), "transactions": (("2026-09-12", "150.00", "4250.75"), ("2026-09-10", "4100.75", "4100.75"))},
    ("10001", "Everyday Checking"): {"status": "Active", "balances": ("1840.20", "1840.20", "0.00"), "transactions": (("2026-09-12", "150.00", "1840.20"), ("2026-09-10", "1690.20", "1690.20"))},
    ("10001", "Holiday Savings"): {"status": "Closed"},
    ("10002", "Primary Savings"): {"status": "Active", "balances": ("9123.45", "9000.00", "123.45"), "transactions": (("2026-09-12", "150.00", "9123.45"), ("2026-09-10", "8973.45", "8973.45"))},
    ("10003", "Primary Savings"): {"status": "Active", "balances": ("670.00", "670.00", "0.00"), "transactions": (("2026-09-12", "150.00", "670.00"), ("2026-09-10", "520.00", "520.00"))},
    ("10004", "Primary Savings"): {"status": "Active", "balances": ("1250.00", "1250.00", "0.00"), "transactions": (("2026-09-12", "150.00", "1250.00"), ("2026-09-10", "1100.00", "1100.00"))},
    ("10004", "Education Savings"): {"status": "Active", "balances": ("7000.00", "7000.00", "0.00"), "transactions": (("2026-09-12", "150.00", "7000.00"), ("2026-09-10", "6850.00", "6850.00"))},
    ("10005", "Everyday Checking"): {"status": "Active", "balances": ("800.00", "800.00", "0.00"), "transactions": (("2026-09-12", "150.00", "800.00"), ("2026-09-10", "650.00", "650.00"))},
    ("10006", "Primary Savings"): {"status": "Closed"},
    ("10007", "Primary Savings"): {"status": "Active", "restricted": True},
    ("10008", "Primary Savings"): {"status": "Active", "balances": ("720.00", "720.00", "0.00"), "transactions": (("2026-09-12", "150.00", "720.00"), ("2026-09-10", "570.00", "570.00"))},
    ("10009", "Primary Savings"): {"status": "Active", "balances": ("860.00", "860.00", "0.00"), "transactions": (("2026-09-12", "150.00", "860.00"), ("2026-09-10", "710.00", "710.00"))},
    ("10010", "Primary Savings"): {"status": "Active", "balances": ("940.00", "940.00", "0.00"), "transactions": (("2026-09-12", "150.00", "940.00"), ("2026-09-10", "790.00", "790.00"))},
}
MEMBERS = {"10001", "10002", "10003", "10004", "10005", "10006", "10007", "10008", "10009", "10010"}

PROVENANCE_LABELS = {
    "llm_discovery": "PRIOR LLM DISCOVERY -- this replay matrix never calls a model",
    "simulated_discovery": "SIMULATED DISCOVERY -- not genuine LLM evidence",
    "hand_authored_executor_test": "HAND-AUTHORED EXECUTOR TEST ARTIFACT -- no model ever involved",
}

DEFAULT_SCENARIOS = (
    "normal",
    "member_not_found",
    "invalid_member_id",
    "no_matching_active_account",
    "permission_denied",
    "session_expiry",
    "blocking_dialog",
    "fail_once",
    "slow_account_loading",
)


def expected_outcome(member_id: str, product_name: str, scenario: str):
    """Predict the correct (status, code) from synthetic seed data + scenario."""
    if not re.fullmatch(r"[0-9]{5}", member_id) or scenario == "invalid_member_id":
        return "business_outcome", "INVALID_INPUT"
    if scenario == "member_not_found":
        return "business_outcome", "MEMBER_NOT_FOUND"
    if member_id not in MEMBERS:
        return "business_outcome", "MEMBER_NOT_FOUND"
    if scenario == "no_matching_active_account":
        return "business_outcome", "NO_ELIGIBLE_ACCOUNT"
    account = ACCOUNTS.get((member_id, product_name))
    if not account or account["status"] != "Active":
        return "business_outcome", "NO_ELIGIBLE_ACCOUNT"
    if scenario == "permission_denied" or account.get("restricted"):
        return "failure", "PERMISSION_DENIED"
    if scenario in ("session_expiry", "blocking_dialog"):
        return "intervention_required", "OPERATOR_UNAVAILABLE"
    return "success", "SUCCESS"


def bucket_for(status: str) -> str:
    return {
        "success": "extraction_success",
        "business_outcome": "business_outcome",
        "intervention_required": "intervention_required",
        "failure": "failure",
    }.get(status, "failure")


def verify_outputs(capability, member_id: str, product_name: str, result) -> bool:
    """In-memory semantic check of produced outputs against declared seed truth.

    Dispatches on the capability's declared workflow name, so a transactions
    artifact is verified against expected transaction rows (never balances) and
    a balance artifact against expected balance fields. A wrong output type or
    an account without declared expectations is a failed verification, not a
    skipped one.
    """
    outputs = result.outputs
    if (
        result.status != "success"
        or result.code != "SUCCESS"
        or not isinstance(outputs, (BalanceOutputs, TransactionsOutputs))
        or outputs.member_id != member_id
        or outputs.product_name != product_name
        or outputs.account_status != "Active"
    ):
        return False
    account = ACCOUNTS.get((member_id, product_name), {})
    if capability.name == "read_recent_transactions":
        expected = account.get("transactions")
        return bool(
            isinstance(outputs, TransactionsOutputs)
            and expected is not None
            and tuple(
                (row.posted_at, row.amount, row.ledger_balance)
                for row in outputs.transactions
            )
            == expected
        )
    expected = account.get("balances")
    return bool(
        isinstance(outputs, BalanceOutputs)
        and expected
        and (
            outputs.current_balance,
            outputs.available_balance,
            outputs.active_holds,
        )
        == expected
    )


def assess(records, artifact_reports, requested_runs: int, required_combinations=()) -> dict:
    """Decide whether the recorded matrix run may be reported as passing.

    A run fails when any expected outcome mismatches, any successful extraction
    produced unverified or incorrectly typed outputs, any *requested* artifact
    was rejected (rejection is recorded but never substitutes for coverage), or
    coverage is incomplete: fewer attempts than requested, or a requested
    artifact that was never exercised.
    """
    mismatches = [
        r["iteration"]
        for r in records
        if not r["matches_expectation"] and r["category"] != "rejected_artifact"
    ]
    unverified = [
        r["iteration"]
        for r in records
        if r["outputs_verified_in_memory"] is False
        or (r["category"] == "extraction_success" and r["outputs_verified_in_memory"] is not True)
    ]
    rejected = [
        path for path, info in artifact_reports.items() if not info["accepted"]
    ]
    exercised = {
        r["artifact"] for r in records if r["category"] != "rejected_artifact"
    }
    uncovered = [p for p in artifact_reports if p not in exercised]
    observed_combinations = {
        (r["artifact"], r.get("member_slot"), r.get("product"), r.get("scenario"))
        for r in records if r["category"] != "rejected_artifact"
    }
    missing = [c for c in required_combinations if c not in observed_combinations]
    ok = (
        not mismatches
        and not unverified
        and not rejected
        and not uncovered
        and not missing
        and bool(records)
        and len(records) == requested_runs
    )
    return {
        "unexpected_mismatch_iterations": mismatches,
        "unverified_output_iterations": unverified,
        "rejected_required_artifacts": rejected,
        "uncovered_artifacts": uncovered,
        "missing_combinations": missing,
        "ok": ok,
    }


def evaluate_artifact(path_str: str, tenant: Tenant, policy: PolicyConfig):
    """Load and gate one artifact. Rejects anything not genuinely approved.

    Returns (capability_or_None, info_dict). `info_dict["accepted"]` is False
    for any artifact that is missing, invalid, not `lifecycle == "approved"`,
    or (for llm_discovery artifacts) lacking a matching qualification approval
    sidecar. A rejection is reported, never silently substituted with success.
    """
    path = Path(path_str)
    if not path.exists():
        return None, {
            "path": path_str,
            "accepted": False,
            "label": "MISSING ARTIFACT",
            "reason": "artifact_file_not_found",
        }
    try:
        capability = Capability.model_validate_json(path.read_text())
    except Exception as exc:  # noqa: BLE001 - reported, never raised further
        return None, {
            "path": path_str,
            "accepted": False,
            "label": "INVALID ARTIFACT",
            "reason": f"invalid_capability_schema:{type(exc).__name__}",
        }
    label = PROVENANCE_LABELS.get(capability.provenance.kind, capability.provenance.kind)
    if capability.lifecycle != "approved":
        return None, {
            "path": path_str,
            "accepted": False,
            "label": label,
            "reason": f"lifecycle_not_approved:{capability.lifecycle}",
        }
    if capability.provenance.kind == "llm_discovery" and not approval_matches(
        path_str, capability, tenant, policy
    ):
        return None, {
            "path": path_str,
            "accepted": False,
            "label": label,
            "reason": "missing_or_stale_qualification_approval",
        }
    return capability, {
        "path": path_str,
        "accepted": True,
        "label": label,
        "reason": None,
        "provenance_kind": capability.provenance.kind,
        "capability_sha256": capability_sha256(capability),
    }


def read_model(path, model):
    return model.model_validate_json(Path(path).read_text()) if path else model()


async def run_one(capability, member_id, product_name, scenario, tenant, policy, evidence_dir):
    set_scenario(scenario)
    inputs = Inputs(
        member_id=member_id,
        product_name=product_name,
        staff_username="teller",
        staff_password="DemoBank!2026",
    )
    config = RuntimeConfig(
        headless=True,
        interactive=False,
        overall_timeout_seconds=30,
        evidence_dir=str(evidence_dir),
    )
    started = time.monotonic()
    result = await replay(capability, inputs, tenant, config, policy)
    elapsed = round(time.monotonic() - started, 3)
    return result, elapsed


def check_bank_reachable(tenant: Tenant):
    try:
        response = httpx.get(tenant.entry_url, timeout=5, trust_env=False)
        return response.status_code == 200
    except httpx.TransportError:
        return False


async def main():
    parser = argparse.ArgumentParser(
        description=(
            "Run a varied, model-free matrix of deterministic replays against "
            "previously approved artifacts. Requires the synthetic bank already "
            "running (python -m automation.cli seed && python -m automation.cli serve)."
        )
    )
    parser.add_argument("--runs", type=int, default=100, help="Total attempts to record (>=100 recommended)")
    parser.add_argument(
        "--artifacts",
        default="artifacts/read-account-balances.json,artifacts/read-recent-transactions.json",
        help="Comma-separated artifact paths",
    )
    parser.add_argument(
        "--members",
        default="10001,10002,10004,10005,10006,10007",
        help="Comma-separated member IDs",
    )
    parser.add_argument(
        "--products",
        default="Primary Savings,Everyday Checking,Education Savings",
        help="Comma-separated product names",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(DEFAULT_SCENARIOS),
        help="Comma-separated developer scenario names to cycle through",
    )
    parser.add_argument("--tenant", default="config/tenant.json")
    parser.add_argument("--policy", default="config/policy.json")
    parser.add_argument("--out", default="evidence/repeatability-matrix.json")
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip resetting the synthetic bank database before running",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")

    destination = Path(args.out)
    evidence_root = destination.parent / f"{destination.stem}-runs"
    if destination.exists() or evidence_root.exists():
        parser.error("Output or evidence directory already exists; choose a new --out path")
    source_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    source_dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain", "--", "automation", "banking_app", "tools", "config"],
        cwd=ROOT, text=True,
    ).strip())
    tenant = read_model(args.tenant, Tenant)
    policy = read_model(args.policy, PolicyConfig)

    if not check_bank_reachable(tenant):
        parser.error(
            f"Synthetic bank not reachable at {tenant.entry_url}. Start it first with "
            "'python -m automation.cli seed' and 'python -m automation.cli serve'."
        )

    if not args.skip_seed:
        seed_bank()

    requested_artifacts = [a.strip() for a in args.artifacts.split(",") if a.strip()]
    members = [m.strip() for m in args.members.split(",") if m.strip()]
    products = [p.strip() for p in args.products.split(",") if p.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    if not (requested_artifacts and members and products and scenarios):
        parser.error("--artifacts, --members, --products and --scenarios must be non-empty")

    capabilities = {}
    artifact_reports = {}
    for artifact_path in requested_artifacts:
        capability, info = evaluate_artifact(artifact_path, tenant, policy)
        artifact_reports[artifact_path] = info
        if capability is not None:
            capabilities[artifact_path] = capability

    member_slot = {member: f"M{index + 1}" for index, member in enumerate(members)}
    combo_template = list(itertools.product(requested_artifacts, members, products, scenarios))
    cases = list(itertools.islice(itertools.cycle(combo_template), args.runs))

    records = []
    evidence_root.mkdir(parents=True, exist_ok=False)
    with (evidence_root / "iterations.jsonl").open("x") as journal:
        def record_attempt(record):
            records.append(record)
            journal.write(json.dumps(record) + "\n")
            journal.flush()
            print(
                f"{record['iteration']}/{args.runs} {record['category']} "
                f"{record['actual_code']} matches={record['matches_expectation']} "
                f"outputs_verified={record['outputs_verified_in_memory']}",
                flush=True,
            )

        for iteration, (artifact_path, member_id, product_name, scenario) in enumerate(cases, 1):
            print(f"Starting {iteration}/{args.runs}", flush=True)
            expected_status, expected_code = expected_outcome(member_id, product_name, scenario)
            base = {
                "iteration": iteration,
                "artifact": artifact_path,
                "provenance_label": artifact_reports[artifact_path]["label"],
                "member_slot": member_slot[member_id],
                "product": product_name,
                "scenario": scenario,
                "expected_status": expected_status,
                "expected_code": expected_code,
            }
            if artifact_path not in capabilities:
                record_attempt(
                    {
                        **base,
                        "actual_status": "rejected_artifact",
                        "actual_code": artifact_reports[artifact_path]["reason"],
                        "category": "rejected_artifact",
                        "matches_expectation": False,
                        "run_id": None,
                        "elapsed_seconds": None,
                        "outputs_verified_in_memory": None,
                    }
                )
                continue
            result, elapsed = await run_one(
                capabilities[artifact_path],
                member_id,
                product_name,
                scenario,
                tenant,
                policy,
                evidence_root,
            )
            category = bucket_for(result.status)
            matches = (result.status, result.code) == (expected_status, expected_code)
            if category == "extraction_success":
                verified = verify_outputs(
                    capabilities[artifact_path], member_id, product_name, result
                )
            elif result.outputs is not None:
                # A non-success result that still carries outputs is incorrect.
                verified = False
            else:
                verified = None
            record_attempt(
                {
                    **base,
                    "actual_status": result.status,
                    "actual_code": result.code,
                    "category": category,
                    "matches_expectation": matches,
                    "run_id": result.run_id,
                    "elapsed_seconds": elapsed,
                    "outputs_verified_in_memory": verified,
                }
            )

    counts = {}
    for record in records:
        counts[record["category"]] = counts.get(record["category"], 0) + 1
    required = [(a, member_slot[m], p, s) for a, m, p, s in combo_template]
    verdict = assess(records, artifact_reports, args.runs, required)
    elapsed_values = [r["elapsed_seconds"] for r in records if r["elapsed_seconds"] is not None]

    summary = {
        "tool": "tools/repeatability_matrix.py",
        "source_revision": source_revision,
        "source_dirty": source_dirty,
        "evidence_directory": str(evidence_root),
        "requested_combinations": len(set(required)),
        "missing_combinations": verdict["missing_combinations"],
        "model_access": "disabled (automation.provider import is blocked in-process)",
        "requested_runs": args.runs,
        "recorded_attempts": len(records),
        "artifacts": [artifact_reports[a] for a in requested_artifacts],
        "category_counts": counts,
        "unexpected_mismatch_iterations": verdict["unexpected_mismatch_iterations"],
        "unverified_output_iterations": verdict["unverified_output_iterations"],
        "rejected_required_artifacts": verdict["rejected_required_artifacts"],
        "uncovered_artifacts": verdict["uncovered_artifacts"],
        "ok": verdict["ok"],
        "elapsed_seconds": (
            {
                "min": min(elapsed_values),
                "max": max(elapsed_values),
                "median": statistics.median(elapsed_values),
            }
            if elapsed_values
            else None
        ),
        "iterations": records,
    }
    with destination.open("x") as report:
        report.write(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                "out": str(destination),
                "recorded_attempts": summary["recorded_attempts"],
                "category_counts": counts,
                "unexpected_mismatch_count": len(
                    verdict["unexpected_mismatch_iterations"]
                ),
                "unverified_output_count": len(
                    verdict["unverified_output_iterations"]
                ),
                "rejected_required_artifacts": verdict[
                    "rejected_required_artifacts"
                ],
                "uncovered_artifacts": verdict["uncovered_artifacts"],
                "missing_combination_count": len(verdict["missing_combinations"]),
                "artifacts": [
                    {"path": a["path"], "accepted": a["accepted"], "reason": a.get("reason")}
                    for a in summary["artifacts"]
                ],
                "ok": verdict["ok"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if verdict["ok"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
