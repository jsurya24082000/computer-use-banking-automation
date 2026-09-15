"""One browser adapter. Only visible DOM is read; no banking imports or HTTP clients.

The few evaluated scripts below are trusted, static adapter code, never model code.
Target fallbacks: declared order; exact unique visible match; ambiguity never falls through.
"""

import asyncio
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from urllib.parse import urljoin

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .models import (
    Action,
    AutomationError,
    BalanceOutputs,
    Binding,
    CellMatch,
    Checkpoint,
    Inputs,
    Ownership,
    RuntimeConfig,
    RecentTransaction,
    TransactionsOutputs,
    Strategy,
    Target,
    Tenant,
)
from .policy import Policy
from .evidence import Evidence

HEADINGS = {
    "Staff sign-in": "sign_in",
    "Member search": "member_search",
    "Member overview": "member_overview",
    "Account details": "account_details",
}


def role_target(name, role="button", table=None, row=None):
    return Target(
        strategies=[Strategy(kind="role", role=role, name=Binding(literal=name))],
        table=table,
        row=row or [],
    )


def label_target(name):
    return Target(strategies=[Strategy(kind="label", name=Binding(literal=name))])


async def visible_texts(locator, keep_positions=False):
    result = []
    for element in await locator.all():
        if await element.is_visible():
            result.append((await element.inner_text()).strip())
        elif keep_positions:
            result.append(None)
    return result


class SurfaceAdapter(Protocol):
    async def observe(self) -> dict: ...
    async def execute(self, action: Action): ...
    async def verify(self, checkpoint: Checkpoint): ...
    async def balances(self) -> BalanceOutputs: ...
    async def recent_transactions(self) -> TransactionsOutputs: ...
    async def extract_outputs(self) -> "BalanceOutputs | TransactionsOutputs": ...
    async def snapshot(self) -> dict: ...


