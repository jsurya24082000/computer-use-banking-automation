"""Measure bounded, model-free replays of the genuine discovered artifact."""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.models import Capability

EXPECTED = {
    "10001": ("4250.75", "4000.75", "250.00"),
    "10002": ("9123.45", "9000.00", "123.45"),
}
BLOCK_PROVIDER = (
    "import builtins,runpy,sys\n"
    "real_import=builtins.__import__\n"
    "def guarded(name,*args,**kwargs):\n"
    "    if name == 'automation.provider' or name.startswith('automation.provider.'):\n"
    "        raise RuntimeError('model provider import attempted during repeatability')\n"
    "    return real_import(name,*args,**kwargs)\n"
    "builtins.__import__=guarded\n"
    "sys.argv=['automation.cli']+sys.argv[1:]\n"
    "runpy.run_module('automation.cli',run_name='__main__')\n"
)


def parse_result(stdout):
    try:
        value = json.loads(stdout.strip())
        if isinstance(value, dict) and "status" in value and "code" in value:
            return value
    except json.JSONDecodeError:
        pass
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "status" in value and "code" in value:
            return value
    return None


def command(env, *args):
    return subprocess.run(
        [sys.executable, "-c", BLOCK_PROVIDER, *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run model-free replays of a genuine discovered artifact."
    )
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", default="evidence/repeatability-final.json")
    parser.add_argument("--artifact", default="artifacts/read-account-balances.json")
    parser.add_argument("--members", default="10001,10002")
    parser.add_argument("--product", default="Primary Savings")
    args = parser.parse_args()
    if args.runs != 10:
        parser.error("--runs must be 10 for the documented sample")
    members = [member.strip() for member in args.members.split(",")]
    if len(members) != 2 or any(member not in EXPECTED for member in members):
        parser.error("--members must contain the two documented normal members")

    capability = Capability.model_validate_json(Path(args.artifact).read_text())
    if capability.provenance.kind != "llm_discovery":
        parser.error("artifact provenance must be llm_discovery")

    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env["BANK_STAFF_USER"] = "teller"
    env["BANK_STAFF_PASSWORD"] = "DemoBank!2026"
    reset = command(env, "seed")
    if reset.returncode:
        raise RuntimeError("synthetic bank reset failed")

    records = []
    with tempfile.TemporaryDirectory(prefix="repeatability-") as evidence_dir:
        for iteration in range(args.runs):
            member = members[iteration % 2]
            started = time.monotonic()
            result_process = command(
                env,
                "replay",
                "--artifact",
                args.artifact,
                "--member",
                member,
                "--product",
                args.product,
                "--evidence-dir",
                evidence_dir,
            )
            elapsed = round(time.monotonic() - started, 3)
            result = parse_result(result_process.stdout)
            expected = EXPECTED[member]
            verified = bool(
                result
                and result_process.returncode == 0
                and result.get("status") == "success"
                and result.get("code") == "SUCCESS"
                and result.get("outputs")
                and (
                    result["outputs"]["current_balance"],
                    result["outputs"]["available_balance"],
                    result["outputs"]["active_holds"],
                )
                == expected
            )
            records.append(
                {
                    "iteration": iteration + 1,
                    "member_slot": "A" if iteration % 2 == 0 else "B",
                    "run_id": result.get("run_id") if result else None,
                    "status": "success" if verified else "failure",
                    "elapsed_seconds": elapsed,
                    "outputs_verified_in_memory": verified,
                }
            )

    elapsed = [record["elapsed_seconds"] for record in records]
    summary = {
        "artifact": args.artifact,
        "model_access": "disabled",
        "iterations": records,
        "success_count": sum(record["status"] == "success" for record in records),
        "failure_count": sum(record["status"] == "failure" for record in records),
        "elapsed_seconds": {
            "min": min(elapsed),
            "max": max(elapsed),
            "median": statistics.median(elapsed),
        },
    }
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({
        "out": str(destination),
        "success_count": summary["success_count"],
        "failure_count": summary["failure_count"],
        "elapsed_seconds": summary["elapsed_seconds"],
    }))
    raise SystemExit(0 if summary["failure_count"] == 0 else 1)


if __name__ == "__main__":
    main()
