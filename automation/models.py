from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


InputName = Literal["member_id", "product_name", "staff_username", "staff_password"]
ActionKind = Literal[
    "navigate", "click", "fill", "select", "extract", "check", "finish"
]
Screen = Literal[
    "sign_in", "member_search", "search_results", "member_overview", "account_details"
]


class Inputs(StrictModel):
    # Format errors are returned as business outcomes before any browser work.
    member_id: str = Field(min_length=1, max_length=40, repr=False)
    product_name: str = Field(min_length=1, max_length=80)
    staff_username: SecretStr
    staff_password: SecretStr

    def resolve(self, name: InputName) -> str:
        value = getattr(self, name)
        return value.get_secret_value() if isinstance(value, SecretStr) else value


class Binding(StrictModel):
    literal: str | None = Field(default=None, max_length=120)
    input_ref: InputName | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.literal is None) == (self.input_ref is None):
            raise ValueError("Exactly one of literal or input_ref is required")
        return self

    def resolve(self, inputs: Inputs) -> str:
        return inputs.resolve(self.input_ref) if self.input_ref else self.literal


class CellMatch(StrictModel):
    column: Literal["Member ID", "Product", "Status"]
    value: Binding


class Strategy(StrictModel):
    kind: Literal["label", "role", "text"]
    name: Binding
    role: Literal["button", "link", "textbox", "combobox", "heading"] | None = None

    @model_validator(mode="after")
    def valid_role(self):
        if (self.kind == "role") != (self.role is not None):
            raise ValueError("Only role strategies require a role")
        return self


class Target(StrictModel):
    frame: Literal["content", "shell"] = "content"
    strategies: list[Strategy] = Field(min_length=1, max_length=3)
    table: Literal["Member search results", "Member accounts"] | None = None
    row: list[CellMatch] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def table_scope(self):
        if bool(self.table) != bool(self.row):
            raise ValueError("Table and row constraints must occur together")
        for cell in self.row:
            required = {"Member ID": "member_id", "Product": "product_name"}.get(
                cell.column
            )
            if required and cell.value.input_ref != required:
                raise ValueError(
                    "Member and product targets require explicit input references"
                )
        return self


class Checkpoint(StrictModel):
    screen: Screen
    verify_member: bool = False
    verify_product: bool = False
    require_active: bool = False
    require_balances: bool = False


FINAL = Checkpoint(
    screen="account_details",
    verify_member=True,
    verify_product=True,
    require_active=True,
    require_balances=True,
)


class Action(StrictModel):
    kind: ActionKind
    target: Target | None = None
    input_ref: InputName | None = None
    checkpoint: Checkpoint | None = None
    # The only model-requested navigation is the configured tenant entry point.
    destination: Literal["entry"] | None = None

    @model_validator(mode="after")
    def shape(self):
        needs_target = self.kind in ("click", "fill", "select")
        if needs_target != (self.target is not None):
            raise ValueError("Invalid action target")
        if (self.kind in ("fill", "select")) != (self.input_ref is not None):
            raise ValueError("Fill/select require an input reference")
        if (self.kind == "navigate") != (self.destination is not None):
            raise ValueError("Navigate requires entry binding")
        if (self.kind == "check") != (self.checkpoint is not None):
            raise ValueError("Only check actions carry a checkpoint")
        return self


class Decision(StrictModel):
    """Untrusted model reply; references this observation's controls, never executable code."""

    action: ActionKind
    control_ref: str | None
    input_ref: InputName | None
    screen: Screen | None
    rationale: str = Field(max_length=240)


class Step(StrictModel):
    id: str = Field(pattern=r"^s[0-9]{3}$")
    action: Action
    before: Checkpoint | None = None
    after: Checkpoint | None = None


class InputContract(StrictModel):
    name: InputName
    type: Literal["string", "secret"]
    required: Literal[True] = True


class OutputContract(StrictModel):
    name: Literal[
        "product_name",
        "account_status",
        "currency",
        "current_balance",
        "available_balance",
        "active_holds",
        "as_of",
    ]
    type: Literal["string", "decimal", "timestamp"]


INPUT_CONTRACT = [
    InputContract(name=n, type="secret" if n.startswith("staff_") else "string")
    for n in ("member_id", "product_name", "staff_username", "staff_password")
]
OUTPUT_CONTRACT = [
    OutputContract(
        name=n,
        type="decimal"
        if n in ("current_balance", "available_balance", "active_holds")
        else "timestamp"
        if n == "as_of"
        else "string",
    )
    for n in (
        "product_name",
        "account_status",
        "currency",
        "current_balance",
        "available_balance",
        "active_holds",
        "as_of",
    )
]


class Compatibility(StrictModel):
    product: Literal["demo-credit-union-staff-console"] = (
        "demo-credit-union-staff-console"
    )
    ui_version: Literal["1.0"] = "1.0"
    adapter: Literal["playwright-dom-v1"] = "playwright-dom-v1"


