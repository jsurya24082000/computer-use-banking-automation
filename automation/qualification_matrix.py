"""Declared, independent qualification expectations for synthetic scenarios."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class QualificationCase:
    name: str
    member_id: str
    product_name: str
    expected_status: str
    expected_code: str


BALANCE_CASES = (
    QualificationCase("member-10001", "10001", "Primary Savings", "success", "SUCCESS"),
    QualificationCase("member-10002", "10002", "Primary Savings", "success", "SUCCESS"),
    QualificationCase("missing-member", "99999", "Primary Savings", "business_outcome", "MEMBER_NOT_FOUND"),
    QualificationCase("closed-product", "10001", "Holiday Savings", "business_outcome", "NO_ELIGIBLE_ACCOUNT"),
)

TRANSACTION_CASES = (
    QualificationCase("transactions-10001", "10001", "Primary Savings", "success", "SUCCESS"),
    QualificationCase("transactions-10002", "10002", "Primary Savings", "success", "SUCCESS"),
    QualificationCase("transactions-missing-member", "99999", "Primary Savings", "business_outcome", "MEMBER_NOT_FOUND"),
    QualificationCase("transactions-closed-product", "10001", "Holiday Savings", "business_outcome", "NO_ELIGIBLE_ACCOUNT"),
)

EXPECTED_BALANCES = {
    "10001": ("4250.75", "4000.75", "250.00"),
    "10002": ("9123.45", "9000.00", "123.45"),
}

EXPECTED_TRANSACTIONS = {
    "10001": (
        ("2026-09-12", "150.00", "4250.75"),
        ("2026-09-10", "4100.75", "4100.75"),
    ),
    "10002": (
        ("2026-09-12", "150.00", "9123.45"),
        ("2026-09-10", "8973.45", "8973.45"),
    ),
}


def validate_balance_result(result, case: QualificationCase) -> bool:
    if result.status != case.expected_status or result.code != case.expected_code:
        return False
    if result.status != "success":
        return True
    output = result.outputs
    expected = EXPECTED_BALANCES.get(case.member_id)
    return bool(
        output
        and output.member_id == case.member_id
        and output.product_name == case.product_name
        and output.account_status == "Active"
        and expected
        and (
            output.current_balance,
            output.available_balance,
            output.active_holds,
        )
        == expected
    )


def validate_transaction_result(result, case: QualificationCase) -> bool:
    if result.status != case.expected_status or result.code != case.expected_code:
        return False
    if result.status != "success":
        return True
    output = result.outputs
    expected = EXPECTED_TRANSACTIONS.get(case.member_id)
    if not output or output.member_id != case.member_id:
        return False
    if output.product_name != case.product_name or output.account_status != "Active":
        return False
    if expected is None or len(output.transactions) != len(expected):
        return False
    observed = tuple(
        (row.posted_at, row.amount, row.ledger_balance)
        for row in output.transactions
    )
    if observed != expected:
        return False
    return all(
        date.fromisoformat(row.posted_at)
        and Decimal(row.amount)
        and Decimal(row.ledger_balance)
        for row in output.transactions
    )
