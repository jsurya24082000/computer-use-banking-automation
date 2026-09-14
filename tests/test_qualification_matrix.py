from automation.models import (
    BalanceOutputs,
    RecentTransaction,
    Result,
    TransactionsOutputs,
)
from automation.qualification_matrix import (
    BALANCE_CASES,
    TRANSACTION_CASES,
    validate_balance_result,
    validate_transaction_result,
)


def test_balance_matrix_checks_identity_and_semantic_fields():
    case = BALANCE_CASES[0]
    result = Result(
        status="success",
        code="SUCCESS",
        run_id="abcdefabcdef",
        outputs=BalanceOutputs(
            member_id="10001",
            product_name="Primary Savings",
            account_status="Active",
            currency="USD",
            current_balance="4250.75",
            available_balance="4000.75",
            active_holds="250.00",
            as_of="2026-09-13T12:00:00Z",
        ),
    )
    assert validate_balance_result(result, case)
    result.outputs.member_id = "10002"
    assert not validate_balance_result(result, case)


def test_transaction_matrix_checks_order_count_dates_and_amounts():
    case = TRANSACTION_CASES[0]
    result = Result(
        status="success",
        code="SUCCESS",
        run_id="abcdefabcdef",
        outputs=TransactionsOutputs(
            member_id="10001",
            product_name="Primary Savings",
            account_status="Active",
            transactions=[
                RecentTransaction(
                    posted_at="2026-09-12",
                    description="Synthetic payroll credit",
                    amount="150.00",
                    ledger_balance="4250.75",
                ),
                RecentTransaction(
                    posted_at="2026-09-10",
                    description="Opening ledger balance",
                    amount="4100.75",
                    ledger_balance="4100.75",
                ),
            ],
        ),
    )
    assert validate_transaction_result(result, case)
    result.outputs.transactions.reverse()
    assert not validate_transaction_result(result, case)
