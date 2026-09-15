"""Run independent discovery attempts without printing provider payloads."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GOALS = {
    "balances": (
        "Find the member identified by input_ref member_id and return the "
        "current and available balances for the active account identified by "
        "input_ref product_name."
    ),
    "transactions": (
        "Find the requested member and active account, then return its five "
        "most recent transactions."
    ),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--provider", choices=["openai", "fake"], default="openai")
    parser.add_argument("--member", default="10001")
    parser.add_argument("--product", default="Primary Savings")
    parser.add_argument(
        "--workflow",
        choices=["balances", "transactions"],
        default="balances",
        help="Typed workflow each attempt compiles; selects the artifact directory and default goal.",
    )
    parser.add_argument("--goal", default=None)
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help=(
            "Directory receiving attempt-N-capability.json artifacts; defaults "
            "to evidence/discovery-attempts/<workflow> so the same path is "
            "used by discovery, qualification and replay commands."
        ),
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")
    goal = args.goal or GOALS[args.workflow]
    artifact_dir = Path(
        args.artifact_dir or f"evidence/discovery-attempts/{args.workflow}"
    )
    out = args.out or f"evidence/discovery-attempts-{args.workflow}.json"
    # Attempt numbering continues past any existing files so a new run never
    # overwrites preserved historical artifacts in the same directory.
    next_attempt = 1
    if artifact_dir.exists():
        existing = [
            int(p.name.split("-")[1])
            for p in artifact_dir.glob("attempt-*-capability.json")
            if p.name.split("-")[1].isdigit()
        ]
        next_attempt = max(existing, default=0) + 1
    records = []
    for index in range(args.runs):
        attempt = next_attempt + index
        artifact = artifact_dir / f"attempt-{attempt}-capability.json"
        started = time.monotonic()
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "automation.cli",
                "discover",
                "--provider",
                args.provider,
                "--member",
                args.member,
                "--product",
                args.product,
                "--workflow",
                args.workflow,
                "--artifact-out",
                str(artifact),
                "--goal",
                goal,
            ],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        records.append(
            {
                "attempt": attempt,
                "status": "success" if process.returncode == 0 else "failure",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "artifact": str(artifact),
            }
        )
    output = Path(out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "attempts": records,
                "provider": args.provider,
                "workflow": args.workflow,
                "success_count": sum(r["status"] == "success" for r in records),
                "failure_count": sum(r["status"] == "failure" for r in records),
            },
            indent=2,
        )
        + "\n"
    )
    raise SystemExit(0 if all(r["status"] == "success" for r in records) else 1)


if __name__ == "__main__":
    main()
