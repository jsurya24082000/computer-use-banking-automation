"""Allowlisted diagnostic records, never raw UI/model payloads or returned outputs."""

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from .models import Inputs


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def capability_sha256(capability) -> str:
    """Hash the validated capability's canonical JSON, excluding no capability fields."""
    canonical = json.dumps(
        capability.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class Sanitizer:
    def __init__(self, inputs: Inputs):
        self.secrets = sorted(
            [
                inputs.resolve(n)
                for n in ("member_id", "staff_username", "staff_password")
                if inputs.resolve(n)
            ],
            key=len,
            reverse=True,
        )

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "<redacted>")
        value = re.sub(
            r"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b|\b[0-9]{4,}\b", "<redacted>", value
        )
        value = re.sub(r"\$[0-9,]+\.[0-9]{2}", "<amount>", value)
        return value[:300]

    def clean(self, obj):
        if isinstance(obj, dict):
            return {
                k: "<redacted>"
                if k.lower()
                in {
                    "password",
                    "token",
                    "cookie",
                    "authorization",
                    "value",
                    "outputs",
                    "raw",
                    "prompt",
                    "response",
                    "member_id",
                    "csrf",
                }
                else self.clean(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [self.clean(v) for v in obj]
        if isinstance(obj, str):
            return self.text(obj)
        return obj


class Evidence:
    def __init__(self, root: str, run_id: str, inputs: Inputs):
        self.directory = Path(root) / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.run_id = run_id
        self.sanitizer = Sanitizer(inputs)
        self.path = self.directory / "events.jsonl"

    def event(self, event: str, **fields):
        # Callers supply only typed/control metadata, never raw provider rationales.
        allowed = {
            "step_id",
            "action",
            "state",
            "from_state",
            "to_state",
            "code",
            "attempt",
            "provider",
            "provenance",
            "screen",
            "rationale",
            "interaction",
            "tag",
            "frame",
            "checkpoint",
            "evidence_ref",
            "status",
            "capability_sha256",
        }
        if set(fields) - allowed:
            raise ValueError("Diagnostic field not allowlisted")
        record = {
            "at": utcnow(),
            "event": event,
            "run_id": self.run_id,
            **self.sanitizer.clean(fields),
        }
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def snapshot(self, state: dict) -> str:
        # Caller supplies a structured, sanitized snapshot. No HTML/screenshots.
        allowed = {
            "screen",
            "signal",
            "control_count",
            "matching_member",
            "matching_product",
            "active",
            "balance_fields_present",
        }
        safe = {k: v for k, v in state.items() if k in allowed}
        path = self.directory / "failure-snapshot.json"
        path.write_text(json.dumps(self.sanitizer.clean(safe), indent=2))
        return str(path)

    def intervention(self, step_id: str, code: str, context: dict):
        path = self.directory / "intervention.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "capability": "read_account_balances",
                    "step_id": step_id,
                    "reason": code,
                    "context": self.sanitizer.clean(context),
                    "operator": "Claim this run in its terminal; use the existing visible browser; resume after account verification.",
                },
                indent=2,
            )
        )
        return str(path)
