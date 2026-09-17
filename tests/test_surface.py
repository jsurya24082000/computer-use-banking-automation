import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import uuid
from types import SimpleNamespace
import pytest
from automation.evidence import Evidence
from automation.models import Action, AutomationError, Ownership, RuntimeConfig, Tenant
from automation.policy import Policy
from automation.surface import BrowserSurface, role_target, label_target
from .artifacts import executor_artifact


@asynccontextmanager
async def live(bank, inputs):
    evidence = Evidence(bank["config"].evidence_dir, uuid.uuid4().hex[:12], inputs)
    async with BrowserSurface(
        bank["tenant"], inputs, bank["config"], Policy(bank["policy"]), evidence
    ) as surface:
        yield surface, evidence


async def go_account(surface):
    for step in executor_artifact().steps[:7]:
        await surface.execute(step.action)


@pytest.mark.browser
async def test_ambiguous_targets_stop_without_first_fallback(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        frame = await surface.frame()
        await frame.locator("button").evaluate(
            "e=>e.parentElement.appendChild(e.cloneNode(true))"
        )
        with pytest.raises(AutomationError, match="AMBIGUOUS_TARGET"):
            await surface.resolve(role_target("Sign in"))


@pytest.mark.browser
async def test_duplicate_product_rows_stop(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        for step in executor_artifact().steps[:6]:
            await surface.execute(step.action)
        frame = await surface.frame()
        await frame.locator("tbody tr").first.evaluate(
            "e=>e.parentElement.appendChild(e.cloneNode(true))"
        )
        assert await surface.signal() == "ambiguous_account"
        with pytest.raises(AutomationError, match="AMBIGUOUS_TARGET"):
            await surface.resolve(executor_artifact().steps[6].action.target)


@pytest.mark.browser
@pytest.mark.parametrize(
    "field,value,code",
    [
        ("Member ID", "10002", "MEMBER_MISMATCH"),
        ("Product name", "Everyday Checking", "PRODUCT_MISMATCH"),
        ("Account status", "Closed", "ACCOUNT_NOT_ACTIVE"),
        ("Current balance", "not money", "INVALID_BALANCE"),
        ("Available balance", "$1.00", "INCONSISTENT_BALANCES"),
        ("Currency", "EUR", "INVALID_CURRENCY"),
        ("As of", "invalid", "INVALID_TIMESTAMP"),
    ],
)
async def test_final_checkpoint_catches_wrong_state(bank, inputs, field, value, code):
    async with live(bank, inputs) as (surface, evidence):
        await go_account(surface)
        frame = await surface.frame()
        await frame.locator("dl").evaluate(
            "(e,arg)=>{for(const dt of e.querySelectorAll('dt')) if(dt.innerText===arg[0])dt.nextElementSibling.innerText=arg[1]}",
            [field, value],
        )
        with pytest.raises(AutomationError, match=code):
            await surface.balances()


@pytest.mark.browser
async def test_actual_password_control_binding_is_checked(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        with pytest.raises(AutomationError, match="SENSITIVE_BINDING_WRONG_TARGET"):
            await surface.execute(
                Action(
                    kind="fill",
                    target=label_target("Staff username"),
                    input_ref="staff_password",
                )
            )
        surface.ownership = Ownership.HUMAN
        with pytest.raises(AutomationError, match="CONTROL_NOT_OWNED"):
            await surface.execute(
                Action(
                    kind="fill",
                    target=label_target("Password"),
                    input_ref="staff_password",
                )
            )


@pytest.mark.browser
async def test_observations_and_failure_snapshots_contain_no_sensitive_values(
    bank, inputs
):
    import json

    async with live(bank, inputs) as (surface, evidence):
        await go_account(surface)
        text = json.dumps(await surface.observe())
        ref = evidence.snapshot(await surface.snapshot())
        text += Path(ref).read_text()
        for raw in (
            "10001",
            "Mira Rowan",
            "4102",
            "4250.75",
            "4,250.75",
            "DemoBank!2026",
            "teller",
        ):
            assert raw not in text


@pytest.mark.browser
async def test_outgoing_fetch_is_blocked(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        # Same-origin avoids the app CSP blocking first: exercise the automation's
        # own request interceptor, independent of application defenses.
        await surface.page.evaluate("fetch('/ui/transfer').catch(()=>null)")
        with pytest.raises(AutomationError, match="FORBIDDEN_ROUTE"):
            surface.assert_safe()


@pytest.mark.browser
async def test_link_destination_checked_before_click(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        frame = await surface.frame()
        await frame.locator("body").evaluate(
            "e=>{const a=document.createElement('a');a.textContent='View';a.href='https://outside.example';e.appendChild(a)}"
        )
        with pytest.raises(AutomationError, match="FORBIDDEN_ORIGIN"):
            await surface.execute(
                Action(kind="click", target=role_target("View", "link"))
            )
        assert "outside.example" not in frame.url


@pytest.mark.browser
async def test_safe_looking_control_cannot_submit_bank_write(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        frame = await surface.frame()
        await frame.locator("form").evaluate("e=>e.action='/ui/accounts/1'")
        with pytest.raises(AutomationError, match="BANKING_WRITE_BLOCKED"):
            await surface.execute(Action(kind="click", target=role_target("Sign in")))


@pytest.mark.browser
async def test_ui_version_drift_stops(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        await surface.page.locator("header").evaluate(
            "e=>e.innerText='Demo Credit Union Version 2.0'"
        )
        with pytest.raises(AutomationError, match="INCOMPATIBLE_UI"):
            await surface.compatible()


@pytest.mark.browser
async def test_delayed_frame_registration_is_bounded_and_event_driven(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        await surface.page.locator("iframe").evaluate("e=>e.remove()")
        await surface.page.evaluate(
            """() => setTimeout(() => {
                const iframe = document.createElement('iframe');
                iframe.name = 'bank-content';
                iframe.src = '/ui/sign-in';
                document.body.appendChild(iframe);
            }, 100)"""
        )
        frame = await surface.frame()
        assert frame.name == "bank-content"


@pytest.mark.browser
async def test_missing_frame_fails_without_fallback(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        bank["config"].action_timeout_ms = 100
        await surface.page.locator("iframe").evaluate("e=>e.remove()")
        with pytest.raises(AutomationError, match="FRAME_NOT_FOUND"):
            await surface.frame()


@pytest.mark.browser
async def test_recent_transactions_are_typed_and_ordered(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        await go_account(surface)
        result = await surface.recent_transactions()
        assert len(result.transactions) == 2
        assert result.transactions[0].posted_at == "2026-09-12"
        assert result.transactions[1].posted_at == "2026-09-10"


class RegistrationPage:
    """Controllable registration state; no browser scheduling assumptions."""

    def __init__(self):
        self.frames = []
        self.current = None
        self.count = 1
        self.connected = True
        self.listeners = {}
        self.content_calls = 0
        self.disposed = 0
        self.on_content = None

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, frame):
        for callback in self.listeners.get(event, ()):
            callback(frame)

    def locator(self, selector):
        page = self

        class Handle:
            async def content_frame(self):
                page.content_calls += 1
                if page.on_content:
                    page.on_content()
                return page.current

            async def evaluate(self, expression):
                return page.connected

            async def dispose(self):
                page.disposed += 1

        class Locator:
            async def wait_for(self, **kwargs):
                return None

            async def count(self):
                return page.count

            async def element_handle(self):
                return Handle()

        return Locator()


def registration_surface(page, timeout=200):
    surface = BrowserSurface(
        Tenant(), None, RuntimeConfig(action_timeout_ms=timeout), None, None
    )
    surface.page = page
    return surface


def registered_frame(name="bank-content", detached=False):
    return SimpleNamespace(name=name, is_detached=lambda: detached)


@pytest.mark.asyncio
async def test_attached_frame_falls_back_when_content_frame_temporarily_unavailable():
    page = RegistrationPage()
    expected = registered_frame()

    def attach():
        page.current = expected
        page.frames = [expected]
        page.emit("frameattached", expected)

    page.on_content = lambda: asyncio.get_running_loop().call_soon(attach)
    assert await registration_surface(page).frame() is expected
    assert page.content_calls >= 2
    assert all(not callbacks for callbacks in page.listeners.values())


@pytest.mark.asyncio
async def test_unnamed_content_frame_waits_for_registration():
    page = RegistrationPage()
    expected = registered_frame(name="")
    page.current = expected
    page.frames = [expected]

    def register():
        expected.name = "bank-content"
        page.emit("framenavigated", expected)

    page.on_content = lambda: asyncio.get_running_loop().call_soon(register)
    assert await registration_surface(page).frame() is expected
    assert expected.name == "bank-content"
    assert page.content_calls >= 2
    assert page.disposed == page.content_calls
    assert all(not callbacks for callbacks in page.listeners.values())


@pytest.mark.asyncio
async def test_registration_event_during_inspection_is_not_lost():
    page = RegistrationPage()
    expected = registered_frame()

    def register_during_read():
        # Wake before changed.wait() is entered, while this read still returns None.
        page.frames = [expected]
        page.emit("framenavigated", expected)
        page.on_content = lambda: setattr(page, "current", expected)

    page.on_content = register_during_read
    assert await registration_surface(page).frame() is expected
    assert page.content_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_dom", [False, True])
async def test_duplicate_matching_frames_fail_closed(duplicate_dom):
    page = RegistrationPage()
    page.current = registered_frame()
    page.frames = [page.current]
    if duplicate_dom:
        page.count = 2
    else:
        page.frames.append(registered_frame())
    with pytest.raises(AutomationError, match="AMBIGUOUS_FRAME"):
        await registration_surface(page).frame()
    assert all(not callbacks for callbacks in page.listeners.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "unnamed", "detached", "disconnected"])
async def test_frame_registration_timeout_is_bounded(state):
    page = RegistrationPage()
    page.current = registered_frame(
        name="" if state == "unnamed" else "bank-content",
        detached=state == "detached",
    )
    page.frames = [page.current]
    if state == "missing":
        page.count = 0
    if state == "disconnected":
        page.connected = False
    # Outer watchdog detects a broken resolver timeout without hanging the suite.
    async with asyncio.timeout(1):
        with pytest.raises(AutomationError, match="FRAME_NOT_FOUND"):
            await registration_surface(page, timeout=100).frame()
    assert all(not callbacks for callbacks in page.listeners.values())


@pytest.mark.asyncio
async def test_frame_timeout_includes_stalled_locator_and_cleans_listeners():
    page = RegistrationPage()

    async def stalled_count():
        await asyncio.Event().wait()

    page.locator = lambda selector: SimpleNamespace(count=stalled_count)
    async with asyncio.timeout(1):
        with pytest.raises(AutomationError, match="FRAME_NOT_FOUND"):
            await registration_surface(page, timeout=100).frame()
    assert all(not callbacks for callbacks in page.listeners.values())


@pytest.mark.browser
async def test_redirect_to_outside_origin_is_intercepted(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        # Harness installs one synthetic redirect; all subsequent requests still
        # pass through the engine's original context-wide policy route.
        await surface.context.route(
            "**/ui/members/99999",
            lambda route: route.fulfill(
                status=302, headers={"Location": "https://outside.example/"}, body=""
            ),
        )
        try:
            await surface.page.goto(bank["origin"] + "/ui/members/99999")
        except Exception:
            pass
        with pytest.raises(AutomationError, match="FORBIDDEN_ORIGIN"):
            surface.assert_safe()


@pytest.mark.browser
async def test_popups_are_closed(bank, inputs):
    async with live(bank, inputs) as (surface, evidence):
        async with surface.context.expect_page() as event:
            await surface.page.evaluate("window.open('/ui/search')")
        popup = await event.value
        if not popup.is_closed():
            await popup.wait_for_event("close")
        assert popup.is_closed()
        with pytest.raises(AutomationError, match="POPUP_BLOCKED"):
            surface.assert_safe()