class BrowserSurface:
    def __init__(
        self,
        tenant: Tenant,
        inputs: Inputs,
        config: RuntimeConfig,
        policy: Policy,
        evidence: Evidence,
        workflow: str = "read_account_balances",
    ):
        self.tenant, self.inputs, self.config, self.policy, self.evidence = (
            tenant,
            inputs,
            config,
            policy,
            evidence,
        )
        # Selects balances() vs recent_transactions() everywhere outputs are
        # produced (extract/finish actions, checkpoint verification, final
        # results). This is the only switch: it is never inferred from goal
        # text or model output, only from the declared/compiled workflow.
        self.workflow = workflow
        self.ownership = Ownership.AUTOMATION
        self.violation: AutomationError | None = None
        self.controls: dict[str, Target] = {}
        self.browser = self.context = self.page = self.pw = None
        self.outputs = None

    async def __aenter__(self):
        self.policy.authorize_url(self.tenant.entry_url)
        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.launch(headless=self.config.headless)
            self.context = await self.browser.new_context(
                service_workers="block", accept_downloads=False
            )
            self.context.set_default_timeout(self.config.action_timeout_ms)
            self.context.set_default_navigation_timeout(self.config.action_timeout_ms)
            await self.context.route("**/*", self._route)
            await self.context.route_web_socket("**/*", lambda ws: ws.close())
            await self.context.expose_binding("recordHumanEvent", self._human_event)
            await self.context.add_init_script("""(() => {
              for (const kind of ['click','input','change','submit']) {
                document.addEventListener(kind, e => {
                  if (e.isTrusted && window.recordHumanEvent) {
                    window.recordHumanEvent({kind,tag:(e.target.tagName||'').toLowerCase()}).catch(()=>{});
                  }
                },true);
              }
            })();""")
            self.page = await self.context.new_page()
            # Playwright route handlers do not reliably re-run for every redirect
            # hop. Inspect actual response headers before Chromium follows them.
            # This is network policy enforcement, not a business-endpoint client.
            self.cdp = await self.context.new_cdp_session(self.page)
            self.cdp.on("Fetch.requestPaused", self._response_gate)
            await self.cdp.send(
                "Fetch.enable",
                {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]},
            )
            self.context.on("page", self._popup)
            self.page.on("framenavigated", self._navigated)
            self.page.on("dialog", self._native_dialog)
            self.page.on("download", lambda download: download.cancel())
            await self.page.goto(self.tenant.entry_url, wait_until="domcontentloaded")
            await self.settle()
            await self.compatible()
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        # Teardown must stay bounded: a wedged browser or driver process can
        # otherwise stall the whole run far beyond the caller's overall
        # timeout, because Playwright close/stop awaits do not always honour
        # outer cancellation promptly. Give each step its own short budget.
        for action in (
            self.browser.close() if self.browser else None,
            self.pw.stop() if self.pw else None,
        ):
            if action is None:
                continue
            try:
                await asyncio.wait_for(asyncio.shield(action), timeout=5)
            except Exception:
                pass

    async def _route(self, route):
        try:
            self.policy.authorize_url(route.request.url, route.request.method)
            if self.ownership == Ownership.PAUSED:
                raise AutomationError("REQUEST_WHILE_PAUSED")
            await route.continue_()
        except AutomationError as exc:
            self.violation = exc
            self.evidence.event("policy_block", code=exc.code)
            await route.abort("blockedbyclient")

    async def _response_gate(self, event):
        request_id = event["requestId"]
        try:
            status = event.get("responseStatusCode", 0)
            if status in (301, 302, 303, 307, 308):
                location = next(
                    (
                        h["value"]
                        for h in event.get("responseHeaders", [])
                        if h["name"].lower() == "location"
                    ),
                    None,
                )
                if location:
                    method = event["request"]["method"]
                    if status == 303 or (status in (301, 302) and method == "POST"):
                        method = "GET"
                    self.policy.authorize_url(
                        urljoin(event["request"]["url"], location), method
                    )
            await self.cdp.send("Fetch.continueRequest", {"requestId": request_id})
        except AutomationError as exc:
            self.violation = exc
            self.evidence.event("policy_block", code=exc.code)
            await self.cdp.send(
                "Fetch.failRequest",
                {"requestId": request_id, "errorReason": "BlockedByClient"},
            )

    async def _popup(self, page):
        self.violation = AutomationError("POPUP_BLOCKED")
        self.evidence.event("policy_block", code="POPUP_BLOCKED")
        await page.close()

    async def _native_dialog(self, dialog):
        # No unknown confirmation may remain pending in an in-flight action.
        await dialog.dismiss()
        self.violation = AutomationError("UNEXPECTED_DIALOG")
        self.evidence.event("dialog_stopped", code="UNEXPECTED_DIALOG")

    async def _navigated(self, frame):
        if frame.url == "about:blank":
            return
        try:
            self.policy.authorize_url(frame.url)
        except AutomationError as exc:
            self.violation = exc
        if self.ownership == Ownership.HUMAN:
            self.evidence.event(
                "human_interaction",
                interaction="navigation",
                frame="content" if frame.name == self.tenant.frame_name else "shell",
            )

    async def _human_event(self, source, payload):
        if self.ownership != Ownership.HUMAN or not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        tag = payload.get("tag")
        if kind in ("click", "input", "change", "submit") and tag in (
            "a",
            "button",
            "input",
            "select",
            "form",
            "textarea",
        ):
            self.evidence.event(
                "human_interaction",
                interaction=kind,
                tag=tag,
                frame="content"
                if source["frame"].name == self.tenant.frame_name
                else "shell",
            )

    def assert_safe(self):
        if self.violation:
            raise self.violation

    async def frame(self, scope="content"):
        if scope == "shell":
            return self.page
        iframe = self.page.locator(f'iframe[name="{self.tenant.frame_name}"]')
        try:
            await iframe.wait_for(
                state="attached", timeout=self.config.action_timeout_ms
            )
        except PlaywrightTimeout:
            raise AutomationError("FRAME_NOT_FOUND")
        if await iframe.count() != 1:
            raise AutomationError("AMBIGUOUS_FRAME")
        handle = await iframe.element_handle()
        frame = await handle.content_frame() if handle else None
        if frame:
            return frame
        named = [
            frame
            for frame in self.page.frames
            if frame.name == self.tenant.frame_name
        ]
        if len(named) > 1:
            raise AutomationError("AMBIGUOUS_FRAME")
        if named:
            return named[0]
        try:
            await self.page.wait_for_event(
                "frameattached",
                predicate=lambda frame: frame.name == self.tenant.frame_name,
                timeout=self.config.action_timeout_ms,
            )
        except PlaywrightTimeout:
            raise AutomationError("FRAME_NOT_FOUND")
        named = [
            frame
            for frame in self.page.frames
            if frame.name == self.tenant.frame_name
        ]
        if len(named) != 1:
            raise AutomationError(
                "AMBIGUOUS_FRAME" if named else "FRAME_NOT_FOUND"
            )
        return named[0]

    async def settle(self):
        frame = await self.frame()
        await frame.wait_for_load_state("domcontentloaded")
        await frame.locator("h1").wait_for(state="visible")
        self.assert_safe()
        self.policy.authorize_url(frame.url)

    async def compatible(self):
        # Visible version/branding is an application compatibility checkpoint.
        visible = await self.page.locator("header").inner_text()
        if "Demo Credit Union" not in visible or "Version 1.0" not in visible:
            raise AutomationError(
                "INCOMPATIBLE_UI",
                "Demo Credit Union version 1.0",
                "different visible application/version",
            )

    async def fields(self):
        frame = await self.frame()
        return await frame.locator("dl").evaluate_all("""lists => {
          const out={};
          for(const list of lists) for(const dt of list.querySelectorAll('dt')) {
            const dd=dt.nextElementSibling;
            if(dt.checkVisibility() && dd && dd.tagName==='DD' && dd.checkVisibility()) {
              const key=dt.innerText.trim();
              if(key in out) throw new Error('Duplicate field');
              out[key]=dd.innerText.trim();
            }
          }
          return out;
        }""")

    async def screen(self):
        frame = await self.frame()
        headings = await visible_texts(frame.locator("h1"))
        if len(headings) != 1:
            return "unknown"
        screen = HEADINGS.get(headings[0].strip(), "unknown")
        if (
            screen == "member_search"
            and await frame.get_by_role(
                "table", name="Member search results", exact=True
            ).count()
        ):
            return "search_results"
        return screen

    async def signal(self):
        frame = await self.frame()
        text = await frame.locator("body").inner_text()
        if "Permission denied" in text:
            return "permission_denied"
        if "Session expired." in text:
            return "session_expired"
        if "Invalid credentials." in text:
            return "invalid_credentials"
        if "Invalid member ID." in text:
            return "invalid_input"
        if "Member not found" in text:
            return "member_not_found"
        if "Temporary application failure" in text:
            return "temporary_failure"
        if await frame.get_by_role("dialog").count():
            return "blocking_dialog"
        if await self.screen() == "member_overview":
            values = await self.fields()
            if values.get("Member ID") != self.inputs.member_id:
                return "wrong_member"
            matches = await self.matching_account_rows()
            if not matches:
                return "no_eligible_account"
            if len(matches) > 1:
                return "ambiguous_account"
        return "normal"

    async def matching_account_rows(self):
        frame = await self.frame()
        table = frame.get_by_role("table", name="Member accounts", exact=True)
        if await table.count() != 1:
            raise AutomationError("TARGET_NOT_FOUND")
        headers = await visible_texts(table.locator("thead th"), keep_positions=True)
        if headers.count("Product") != 1 or headers.count("Status") != 1:
            raise AutomationError("AMBIGUOUS_TARGET")
        product_index, status_index = headers.index("Product"), headers.index("Status")
        matches = []
        for row in await table.locator("tbody tr").all():
            if not await row.is_visible():
                continue
            cells = await visible_texts(row.locator("td"), keep_positions=True)
            if (
                len(cells) > max(product_index, status_index)
                and cells[product_index] == self.inputs.product_name
                and cells[status_index] == "Active"
            ):
                matches.append(row)
        return matches

    async def snapshot(self):
        fields = await self.fields()
        return {
            "screen": await self.screen(),
            "signal": await self.signal(),
            "control_count": len(self.controls),
            "matching_member": fields.get("Member ID") == self.inputs.member_id,
            "matching_product": fields.get("Product name") == self.inputs.product_name,
            "active": fields.get("Account status") == "Active",
            "balance_fields_present": all(
                k in fields
                for k in ("Current balance", "Available balance", "Currency")
            ),
        }

    async def observe(self):
        """Sanitized visible control catalog with explicit reusable bindings.

        Unrelated names, identifiers, amounts and field values are never sent to the model.
        Dynamic row identity is represented as an input reference, not string replacement.
        """
        self.assert_safe()
        frame = await self.frame()
        self.controls = {}
        descriptions = []

        async def add(target, label):
            try:
                await self.resolve(target)
            except AutomationError:
                return False
            cid = f"c{len(self.controls) + 1:02d}"
            self.controls[cid] = target
            descriptions.append(
                {
                    "control_ref": cid,
                    "description": label,
                    "target": target.model_dump(mode="json", exclude_none=True),
                }
            )
            return True

        for label in ("Staff username", "Password", "Member ID", "Member name"):
            if await frame.get_by_label(label, exact=True).count():
                supported = await add(
                    label_target(label), f"Editable field: {label}; value omitted"
                )
                if supported:
                    ref = {
                        "Staff username": "staff_username",
                        "Password": "staff_password",
                        "Member ID": "member_id",
                    }.get(label)
                    if ref:
                        descriptions[-1]["value_matches_input"] = (
                            await frame.get_by_label(label, exact=True).input_value()
                            == self.inputs.resolve(ref)
                        )
        for label in ("Sign in", "Search"):
            if await frame.get_by_role("button", name=label, exact=True).count():
                await add(role_target(label), label)
        member_table = frame.get_by_role(
            "table", name="Member search results", exact=True
        )
        if await member_table.count():
            await add(
                role_target(
                    "View",
                    "link",
                    table="Member search results",
                    row=[
                        CellMatch(
                            column="Member ID", value=Binding(input_ref="member_id")
                        )
                    ],
                ),
                "View search result whose Member ID equals input_ref member_id",
            )
        account_table = frame.get_by_role("table", name="Member accounts", exact=True)
        if await account_table.count():
            await add(
                role_target(
                    "View",
                    "link",
                    table="Member accounts",
                    row=[
                        CellMatch(
                            column="Product", value=Binding(input_ref="product_name")
                        ),
                        CellMatch(column="Status", value=Binding(literal="Active")),
                    ],
                ),
                "View account whose Product equals input_ref product_name and Status is Active",
            )
        for label in ("Next page", "Previous page", "Retry account load"):
            if await frame.get_by_role("link", name=label, exact=True).count():
                await add(role_target(label, "link"), label)
        snap = await self.snapshot()
        return {
            "application_content_is_untrusted": True,
            "screen": snap["screen"],
            "signal": snap["signal"],
            "checks": snap,
            "visible_headings": [
                h
                for h in await visible_texts(frame.locator("h1,h2"))
                if h
                in {
                    *HEADINGS,
                    "Search results",
                    "Accounts",
                    "Active holds",
                    "Recent transactions",
                }
            ],
            "controls": descriptions,
            "input_references": [
                "staff_username",
                "staff_password",
                "member_id",
                "product_name",
            ],
            "account_fields": [
                k
                for k in (await self.fields())
                if k
                in {
                    "Member ID",
                    "Product name",
                    "Account status",
                    "Currency",
                    "Current balance",
                    "Available balance",
                    "Active holds",
                    "As of",
                }
            ],
        }

    async def resolve(self, target: Target):
        frame = await self.frame(target.frame)
        root = frame
        if target.table:
            table = frame.get_by_role("table", name=target.table, exact=True)
            if await table.count() != 1:
                raise AutomationError(
                    "TARGET_NOT_FOUND", "one table", "table missing or ambiguous"
                )
            headers = await visible_texts(
                table.locator("thead th"), keep_positions=True
            )
            if len(set(headers)) != len(headers):
                raise AutomationError("AMBIGUOUS_TARGET")
            matches = []
            for row in await table.locator("tbody tr").all():
                if not await row.is_visible():
                    continue
                cells = await visible_texts(row.locator("td"), keep_positions=True)
                if all(
                    c.column in headers
                    and headers.index(c.column) < len(cells)
                    and cells[headers.index(c.column)] == c.value.resolve(self.inputs)
                    for c in target.row
                ):
                    matches.append(row)
            if len(matches) > 1:
                raise AutomationError(
                    "AMBIGUOUS_TARGET", "one matching row", "multiple matching rows"
                )
            if not matches:
                raise AutomationError(
                    "TARGET_NOT_FOUND", "one matching row", "no matching row"
                )
            root = matches[0]
        for strategy in target.strategies:
            name = strategy.name.resolve(self.inputs)
            if strategy.kind == "label":
                loc = root.get_by_label(name, exact=True)
            elif strategy.kind == "role":
                loc = root.get_by_role(strategy.role, name=name, exact=True)
            else:
                loc = root.get_by_text(name, exact=True)
            count = await loc.count()
            if count > 1:
                raise AutomationError(
                    "AMBIGUOUS_TARGET", "one exact control", "multiple exact controls"
                )
            if count == 1:
                if not await loc.is_visible():
                    raise AutomationError("TARGET_NOT_VISIBLE")
                return loc
        raise AutomationError(
            "TARGET_NOT_FOUND",
            "one exact visible control",
            "no declared locator matched",
        )

    async def metadata(self, locator):
        return await locator.evaluate("""e => {
          const f=e.form;
          const label=e.labels ? Array.from(e.labels).map(x=>x.innerText.trim()).join(' ') : '';
          return {tag:e.tagName.toLowerCase(),text:e.innerText.trim()||e.value||'',label,
            destination:e.tagName==='A'?e.href:(f?f.action:''),
            method:e.tagName==='A'?'GET':(f?(f.method||'GET').toUpperCase():'GET'),page_url:location.href};
        }""")

    async def execute(self, action: Action):
        self.policy.authorize_action(action, self.ownership)
        self.assert_safe()
        await self.compatible()
        try:
            if action.kind == "navigate":
                self.policy.authorize_url(self.tenant.entry_url)
                await self.page.goto(
                    self.tenant.entry_url, wait_until="domcontentloaded"
                )
            elif action.kind in ("fill", "select", "click"):
                frame = await self.frame(action.target.frame)
                self.policy.authorize_url(frame.url)
                loc = await self.resolve(action.target)
                meta = await self.metadata(loc)
                self.policy.authorize_control(action, meta)
                if action.kind == "fill":
                    await loc.fill(self.inputs.resolve(action.input_ref))
                elif action.kind == "select":
                    await loc.select_option(label=self.inputs.resolve(action.input_ref))
                else:
                    # This vendor adapter classifies only server-rendered navigation
                    # controls. Wait for that navigation, not the old page's heading.
                    async with frame.expect_navigation(
                        wait_until="domcontentloaded",
                        timeout=self.config.action_timeout_ms,
                    ):
                        await loc.click()
            elif action.kind == "check":
                await self.verify(action.checkpoint)
            elif action.kind in ("extract", "finish"):
                self.outputs = await self.extract_outputs()
            await self.settle()
            self.assert_safe()
        except PlaywrightTimeout:
            self.assert_safe()
            raise AutomationError(
                "ACTION_TIMEOUT",
                "visible target or completed navigation",
                "bounded action timeout",
            ) from None
        except AutomationError:
            raise
        except Exception:
            self.assert_safe()
            raise AutomationError(
                "BROWSER_ACTION_FAILED",
                "supported browser action",
                "browser operation failed",
            ) from None

    async def verify(self, checkpoint: Checkpoint):
        self.assert_safe()
        current = await self.screen()
        if current != checkpoint.screen:
            raise AutomationError("CHECKPOINT_FAILED", checkpoint.screen, current)
        fields = await self.fields()
        if (
            checkpoint.verify_member
            and fields.get("Member ID") != self.inputs.member_id
        ):
            raise AutomationError(
                "MEMBER_MISMATCH", "requested member", "different or absent member"
            )
        if (
            checkpoint.verify_product
            and fields.get("Product name") != self.inputs.product_name
        ):
            raise AutomationError(
                "PRODUCT_MISMATCH", "requested product", "different or absent product"
            )
        if checkpoint.require_active and fields.get("Account status") != "Active":
            raise AutomationError("ACCOUNT_NOT_ACTIVE")
        if checkpoint.require_balances:
            await self.balances()
        if checkpoint.require_transactions:
            await self.recent_transactions()

    async def extract_outputs(self):
        """Single dispatch point for produced outputs: never hardcoded to
        balances(). The workflow discriminator decides, so a transactions
        capability can never succeed with balance-only outputs."""
        if self.workflow == "read_recent_transactions":
            return await self.recent_transactions()
        return await self.balances()

    async def balances(self):
        if await self.screen() != "account_details":
            raise AutomationError(
                "CHECKPOINT_FAILED", "account_details", "other screen"
            )
        fields = await self.fields()
        if fields.get("Member ID") != self.inputs.member_id:
            raise AutomationError("MEMBER_MISMATCH")
        if fields.get("Product name") != self.inputs.product_name:
            raise AutomationError("PRODUCT_MISMATCH")
        if fields.get("Account status") != "Active":
            raise AutomationError("ACCOUNT_NOT_ACTIVE")
        if fields.get("Currency") != "USD":
            raise AutomationError("INVALID_CURRENCY")

        def decimal_field(label):
            value = fields.get(label, "")
            if not re.fullmatch(
                r"\$-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)\.[0-9]{2}", value
            ):
                raise AutomationError(
                    "INVALID_BALANCE",
                    "decimal currency amount",
                    "missing or malformed amount",
                )
            return Decimal(value[1:].replace(",", ""))

        current, available, holds = [
            decimal_field(k)
            for k in ("Current balance", "Available balance", "Active holds")
        ]
        if holds < 0 or available != current - holds:
            raise AutomationError("INCONSISTENT_BALANCES")
        try:
            timestamp = fields["As of"]
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        except (ValueError, KeyError):
            raise AutomationError("INVALID_TIMESTAMP") from None
        return BalanceOutputs(
            member_id=self.inputs.member_id,
            product_name=self.inputs.product_name,
            account_status="Active",
            currency="USD",
            current_balance=f"{current:.2f}",
            available_balance=f"{available:.2f}",
            active_holds=f"{holds:.2f}",
            as_of=timestamp,
        )

    async def recent_transactions(self):
        if await self.screen() != "account_details":
            raise AutomationError("CHECKPOINT_FAILED")
        fields = await self.fields()
        if fields.get("Member ID") != self.inputs.member_id:
            raise AutomationError("MEMBER_MISMATCH")
        if fields.get("Product name") != self.inputs.product_name:
            raise AutomationError("PRODUCT_MISMATCH")
        if fields.get("Account status") != "Active":
            raise AutomationError("ACCOUNT_NOT_ACTIVE")
        frame = await self.frame()
        table = frame.get_by_role(
            "table", name="Recent synthetic transactions", exact=True
        )
        if await table.count() != 1:
            raise AutomationError("TRANSACTIONS_NOT_FOUND")
        headers = await visible_texts(table.locator("thead th"))
        if headers != ["Posted", "Description", "Amount", "Ledger balance"]:
            raise AutomationError("INVALID_TRANSACTION_HEADERS")
        rows = []
        previous_date = None
        for row in await table.locator("tbody tr").all():
            cells = await visible_texts(row.locator("td"))
            if len(cells) != 4 or cells[0] == "No transactions":
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
                raise AutomationError("INVALID_TRANSACTION_DATE")
            try:
                posted = date.fromisoformat(cells[0])
            except ValueError:
                raise AutomationError("INVALID_TRANSACTION_DATE") from None
            if previous_date is not None and posted > previous_date:
                raise AutomationError("TRANSACTIONS_NOT_NEWEST_FIRST")
            previous_date = posted
            amounts = []
            for value in cells[2:]:
                if not re.fullmatch(r"\$-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)\.[0-9]{2}", value):
                    raise AutomationError("INVALID_TRANSACTION_AMOUNT")
                amounts.append(Decimal(value[1:].replace(",", "")))
            rows.append(
                RecentTransaction(
                    posted_at=cells[0],
                    description=cells[1],
                    amount=f"{amounts[0]:.2f}",
                    ledger_balance=f"{amounts[1]:.2f}",
                )
            )
        if len(rows) > 5:
            raise AutomationError("TOO_MANY_TRANSACTIONS")
        return TransactionsOutputs(
            member_id=self.inputs.member_id,
            product_name=self.inputs.product_name,
            account_status="Active",
            transactions=rows,
        )

