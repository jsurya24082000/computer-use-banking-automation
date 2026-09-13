"""Compile observation references into reusable typed targets; never string-replace."""

from .models import Action, AutomationError, Checkpoint, Decision


def compile_action(decision: Decision, controls: dict) -> Action:
    target = None
    if decision.action in ("fill", "select", "click"):
        if decision.control_ref not in controls:
            raise AutomationError(
                "INVALID_MODEL_RESPONSE",
                "current supported control",
                "uncompilable control reference",
            )
        target = controls[decision.control_ref].model_copy(deep=True)
    elif decision.control_ref is not None:
        raise AutomationError("INVALID_MODEL_RESPONSE")
    try:
        return Action(
            kind=decision.action,
            target=target,
            input_ref=decision.input_ref,
            checkpoint=Checkpoint(screen=decision.screen) if decision.screen else None,
            destination="entry" if decision.action == "navigate" else None,
        )
    except ValueError:
        raise AutomationError("INVALID_MODEL_RESPONSE") from None


def observed_checkpoint(screen: str):
    if screen not in (
        "sign_in",
        "member_search",
        "search_results",
        "member_overview",
        "account_details",
    ):
        raise AutomationError(
            "REVIEW_REQUIRED", "supported checkpoint", "uncompilable page state"
        )
    return Checkpoint(
        screen=screen,
        verify_member=screen in ("member_overview", "account_details"),
        verify_product=screen == "account_details",
        require_active=screen == "account_details",
        require_balances=screen == "account_details",
    )
