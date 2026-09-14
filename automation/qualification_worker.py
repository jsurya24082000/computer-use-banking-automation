"""Private qualification subprocess entry point.

This is deliberately separate from the normal CLI replay command. It is used
only by the bounded qualification runner and never weakens ordinary replay.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from .models import Capability, Inputs, RuntimeConfig, Tenant
from .policy import PolicyConfig
from .runner import replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--tenant", default="config/tenant.json")
    parser.add_argument("--policy", default="config/policy.json")
    args = parser.parse_args()
    user = os.getenv("BANK_STAFF_USER")
    password = os.getenv("BANK_STAFF_PASSWORD")
    if not user or not password:
        print(json.dumps({"status": "failure", "code": "MISSING_STAFF_ENV"}))
        raise SystemExit(2)
    capability = Capability.model_validate_json(Path(args.artifact).read_text())
    tenant = Tenant.model_validate_json(Path(args.tenant).read_text())
    policy = PolicyConfig.model_validate_json(Path(args.policy).read_text())
    inputs = Inputs(
        member_id=args.member,
        product_name=args.product,
        staff_username=user,
        staff_password=password,
    )
    result = asyncio.run(
        replay(
            capability,
            inputs,
            tenant,
            RuntimeConfig(evidence_dir=args.evidence_dir),
            policy,
        )
    )
    print(result.model_dump_json())
    raise SystemExit(0 if result.status in ("success", "business_outcome") else 2)


if __name__ == "__main__":
    main()
