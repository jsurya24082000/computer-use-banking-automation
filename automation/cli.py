import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path

from pydantic import ValidationError
from .models import AutomationError, Capability, Inputs, RuntimeConfig, Tenant
from .policy import PolicyConfig


def read_model(path, model):
    return model.model_validate_json(Path(path).read_text()) if path else model()


def invocation(args):
    return Inputs(
        member_id=args.member,
        product_name=args.product,
        staff_username=os.getenv("BANK_STAFF_USER") or input("Demo staff username: "),
        staff_password=os.getenv("BANK_STAFF_PASSWORD")
        or getpass.getpass("Demo staff password: "),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Computer-Use Banking Automation — synthetic data only"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Reset and seed the private synthetic bank database")
    scenario = sub.add_parser(
        "scenario", help="Developer setup only; never exposed to the automation"
    )
    scenario.add_argument(
        "name",
        choices=[
            "normal",
            "member_not_found",
            "invalid_member_id",
            "no_matching_active_account",
            "permission_denied",
            "session_expiry",
            "slow_account_loading",
            "fail_once",
            "blocking_dialog",
        ],
    )
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    for command in ("discover", "replay"):
        p = sub.add_parser(command)
        p.add_argument("--member", required=True)
        p.add_argument("--product", default="Primary Savings")
        p.add_argument("--tenant", default="config/tenant.json")
        p.add_argument("--policy", default="config/policy.json")
        p.add_argument("--headed", action="store_true")
        p.add_argument("--interactive", action="store_true")
        p.add_argument("--timeout", type=float, default=120)
        p.add_argument("--evidence-dir", default="evidence/local")
        if command == "discover":
            p.add_argument(
                "--artifact-out",
                help="Optional stable path for the verified capability",
            )
            p.add_argument(
                "--workflow",
                choices=["balances", "transactions"],
                default="balances",
                help=(
                    "Which typed capability to compile: 'balances' calls "
                    "surface.balances() at finish, 'transactions' calls "
                    "surface.recent_transactions(). This selects the extraction "
                    "verb only; every step is still chosen live by the model."
                ),
            )
            p.add_argument("--goal", default=None)
            p.add_argument("--provider", choices=["openai", "fake"], default="openai")
            p.add_argument(
                "--fake-script", default="tests/fixtures/fake_decisions.json"
            )
        else:
            p.add_argument("--artifact", required=True)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--artifact", required=True)
    qualify.add_argument("--members", default="10001,10002")
    qualify.add_argument("--product", default="Primary Savings")
    qualify.add_argument("--tenant", default="config/tenant.json")
    qualify.add_argument("--policy", default="config/policy.json")
    args = parser.parse_args()
    try:
        if args.command == "seed":
            from banking_app.db import seed

            seed()
            print(
                "Synthetic database reset. Demo users: teller / supervisor. Demo password: DemoBank!2026"
            )
            return
        if args.command == "scenario":
            from banking_app.app import set_scenario

            set_scenario(args.name)
            print("Developer scenario configured for the next run.")
            return
        if args.command == "serve":
            import uvicorn

            uvicorn.run(
                "banking_app.app:app",
                host="127.0.0.1",
                port=args.port,
                access_log=False,
            )
            return
        if args.command == "qualify":
            from .qualification import qualify

            tenant = read_model(args.tenant, Tenant)
            policy = read_model(args.policy, PolicyConfig)
            record = qualify(
                args.artifact,
                tuple(args.members.split(",")),
                args.product,
                tenant,
                policy,
                args.tenant,
                args.policy,
            )
            print(json.dumps(record, indent=2))
            raise SystemExit(0 if record["status"] == "approved" else 2)
        if args.interactive and not args.headed:
            parser.error("--interactive requires --headed")
        tenant = read_model(args.tenant, Tenant)
        policy = read_model(args.policy, PolicyConfig)
        config = RuntimeConfig(
            headless=not args.headed,
            interactive=args.interactive,
            overall_timeout_seconds=args.timeout,
            evidence_dir=args.evidence_dir,
        )
        inputs = invocation(args)
        if args.command == "replay":
            from .runner import replay
            from .qualification import approval_matches

            artifact = Capability.model_validate_json(Path(args.artifact).read_text())
            if (
                artifact.provenance.kind == "llm_discovery"
                and not approval_matches(args.artifact, artifact, tenant, policy)
            ):
                raise AutomationError("MISSING_APPROVAL")
            result = asyncio.run(replay(artifact, inputs, tenant, config, policy))
        else:
            from .provider import FakeProvider, OpenAIProvider
            from .discovery import discover

            provider = (
                OpenAIProvider()
                if args.provider == "openai"
                else FakeProvider(json.loads(Path(args.fake_script).read_text()))
            )
            if provider.simulated:
                print("SIMULATED OFFLINE PROVIDER — NOT genuine LLM discovery")
            workflow = (
                "read_recent_transactions"
                if args.workflow == "transactions"
                else "read_account_balances"
            )
            goal = args.goal or (
                "Find the requested member and active account, then return its "
                "five most recent transactions."
                if workflow == "read_recent_transactions"
                else "Find the member identified by input_ref member_id and return "
                "the current and available balances for the active account "
                "identified by input_ref product_name."
            )
            result, capability = asyncio.run(
                discover(
                    goal, inputs, provider, tenant, config, policy, workflow=workflow
                )
            )
            if capability:
                if args.artifact_out:
                    dest = Path(args.artifact_out)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(capability.model_dump_json(indent=2))
                print(
                    "Capability:",
                    str(Path(args.evidence_dir) / result.run_id / "capability.json"),
                )
        # This is the declared caller result, deliberately not a diagnostic file.
        print(result.model_dump_json(indent=2))
        raise SystemExit(0 if result.status in ("success", "business_outcome") else 2)
    except (AutomationError, ValidationError, OSError) as exc:
        # Never print ValidationError bodies, which may contain invocation values.
        print(
            json.dumps(
                {
                    "status": "failure",
                    "code": exc.code
                    if isinstance(exc, AutomationError)
                    else "INVALID_CONFIGURATION_OR_FILE",
                }
            )
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
