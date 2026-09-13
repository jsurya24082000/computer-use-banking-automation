import json
import pytest
from pydantic import ValidationError
from automation.compiler import compile_action
from automation.evidence import Sanitizer, Evidence
from automation.models import (
    Action,
    Binding,
    Capability,
    Decision,
    Ownership,
    AutomationError,
)
from automation.policy import Policy, PolicyConfig
from automation.surface import label_target
from .artifacts import executor_artifact


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "execute_python", "code": "print('unsafe')"},
        {
            "kind": "fill",
            "target": label_target("Password").model_dump(),
            "value": "literal-secret",
        },
        {"kind": "navigate", "destination": "https://outside.example"},
        {"kind": "finish", "input_ref": "staff_password"},
        {
            "kind": "fill",
            "target": label_target("Password").model_dump(),
            "input_ref": "unlisted",
        },
    ],
)
def test_invalid_actions(data):
    with pytest.raises(ValidationError):
        Action.model_validate(data)


def test_binding_is_explicit_not_string_substitution(inputs):
    assert Binding(input_ref="member_id").resolve(inputs) == "10001"
    assert Binding(literal="prefix {member_id}").resolve(inputs) == "prefix {member_id}"
    assert Binding(input_ref="staff_password").resolve(inputs) == "DemoBank!2026"
    with pytest.raises(ValidationError):
        Binding(literal="x", input_ref="member_id")


def test_artifact_rejects_weakened_checkpoint():
    data = executor_artifact().model_dump()
    data["final_checkpoint"]["require_balances"] = False
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_artifact_duplicate_ids_and_versions():
    data = executor_artifact().model_dump()
    data["steps"][1]["id"] = data["steps"][0]["id"]
    with pytest.raises(ValidationError):
        Capability.model_validate(data)
    data = executor_artifact().model_dump()
    data["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        Capability.model_validate(data)


def test_unknown_model_target_stops():
    decision = Decision(
        action="click",
        control_ref="invented",
        input_ref=None,
        screen=None,
        rationale="test",
    )
    with pytest.raises(AutomationError, match="INVALID_MODEL_RESPONSE"):
        compile_action(decision, {})


@pytest.mark.parametrize(
    "url,method",
    [
        ("https://outside.example/", "GET"),
        ("http://127.0.0.1:8000.evil.example/", "GET"),
        ("http://user:pass@127.0.0.1:8000/", "GET"),
        ("file:///etc/passwd", "GET"),
        ("javascript:alert(1)", "GET"),
        ("http://127.0.0.1:8000/ui/transfer", "POST"),
        ("http://127.0.0.1:8000/ui/accounts/1", "DELETE"),
    ],
)
def test_policy_blocks_destination(url, method):
    with pytest.raises(AutomationError):
        Policy(PolicyConfig()).authorize_url(url, method)


def test_tenant_policy_cannot_enable_writes():
    policy = Policy(PolicyConfig(allowed_post_routes=[".*"]))
    with pytest.raises(AutomationError):
        policy.authorize_url("http://127.0.0.1:8000/ui/accounts/1", "POST")


@pytest.mark.parametrize(
    "owner", [Ownership.PAUSED, Ownership.HUMAN, Ownership.COMPLETED]
)
def test_no_actions_without_automation_ownership(owner):
    with pytest.raises(AutomationError, match="CONTROL_NOT_OWNED"):
        Policy(PolicyConfig()).authorize_action(Action(kind="finish"), owner)


def test_sensitive_values_are_redacted(inputs, tmp_path):
    s = Sanitizer(inputs)
    raw = {
        "password": "DemoBank!2026",
        "nested": {"target": {"name": "f2"}, "value": "DemoBank!2026"},
        "message": "Member 10001 teller account 123456789 SSN 123-45-6789 $4,250.75",
        "outputs": {"current_balance": "4250.75"},
        "token": "synthetic-token",
    }
    serialized = json.dumps(s.clean(raw))
    for value in (
        "DemoBank!2026",
        "10001",
        "teller",
        "123456789",
        "123-45-6789",
        "4,250.75",
        "4250.75",
        "synthetic-token",
    ):
        assert value not in serialized
    e = Evidence(str(tmp_path), "abcdefabcdef", inputs)
    with pytest.raises(ValueError):
        e.event("unsafe", outputs={"balance": "4250.75"})
    e.snapshot({"screen": "account_details", "password": "bad", "html": "raw DOM"})
    assert "bad" not in (e.directory / "failure-snapshot.json").read_text()


def test_only_placeholders_in_hand_artifact():
    serialized = executor_artifact().model_dump_json()
    assert "DemoBank!2026" not in serialized
    assert "10001" not in serialized
