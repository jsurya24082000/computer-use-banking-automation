"""End-to-end coverage for the read_recent_transactions workflow.

Covers discovery -> compilation -> qualification -> replay with different
inputs, plus zero, fewer than five, more than five, malformed and incorrectly
ordered transaction tables. All runs use the scripted fake provider or a
hand-authored artifact; nothing here is genuine LLM discovery evidence.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from automation.discovery import discover
from automation.models import (
    AutomationError,
    Capability,
    FINAL_TRANSACTIONS,
    OUTPUT_CONTRACT,
    RecentTransaction,
    TRANSACTIONS_OUTPUT_CONTRACT,
    TransactionsOutputs,
)
from automation.provider import FakeProvider
from automation.qualification import approval_matches, qualify
from automation.runner import replay
from banking_app.db import connect
from .artifacts import executor_artifact, transactions_artifact


def scripted():
    return FakeProvider(
        json.loads(Path("tests/fixtures/fake_decisions.json").read_text())
    )


def add_member_account(db_path, member_id, transactions, cents=50000):
    """Test-harness DB access only; the automation never reads the database."""
    with connect(db_path) as con:
        con.execute(
            "INSERT INTO members VALUES (?,?,?,?)",
            (member_id, "Zxqw Qvbnm", "Maple Harbor", "Active"),
        )
        account_id = con.execute(
            "INSERT INTO accounts(member_id,product,last_four,status,currency,"
            "current_cents,restricted,as_of) VALUES (?,?,?,?,?,?,?,?)",
            (
                member_id,
                "Primary Savings",
                "9999",
                "Active",
                "USD",
                cents,
                0,
                "2026-09-13T12:00:00Z",
            ),
        ).lastrowid
        for posted, description, amount, balance in transactions:
            con.execute(
                "INSERT INTO transactions(account_id,posted_at,description,"
                "amount_cents,balance_cents) VALUES (?,?,?,?,?)",
                (account_id, posted, description, amount, balance),
            )


def remove_member(db_path, member_id):
    with connect(db_path) as con:
        con.execute(
            "DELETE FROM transactions WHERE account_id IN "
            "(SELECT id FROM accounts WHERE member_id=?)",
            (member_id,),
        )
        con.execute("DELETE FROM accounts WHERE member_id=?", (member_id,))
        con.execute("DELETE FROM members WHERE id=?", (member_id,))


async def test_unsupported_workflow_is_rejected_before_browser(inputs):
    with pytest.raises(AutomationError, match="UNSUPPORTED_WORKFLOW"):
        await discover(
            "test",
            inputs,
            FakeProvider([]),
            workflow="read_everything",
        )


def test_transactions_capability_rejects_balance_contract():
    data = transactions_artifact().model_dump()
    data["outputs"] = [o.model_dump() for o in OUTPUT_CONTRACT]
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_balance_capability_rejects_transactions_contract():
    data = executor_artifact().model_dump()
    data["outputs"] = [o.model_dump() for o in TRANSACTIONS_OUTPUT_CONTRACT]
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_transactions_checkpoint_cannot_be_weakened():
    data = transactions_artifact().model_dump()
    data["final_checkpoint"]["require_transactions"] = False
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_qualification_rejects_balance_outputs_for_transactions(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(transactions_artifact().model_dump_json())

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "status": "success",
                "code": "SUCCESS",
                "run_id": "abcdefabcdef",
                "outputs": {
                    "member_id": "10001",
                    "product_name": "Primary Savings",
                    "account_status": "Active",
                    "currency": "USD",
                    "current_balance": "4250.75",
                    "available_balance": "4000.75",
                    "active_holds": "250.00",
                    "as_of": "2026-09-13T12:00:00Z",
                },
            }
        )

    monkeypatch.setattr(
        "automation.qualification.subprocess.run", lambda *a, **k: Completed()
    )
    record = qualify(artifact_path)
    assert record["status"] == "rejected"
    assert record["results"][0]["run_recorded"] is True


def test_qualification_rejects_wrong_transaction_values(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(transactions_artifact().model_dump_json())

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "status": "success",
                "code": "SUCCESS",
                "run_id": "abcdefabcdef",
                "outputs": TransactionsOutputs(
                    member_id="10001",
                    product_name="Primary Savings",
                    account_status="Active",
                    transactions=[
                        RecentTransaction(
                            posted_at="2026-09-12",
                            description="Synthetic payroll credit",
                            amount="1.00",
                            ledger_balance="1.00",
                        )
                    ],
                ).model_dump(mode="json"),
            }
        )

    monkeypatch.setattr(
        "automation.qualification.subprocess.run", lambda *a, **k: Completed()
    )
    record = qualify(artifact_path)
    assert record["status"] == "rejected"


def _forbidden_worker():
    real_run = subprocess.run

    def forbidden(cmd, *args, **kwargs):
        if "automation.qualification_worker" in cmd:
            raise AssertionError("qualification worker must not run")
        return real_run(cmd, *args, **kwargs)

    return forbidden


@pytest.mark.parametrize(
    "members",
    [(), ("10001",), ("10001", "10001"), ("  ", "10001")],
)
def test_qualification_rejects_empty_and_duplicate_inputs(
    tmp_path, monkeypatch, members
):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(transactions_artifact().model_dump_json())
    monkeypatch.setattr(
        "automation.qualification.subprocess.run", _forbidden_worker()
    )
    record = qualify(artifact_path, members=members)
    assert record["status"] == "rejected"
    assert record["suite_error"] is not None


def test_qualification_rejects_undeclared_member(tmp_path, monkeypatch):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(transactions_artifact().model_dump_json())
    monkeypatch.setattr(
        "automation.qualification.subprocess.run", _forbidden_worker()
    )
    record = qualify(artifact_path, members=("10001", "10003"))
    assert record["status"] == "rejected"
    assert record["suite_error"] == "undeclared_expectations"


def test_cli_qualify_exits_nonzero_on_rejection(tmp_path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(transactions_artifact().model_dump_json())
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "automation.cli",
            "qualify",
            "--artifact",
            str(artifact_path),
            "--members",
            "10001,10001",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert json.loads(process.stdout)["status"] == "rejected"


@pytest.mark.browser
async def test_transactions_discovery_compiles_qualifies_and_replays(
    bank, inputs, tmp_path, monkeypatch
):
    result, artifact = await discover(
        "Find the requested member and active account, then return its five "
        "most recent transactions.",
        inputs,
        scripted(),
        bank["tenant"],
        bank["config"],
        bank["policy"],
        workflow="read_recent_transactions",
    )
    assert result.status == "success", result
    assert isinstance(result.outputs, TransactionsOutputs)
    assert [t.posted_at for t in result.outputs.transactions] == [
        "2026-09-12",
        "2026-09-10",
    ]
    assert artifact.name == "read_recent_transactions"
    assert artifact.outputs == list(TRANSACTIONS_OUTPUT_CONTRACT)
    assert artifact.final_checkpoint == FINAL_TRANSACTIONS
    assert artifact.resume_checkpoint == FINAL_TRANSACTIONS
    assert artifact.lifecycle == "draft"
    serialized = artifact.model_dump_json()
    for raw in ("10001", "teller", "DemoBank!2026", "4250.75", bank["origin"]):
        assert raw not in serialized

    # Qualification runs the declared transaction suite in fresh subprocesses.
    artifact_path = tmp_path / "transactions-capability.json"
    artifact_path.write_text(artifact.model_dump_json(indent=2))
    monkeypatch.setenv("BANK_STAFF_USER", "teller")
    monkeypatch.setenv("BANK_STAFF_PASSWORD", "DemoBank!2026")
    record = qualify(
        artifact_path, tenant=bank["tenant"], policy=bank["policy"]
    )
    assert record["status"] == "approved", record
    approved = Capability.model_validate_json(artifact_path.read_text())
    assert approved.lifecycle == "approved"
    assert approval_matches(
        artifact_path, approved, bank["tenant"], bank["policy"]
    )

    # Replay the approved artifact against a different member, model-free.
    inputs.member_id = "10002"
    replayed = await replay(
        approved, inputs, bank["tenant"], bank["config"], bank["policy"]
    )
    assert replayed.status == "success", replayed
    assert isinstance(replayed.outputs, TransactionsOutputs)
    assert replayed.outputs.member_id == "10002"
    assert [(t.posted_at, t.amount) for t in replayed.outputs.transactions] == [
        ("2026-09-12", "150.00"),
        ("2026-09-10", "8973.45"),
    ]


@pytest.mark.browser
async def test_replay_zero_transactions_succeeds_with_empty_list(bank, inputs):
    add_member_account(bank["db"], "10011", [])
    try:
        inputs.member_id = "10011"
        result = await replay(
            transactions_artifact(),
            inputs,
            bank["tenant"],
            bank["config"],
            bank["policy"],
        )
        assert result.status == "success", result
        assert result.outputs.transactions == []
    finally:
        remove_member(bank["db"], "10011")


@pytest.mark.browser
async def test_replay_fewer_than_five_transactions(bank, inputs):
    # Rows are inserted oldest-first; the app displays newest id first.
    add_member_account(
        bank["db"],
        "10012",
        [
            ("2026-09-10", "Opening ledger balance", 35000, 35000),
            ("2026-09-12", "Synthetic payroll credit", 15000, 50000),
        ],
    )
    try:
        inputs.member_id = "10012"
        result = await replay(
            transactions_artifact(),
            inputs,
            bank["tenant"],
            bank["config"],
            bank["policy"],
        )
        assert result.status == "success", result
        assert len(result.outputs.transactions) == 2
    finally:
        remove_member(bank["db"], "10012")


@pytest.mark.browser
async def test_replay_more_than_five_transactions_fails(bank, inputs):
    add_member_account(
        bank["db"],
        "10013",
        [
            ("2026-09-%02d" % day, "Synthetic entry", 1000, 50000)
            for day in range(7, 13)
        ],
    )
    try:
        inputs.member_id = "10013"
        result = await replay(
            transactions_artifact(),
            inputs,
            bank["tenant"],
            bank["config"],
            bank["policy"],
        )
        assert result.status == "failure", result
        assert result.code == "TOO_MANY_TRANSACTIONS"
    finally:
        remove_member(bank["db"], "10013")


@pytest.mark.browser
async def test_replay_malformed_transaction_date_fails(bank, inputs):
    add_member_account(
        bank["db"],
        "10014",
        [("09/12/2026", "Synthetic entry", 1000, 50000)],
    )
    try:
        inputs.member_id = "10014"
        result = await replay(
            transactions_artifact(),
            inputs,
            bank["tenant"],
            bank["config"],
            bank["policy"],
        )
        assert result.status == "failure", result
        assert result.code == "INVALID_TRANSACTION_DATE"
    finally:
        remove_member(bank["db"], "10014")


@pytest.mark.browser
async def test_replay_incorrectly_ordered_transactions_fails(bank, inputs):
    # The app displays newest table row first (id DESC); inserting an older
    # posting date last makes the displayed order oldest-first.
    add_member_account(
        bank["db"],
        "10015",
        [
            ("2026-09-12", "Synthetic payroll credit", 15000, 50000),
            ("2026-09-05", "Out of order entry", 35000, 35000),
        ],
    )
    try:
        inputs.member_id = "10015"
        result = await replay(
            transactions_artifact(),
            inputs,
            bank["tenant"],
            bank["config"],
            bank["policy"],
        )
        assert result.status == "failure", result
        assert result.code == "TRANSACTIONS_NOT_NEWEST_FIRST"
    finally:
        remove_member(bank["db"], "10015")
