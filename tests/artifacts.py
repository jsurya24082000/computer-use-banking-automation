"""HAND-AUTHORED EXECUTOR TEST ONLY. Never evidence of LLM discovery."""

from automation.evidence import utcnow
from automation.models import (
    Action,
    Binding,
    Capability,
    CellMatch,
    Checkpoint,
    Provenance,
    Step,
    FINAL,
    FINAL_TRANSACTIONS,
    TRANSACTIONS_DESCRIPTION,
    TRANSACTIONS_OUTPUT_CONTRACT,
)
from automation.surface import label_target, role_target


def _executor_steps(final: Checkpoint):
    actions = [
        Action(
            kind="fill",
            target=label_target("Staff username"),
            input_ref="staff_username",
        ),
        Action(
            kind="fill", target=label_target("Password"), input_ref="staff_password"
        ),
        Action(kind="click", target=role_target("Sign in")),
        Action(kind="fill", target=label_target("Member ID"), input_ref="member_id"),
        Action(kind="click", target=role_target("Search")),
        Action(
            kind="click",
            target=role_target(
                "View",
                "link",
                "Member search results",
                [CellMatch(column="Member ID", value=Binding(input_ref="member_id"))],
            ),
        ),
        Action(
            kind="click",
            target=role_target(
                "View",
                "link",
                "Member accounts",
                [
                    CellMatch(
                        column="Product", value=Binding(input_ref="product_name")
                    ),
                    CellMatch(column="Status", value=Binding(literal="Active")),
                ],
            ),
        ),
        Action(kind="extract"),
        Action(kind="finish"),
    ]
    steps = [Step(id=f"s{i:03}", action=a) for i, a in enumerate(actions, 1)]
    steps[2].after = Checkpoint(screen="member_search")
    steps[4].after = Checkpoint(screen="search_results")
    steps[5].after = Checkpoint(screen="member_overview", verify_member=True)
    steps[6].after = final.model_copy()
    return steps


def _provenance():
    return Provenance(
        kind="hand_authored_executor_test",
        run_id="000000000000",
        provider="none",
        created_at=utcnow(),
    )


def executor_artifact():
    return Capability(steps=_executor_steps(FINAL), provenance=_provenance())


def transactions_artifact():
    return Capability(
        name="read_recent_transactions",
        description=TRANSACTIONS_DESCRIPTION,
        outputs=list(TRANSACTIONS_OUTPUT_CONTRACT),
        final_checkpoint=FINAL_TRANSACTIONS.model_copy(),
        resume_checkpoint=FINAL_TRANSACTIONS.model_copy(),
        steps=_executor_steps(FINAL_TRANSACTIONS),
        provenance=_provenance(),
    )
