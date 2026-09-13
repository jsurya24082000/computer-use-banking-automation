"""Run real tests; persist only counts, never test inputs/captures or full traces."""

import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


def main():
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"], check=False
        )
        if not report.exists():
            raise SystemExit(completed.returncode or 1)
        suites = ET.parse(report).getroot()
        counts = {
            key: sum(int(s.attrib.get(key, 0)) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        summary = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "exit_code": completed.returncode,
            "counts": counts,
            "duration_seconds": sum(float(s.attrib.get("time", 0)) for s in suites),
            "browser": "Playwright Chromium",
            "human_test_note": "Human takeover tests use a simulated operator; no real human demo is claimed.",
            "llm_test_note": "Discovery tests use a fake provider; no genuine LLM demo is claimed.",
        }
        Path("evidence").mkdir(exist_ok=True)
        Path("evidence/test-summary.json").write_text(json.dumps(summary, indent=2))
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
