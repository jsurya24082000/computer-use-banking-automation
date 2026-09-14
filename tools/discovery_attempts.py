"""Run independent discovery attempts without printing provider payloads."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--provider", choices=["openai", "fake"], default="openai")
    parser.add_argument("--member", default="10001")
    parser.add_argument("--product", default="Primary Savings")
    parser.add_argument("--goal", default=None)
    parser.add_argument("--out", default="evidence/discovery-attempts.json")
    args = parser.parse_args()
    if args.runs < 3:
        parser.error("--runs must be at least 3")
    goal = args.goal or (
        "Find the member identified by input_ref member_id and return the current "
        "and available balances for the active account identified by input_ref "
        "product_name."
    )
    records = []
    for index in range(args.runs):
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
                "--artifact-out",
                f"evidence/discovery-attempt-{index + 1}.json",
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
                "attempt": index + 1,
                "status": "success" if process.returncode == 0 else "failure",
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "attempts": records,
                "provider": args.provider,
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
