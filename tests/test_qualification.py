import pytest

from automation.models import Inputs
from automation.runner import replay
from .artifacts import executor_artifact


@pytest.mark.asyncio
async def test_draft_artifact_is_rejected_before_browser_work(bank):
    artifact = executor_artifact()
    artifact.lifecycle = "draft"
    result = await replay(
        artifact,
        Inputs(
            member_id="10001",
            product_name="Primary Savings",
            staff_username="teller",
            staff_password="DemoBank!2026",
        ),
        bank["tenant"],
        bank["config"],
        bank["policy"],
    )
    assert result.code == "ARTIFACT_NOT_APPROVED"
