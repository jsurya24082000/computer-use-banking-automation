import asyncio
import hashlib
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict
from typing import Literal

from .db import connect, money, password_matches

HERE = Path(__file__).parent
SCENARIOS = Literal[
    "normal",
    "member_not_found",
    "invalid_member_id",
    "no_matching_active_account",
    "permission_denied",
    "session_expiry",
    "slow_account_loading",
    "fail_once",
    "blocking_dialog",
]


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: SCENARIOS = "normal"
    epoch: str = "initial"
    delay_seconds: float = 2.0


def scenario() -> Scenario:
    path = Path(os.environ.get("BANK_SCENARIO_FILE", "var/scenario.json"))
    return (
        Scenario.model_validate_json(path.read_text()) if path.exists() else Scenario()
    )


def set_scenario(name: str, path: str | None = None):
    s = Scenario(name=name, epoch=secrets.token_hex(8))
    dest = Path(path or os.environ.get("BANK_SCENARIO_FILE", "var/scenario.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".tmp")
    temp.write_text(s.model_dump_json(indent=2))
    temp.replace(dest)


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["money"] = money
consumed: set[tuple[str, str, int]] = set()


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_session(request):
    with connect() as con:
        return con.execute(
            "SELECT s.*, u.username,u.role,u.branch FROM sessions s LEFT JOIN staff_users u ON u.id=s.staff_id WHERE token_hash=? AND expires_at>?",
            (digest(request.cookies.get("bank_session", "")), int(time.time())),
        ).fetchone()


def new_session(staff_id=None):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with connect() as con:
        con.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)",
            (
                digest(token),
                staff_id,
                int(time.time()) + int(os.environ.get("BANK_SESSION_SECONDS", "900")),
                csrf,
            ),
        )
    return token, csrf


def attach_cookie(response, token):
    response.set_cookie(
        "bank_session",
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=900,
    )
    return response


def safe_destination(value):
    return (
        value
        if re.fullmatch(r"/ui/(?:search|members/[0-9]{5}|accounts/[0-9]+)", value)
        else "/ui/search"
    )


def render(request, screen, **context):
    return templates.TemplateResponse(
        request=request,
        name="content.html",
        context={"screen": screen, "staff": get_session(request), **context},
    )


