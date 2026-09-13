"""Trusted policy configuration is separate from artifacts and untrusted page text."""

import re
from urllib.parse import urlsplit, unquote
from pydantic import Field, model_validator
from .models import StrictModel, Action, Ownership, AutomationError


class PolicyConfig(StrictModel):
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8000"]
    )
    allowed_get_routes: list[str] = Field(
        default_factory=lambda: [
            r"/",
            r"/static/style\.css",
            r"/ui/sign-in",
            r"/ui/search",
            r"/ui/members/[0-9]{5}",
            r"/ui/accounts/[0-9]+",
        ]
    )
    allowed_post_routes: list[str] = Field(default_factory=lambda: [r"/ui/sign-in"])
    allowed_actions: list[str] = Field(
        default_factory=lambda: [
            "navigate",
            "click",
            "fill",
            "select",
            "extract",
            "check",
            "finish",
        ]
    )
    version: str = "read-only-v1"

    @model_validator(mode="after")
    def origins(self):
        for origin in self.allowed_origins:
            p = urlsplit(origin)
            if (
                p.scheme not in ("http", "https")
                or not p.netloc
                or p.username
                or p.password
                or p.path
                or p.query
                or p.fragment
            ):
                raise ValueError("Allowed origins must be exact HTTP(S) origins")
        for route in self.allowed_get_routes + self.allowed_post_routes:
            re.compile(route)
        return self


class Policy:
    def __init__(self, config: PolicyConfig):
        self.config = config

    def authorize_url(self, url: str, method="GET"):
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = unquote(parsed.path)
        if (
            parsed.username
            or parsed.password
            or origin not in self.config.allowed_origins
        ):
            raise AutomationError(
                "FORBIDDEN_ORIGIN", "approved origin", "unapproved destination"
            )
        if any(
            word in path.lower().split("/")
            for word in (
                "transfer",
                "transfers",
                "delete",
                "modify",
                "admin",
                "open_account",
            )
        ):
            raise AutomationError(
                "FORBIDDEN_ROUTE", "read-only route", "state-changing route"
            )
        routes = (
            self.config.allowed_get_routes
            if method == "GET"
            else self.config.allowed_post_routes
            if method == "POST"
            else []
        )
        if not any(re.fullmatch(pattern, path) for pattern in routes):
            raise AutomationError(
                "FORBIDDEN_ROUTE",
                "approved read or authentication route",
                "unapproved route or method",
            )
        # Even broadened tenant configuration cannot enable banking writes.
        if method == "POST" and path != "/ui/sign-in":
            raise AutomationError("BANKING_WRITE_BLOCKED")

    def authorize_action(self, action: Action, ownership: Ownership):
        if ownership != Ownership.AUTOMATION:
            raise AutomationError("CONTROL_NOT_OWNED")
        if action.kind not in self.config.allowed_actions:
            raise AutomationError("FORBIDDEN_ACTION")

    def authorize_control(self, action: Action, meta: dict):
        # Destination from the actual link/form is checked, not a model-supplied label.
        if action.kind in ("fill", "select"):
            expected = {
                "staff_username": ("/ui/sign-in", "Staff username"),
                "staff_password": ("/ui/sign-in", "Password"),
                "member_id": ("/ui/search", "Member ID"),
                "product_name": ("/ui/search", "Product name"),
            }
            route, label = expected[action.input_ref]
            if urlsplit(meta["page_url"]).path != route or meta["label"] != label:
                raise AutomationError("SENSITIVE_BINDING_WRONG_TARGET")
        if action.kind == "click":
            if meta["tag"] == "a":
                if not meta["destination"]:
                    raise AutomationError("UNCLASSIFIED_CONTROL")
                if meta["text"] not in {
                    "View",
                    "Member search",
                    "Member overview",
                    "Next page",
                    "Previous page",
                    "Retry account load",
                }:
                    raise AutomationError("UNCLASSIFIED_CONTROL")
            elif meta["tag"] in ("button", "input"):
                allowed = {
                    ("/ui/sign-in", "Sign in", "POST"),
                    ("/ui/search", "Search", "GET"),
                }
                if (
                    urlsplit(meta["destination"]).path,
                    meta["text"],
                    meta["method"],
                ) not in allowed:
                    raise AutomationError("BANKING_WRITE_BLOCKED")
            else:
                raise AutomationError("UNCLASSIFIED_CONTROL")
        if meta.get("destination"):
            self.authorize_url(meta["destination"], meta["method"])
