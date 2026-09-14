"""Bounded artifact qualification and sanitized approval records."""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .evidence import capability_sha256
from .models import Capability

SUITE_VERSION = "qualification-v1"


def digest_json(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def approval_path(artifact_path):
    return Path(f"{artifact_path}.approval.json")


def approval_matches(artifact_path, capability):
    path = approval_path(artifact_path)
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    approved = capability.model_copy(update={"lifecycle": "approved"})
    return (
        record.get("status") == "approved"
        and record.get("artifact_sha256") == capability_sha256(approved)
        and record.get("schema_version") == capability.schema_version
        and record.get("capability_version") == capability.version
        and record.get("compatibility") == capability.compatibility.model_dump(mode="json")
    )


def qualify(artifact_path, members=("10001", "10002"), product="Primary Savings"):
    path = Path(artifact_path)
    capability = Capability.model_validate_json(path.read_text())
    results = []
    with tempfile.TemporaryDirectory(prefix="qualification-") as tmp:
        candidate = Capability.model_validate(
            {**capability.model_dump(), "lifecycle": "approved"}
        )
        candidate_path = Path(tmp) / "candidate.json"
        candidate_path.write_text(candidate.model_dump_json(indent=2))
        for index, member in enumerate(members, 1):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "automation.cli",
                    "replay",
                    "--artifact",
                    str(candidate_path),
                    "--member",
                    member,
                    "--product",
                    product,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            results.append(
                {
                    "slot": index,
                    "status": "success" if result.returncode == 0 else "failure",
                    "code": "SUCCESS"
                    if result.returncode == 0
                    else "QUALIFICATION_FAILED",
                }
            )
    approved = all(item["status"] == "success" for item in results)
    record = {
        "qualification_suite": SUITE_VERSION,
        "status": "approved" if approved else "rejected",
        "artifact_sha256": capability_sha256(candidate),
        "schema_version": capability.schema_version,
        "capability_version": capability.version,
        "compatibility": capability.compatibility.model_dump(mode="json"),
        "policy_digest": digest_json("read-only-v1"),
        "tenant_digest": digest_json("1.0"),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "provenance": capability.provenance.model_dump(mode="json"),
        "results": results,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    approval_path(path).write_text(json.dumps(record, indent=2) + "\n")
    if approved:
        path.write_text(candidate.model_dump_json(indent=2) + "\n")
    return record