class OutcomeRule(StrictModel):
    code: Literal["INVALID_INPUT", "MEMBER_NOT_FOUND", "NO_ELIGIBLE_ACCOUNT"]
    signal: Literal["invalid_input", "member_not_found", "no_eligible_account"]


class RecoveryRule(StrictModel):
    signal: Literal["temporary_failure"] = "temporary_failure"
    action: Literal["retry_visible_read_link"] = "retry_visible_read_link"
    max_attempts: int = Field(default=1, ge=0, le=2)


class Provenance(StrictModel):
    kind: Literal["llm_discovery", "simulated_discovery", "hand_authored_executor_test"]
    run_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    provider: str = Field(max_length=80)
    created_at: str


class Capability(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: Literal["read_account_balances"] = "read_account_balances"
    version: Literal["1.0.0"] = "1.0.0"
    description: str = (
        "Read balances for an active account after verifying member and product."
    )
    compatibility: Compatibility = Field(default_factory=Compatibility)
    inputs: list[InputContract] = Field(default_factory=lambda: INPUT_CONTRACT.copy())
    outputs: list[OutputContract] = Field(
        default_factory=lambda: OUTPUT_CONTRACT.copy()
    )
    preconditions: list[Checkpoint] = Field(
        default_factory=lambda: [Checkpoint(screen="sign_in")]
    )
    steps: list[Step] = Field(min_length=1, max_length=50)
    final_checkpoint: Checkpoint = Field(default_factory=lambda: FINAL.model_copy())
    business_outcomes: list[OutcomeRule] = Field(
        default_factory=lambda: [
            OutcomeRule(code=c, signal=s)
            for c, s in [
                ("INVALID_INPUT", "invalid_input"),
                ("MEMBER_NOT_FOUND", "member_not_found"),
                ("NO_ELIGIBLE_ACCOUNT", "no_eligible_account"),
            ]
        ]
    )
    recovery: list[RecoveryRule] = Field(
        default_factory=lambda: [RecoveryRule()], max_length=1
    )
    policy_requirements: Literal["read-only-v1"] = "read-only-v1"
    resume_checkpoint: Checkpoint = Field(default_factory=lambda: FINAL.model_copy())
    provenance: Provenance
    lifecycle: Literal["draft", "qualifying", "approved", "rejected"] = "approved"

    @model_validator(mode="after")
    def enforce_contract(self):
        if self.inputs != INPUT_CONTRACT or self.outputs != OUTPUT_CONTRACT:
            raise ValueError("Unsupported input/output contract")
        if self.final_checkpoint != FINAL or self.resume_checkpoint != FINAL:
            raise ValueError("Balance verification may not be weakened")
        if len({s.id for s in self.steps}) != len(self.steps):
            raise ValueError("Duplicate step IDs")
        if self.steps[-1].action.kind != "finish":
            raise ValueError("Capability must end in finish")
        return self


class Tenant(StrictModel):
    binding_version: Literal["1.0"] = "1.0"
    entry_url: str = "http://127.0.0.1:8000/"
    frame_name: str = Field(
        default="bank-content", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$"
    )
    compatibility: Compatibility = Field(default_factory=Compatibility)
    # Only one actual tenant is implemented. No unchecked selector override facility.


class RuntimeConfig(StrictModel):
    headless: bool = True
    action_timeout_ms: int = Field(default=6000, ge=100, le=30000)
    overall_timeout_seconds: float = Field(default=120, ge=1, le=900)
    max_steps: int = Field(default=25, ge=1, le=50)
    invalid_response_retries: int = Field(default=2, ge=0, le=3)
    max_no_progress: int = Field(default=3, ge=1, le=5)
    operator_timeout_seconds: float = Field(default=300, ge=1, le=1800)
    interactive: bool = False
    evidence_dir: str = "evidence/local"


class Ownership(str, Enum):
    AUTOMATION = "automation"
    PAUSED = "paused"
    HUMAN = "human"
    COMPLETED = "completed"


class BalanceOutputs(StrictModel):
    product_name: str
    account_status: Literal["Active"]
    currency: Literal["USD"]
    current_balance: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$")
    available_balance: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$")
    active_holds: str = Field(pattern=r"^[0-9]+\.[0-9]{2}$")
    as_of: str


class RecentTransaction(StrictModel):
    posted_at: str
    description: str
    amount: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$")
    ledger_balance: str = Field(pattern=r"^-?[0-9]+\.[0-9]{2}$")


class TransactionsOutputs(StrictModel):
    product_name: str
    account_status: Literal["Active"]
    transactions: list[RecentTransaction] = Field(max_length=5)


class Result(StrictModel):
    status: Literal["success", "business_outcome", "intervention_required", "failure"]
    code: str
    run_id: str
    step_id: str | None = None
    outputs: BalanceOutputs | None = None
    expected: str | None = None
    observed: str | None = None
    evidence_ref: str | None = None


class AutomationError(Exception):
    def __init__(self, code: str, expected: str = "", observed: str = ""):
        super().__init__(code)
        self.code, self.expected, self.observed = code, expected, observed
