"""Real UI executions with a SIMULATED provider. Never genuine LLM evidence.

This is a developer/test harness: it can configure scenarios separately from the
automation engine. Start the bank first, with the same scenario-file environment.
"""

import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.discovery import discover
from automation.evidence import utcnow
from automation.models import Inputs, RuntimeConfig, Tenant
from automation.policy import PolicyConfig
from automation.provider import FakeProvider
from automation.runner import replay
from banking_app.app import set_scenario
from tests.artifacts import executor_artifact


async def main():
    root = Path("evidence")
    root.mkdir(exist_ok=True)
    (root / "executor-test-capability.json").write_text(
        executor_artifact().model_dump_json(indent=2)
    )
    inputs = Inputs(
        member_id="10001",
        product_name="Primary Savings",
        staff_username="teller",
        staff_password="DemoBank!2026",
    )
    config = RuntimeConfig(evidence_dir="evidence/offline")
    tenant = Tenant.model_validate_json(Path("config/tenant.json").read_text())
    policy = PolicyConfig.model_validate_json(Path("config/policy.json").read_text())
    set_scenario("normal")
    provider = FakeProvider(
        json.loads(Path("tests/fixtures/fake_decisions.json").read_text())
    )
    result, artifact = await discover(
        "Read the requested active account balances",
        inputs,
        provider,
        tenant,
        config,
        policy,
    )
    manifest = {
        "recorded_at": utcnow(),
        "synthetic_data_only": True,
        "provider_evidence": "SIMULATED; no genuine LLM discovery recorded",
        "runs": [],
    }

    def record(label, result):
        manifest["runs"].append(
            {
                "label": label,
                "run_id": result.run_id,
                "status": result.status,
                "code": result.code,
                "events": f"offline/{result.run_id}/events.jsonl",
            }
        )

    record("simulated_discovery_real_browser", result)
    if not artifact:
        raise RuntimeError("Offline discovery failed; no success evidence fabricated")
    # Different invocation, same compiled artifact, no provider passed or imported by replay.
    inputs.member_id = "10002"
    result = await replay(artifact, inputs, tenant, config, policy)
    assert result.outputs and result.outputs.available_balance == "9000.00", result.code
    record("parameterized_replay_different_member_no_model", result)
    inputs.member_id = "99999"
    result = await replay(artifact, inputs, tenant, config, policy)
    assert result.code == "MEMBER_NOT_FOUND", result.code
    record("business_outcome", result)
    inputs.member_id = "10001"
    set_scenario("fail_once")
    result = await replay(artifact, inputs, tenant, config, policy)
    assert result.status == "success", result.code
    record("recoverable_read_failure", result)
    set_scenario("session_expiry")
    result = await replay(artifact, inputs, tenant, config, policy)
    assert result.code == "OPERATOR_UNAVAILABLE", result.code
    record("intervention_request_only_no_human", result)
    set_scenario("normal")
    manifest["incomplete"] = [
        "Genuine model-driven discovery and its artifact",
        "Replay of a genuinely discovered artifact",
        "Real human takeover and resume",
    ]
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