@app.middleware("http")
async def security(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin", "")
        if origin != str(request.base_url).rstrip("/"):
            return HTMLResponse(
                "<h1>Permission denied</h1><p>Invalid request origin.</p>",
                status_code=403,
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/", response_class=HTMLResponse)
async def shell(request: Request):
    return templates.TemplateResponse(request=request, name="shell.html", context={})


@app.get("/ui/sign-in", response_class=HTMLResponse)
async def sign_in(request: Request, next: str = "/ui/search", expired: bool = False):
    sess = get_session(request)
    if sess and sess["staff_id"] and not expired:
        return RedirectResponse(safe_destination(next), status_code=303)
    token, csrf = new_session()
    return attach_cookie(
        render(
            request,
            "login",
            csrf=csrf,
            next=safe_destination(next),
            expired=expired,
            message="",
        ),
        token,
    )


@app.post("/ui/sign-in")
async def authenticate(request: Request):
    form = await request.form()
    sess = get_session(request)
    if not sess or not secrets.compare_digest(str(form.get("csrf", "")), sess["csrf"]):
        return render(
            request,
            "error",
            title="Permission denied",
            message="Sign-in form expired. Reload the sign-in page.",
        )
    with connect() as con:
        user = con.execute(
            "SELECT * FROM staff_users WHERE username=?", (form.get("username", ""),)
        ).fetchone()
        if not user or not password_matches(
            str(form.get("password", "")), user["password_hash"]
        ):
            return render(
                request,
                "login",
                csrf=sess["csrf"],
                next=safe_destination(str(form.get("next", ""))),
                expired=False,
                message="Invalid credentials. Check your staff username and password.",
            )
        con.execute("DELETE FROM sessions WHERE token_hash=?", (sess["token_hash"],))
        con.execute(
            "INSERT INTO audit_events(staff_id,action,resource) VALUES (?,?,?)",
            (user["id"], "sign_in", "staff_session"),
        )
    token, _ = new_session(user["id"])
    return attach_cookie(
        RedirectResponse(safe_destination(str(form.get("next", ""))), status_code=303),
        token,
    )


def require_staff(request):
    sess = get_session(request)
    if not sess or not sess["staff_id"]:
        from urllib.parse import urlencode

        return RedirectResponse(
            "/ui/sign-in?"
            + urlencode(
                {"next": safe_destination(request.url.path), "expired": "true"}
            ),
            status_code=303,
        )
    return None


@app.post("/ui/sign-out")
async def sign_out(request: Request):
    form = await request.form()
    sess = get_session(request)
    if sess and secrets.compare_digest(str(form.get("csrf", "")), sess["csrf"]):
        with connect() as con:
            con.execute(
                "DELETE FROM sessions WHERE token_hash=?", (sess["token_hash"],)
            )
    response = RedirectResponse("/ui/sign-in", status_code=303)
    response.delete_cookie("bank_session")
    return response


@app.get("/ui/search", response_class=HTMLResponse)
async def search(
    request: Request,
    member_id: str = "",
    name: str = "",
    page: int = 1,
    searched: str = "",
):
    denied = require_staff(request)
    if denied:
        return denied
    s = scenario()
    message = ""
    rows = []
    count = 0
    page = max(1, page)
    if searched:
        if (
            s.name == "invalid_member_id"
            or (member_id and not re.fullmatch(r"[0-9]{5}", member_id))
            or (not member_id and not name)
        ):
            message = "Invalid member ID. Enter exactly five digits, or search by name."
        else:
            with connect() as con:
                if member_id:
                    rows = con.execute(
                        "SELECT * FROM members WHERE id=?", (member_id,)
                    ).fetchall()
                    count = len(rows)
                else:
                    count = con.execute(
                        "SELECT count(*) FROM members WHERE display_name LIKE ?",
                        ("%" + name + "%",),
                    ).fetchone()[0]
                    rows = con.execute(
                        "SELECT * FROM members WHERE display_name LIKE ? ORDER BY id LIMIT 2 OFFSET ?",
                        ("%" + name + "%", (page - 1) * 2),
                    ).fetchall()
            if s.name == "member_not_found":
                rows = []
                count = 0
            if not rows:
                message = "Member not found. No records match your search."
    from urllib.parse import urlencode

    next_link = (
        "/ui/search?" + urlencode({"name": name, "searched": "1", "page": page + 1})
        if page * 2 < count
        else None
    )
    previous_link = (
        "/ui/search?" + urlencode({"name": name, "searched": "1", "page": page - 1})
        if page > 1
        else None
    )
    return render(
        request,
        "search",
        rows=rows,
        message=message,
        member_id=member_id,
        name=name,
        count=count,
        page=page,
        next_link=next_link,
        previous_link=previous_link,
        searched=searched,
    )


@app.get("/ui/members/{member_id}", response_class=HTMLResponse)
async def member(request: Request, member_id: str):
    denied = require_staff(request)
    if denied:
        return denied
    with connect() as con:
        row = con.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
        accounts = con.execute(
            "SELECT * FROM accounts WHERE member_id=? ORDER BY id", (member_id,)
        ).fetchall()
    if not row:
        return render(
            request,
            "error",
            title="Member not found",
            message="No records match your search.",
        )
    if scenario().name == "no_matching_active_account":
        accounts = []
    return render(request, "member", member=row, accounts=accounts)


@app.get("/ui/accounts/{account_id}", response_class=HTMLResponse)
async def account(request: Request, account_id: int):
    denied = require_staff(request)
    if denied:
        return denied
    sess = get_session(request)
    s = scenario()
    key = (s.epoch, s.name, sess["staff_id"])
    with connect() as con:
        a = con.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not a:
            return render(
                request,
                "error",
                title="Account not found",
                message="The account is unavailable.",
            )
        m = con.execute(
            "SELECT * FROM members WHERE id=?", (a["member_id"],)
        ).fetchone()
        holds = con.execute(
            "SELECT * FROM holds WHERE account_id=? AND active=1", (account_id,)
        ).fetchall()
        tx = con.execute(
            "SELECT * FROM transactions WHERE account_id=? ORDER BY id DESC",
            (account_id,),
        ).fetchall()
        if s.name == "permission_denied" or (
            a["restricted"] and sess["role"] != "Supervisor"
        ):
            return render(
                request,
                "error",
                title="Permission denied",
                message="Your staff role cannot access this account. Contact a supervisor.",
            )
        if s.name == "session_expiry" and key not in consumed:
            consumed.add(key)
            con.execute(
                "UPDATE sessions SET expires_at=0 WHERE token_hash=?",
                (sess["token_hash"],),
            )
            return RedirectResponse(
                f"/ui/sign-in?expired=true&next=/ui/accounts/{account_id}",
                status_code=303,
            )
        if s.name == "fail_once" and key not in consumed:
            consumed.add(key)
            return render(
                request,
                "error",
                title="Temporary application failure",
                message="Account service is temporarily unavailable. This read-only request can be retried.",
                retry=f"/ui/accounts/{account_id}",
            )
        if s.name == "blocking_dialog" and key not in consumed:
            consumed.add(key)
            return render(request, "dialog", destination=f"/ui/accounts/{account_id}")
        con.execute(
            "INSERT INTO audit_events(staff_id,action,resource) VALUES (?,?,?)",
            (sess["staff_id"], "view_account", str(account_id)),
        )
    if s.name == "slow_account_loading":
        await asyncio.sleep(min(max(s.delay_seconds, 0), 20))
    total = sum(h["amount_cents"] for h in holds)
    return render(
        request,
        "account",
        member=m,
        account=a,
        holds=holds,
        hold_total=total,
        available=a["current_cents"] - total,
        transactions=tx,
    )
