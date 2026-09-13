import re
import httpx
from banking_app.db import connect, password_matches, seed


def test_seed_consistency_and_hashed_passwords(tmp_path):
    db = tmp_path / "bank.sqlite3"
    seed(db)
    with connect(db) as con:
        assert con.execute("SELECT count(*) FROM members").fetchone()[0] == 10
        member = con.execute(
            "SELECT current_cents FROM accounts WHERE id=1"
        ).fetchone()[0]
        holds = con.execute(
            "SELECT sum(amount_cents) FROM holds WHERE account_id=1 AND active=1"
        ).fetchone()[0]
        assert (member, holds, member - holds) == (425075, 25000, 400075)
        stored = con.execute(
            "SELECT password_hash FROM staff_users WHERE username='teller'"
        ).fetchone()[0]
        assert "DemoBank!2026" not in stored
        assert password_matches("DemoBank!2026", stored)
        assert not password_matches("wrong", stored)
        for account in con.execute("SELECT id,current_cents FROM accounts"):
            tx = con.execute(
                "SELECT sum(amount_cents) FROM transactions WHERE account_id=?",
                (account["id"],),
            ).fetchone()[0]
            assert tx == account["current_cents"]


def login(client):
    response = client.get("/ui/sign-in")
    csrf = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
    return client.post(
        "/ui/sign-in",
        data={
            "username": "teller",
            "password": "DemoBank!2026",
            "csrf": csrf,
            "next": "/ui/search",
        },
        headers={"Origin": str(client.base_url).rstrip("/")},
    )


def test_app_auth_and_server_side_expiry(bank):
    # Direct HTTP/database access is confined to the independent test harness.
    with httpx.Client(
        base_url=bank["origin"], trust_env=False, follow_redirects=True
    ) as client:
        assert "Staff sign-in" in client.get("/ui/accounts/1").text
        assert "Member search" in login(client).text
        assert "Account details" in client.get("/ui/accounts/1").text
        with connect(bank["db"]) as con:
            con.execute("UPDATE sessions SET expires_at=0")
        response = client.get("/ui/accounts/1")
        assert "Session expired." in response.text
        assert 'name="next" value="/ui/accounts/1"' in response.text


def test_name_search_duplicates_and_pagination(bank):
    with httpx.Client(
        base_url=bank["origin"], trust_env=False, follow_redirects=True
    ) as client:
        login(client)
        page = client.get(
            "/ui/search", params={"name": "Ellis Vale", "searched": "1"}
        ).text
        assert "10002" in page and "10003" in page
        page = client.get("/ui/search", params={"name": "a", "searched": "1"}).text
        assert "Next page" in page
        page2 = client.get(
            "/ui/search", params={"name": "a", "searched": "1", "page": 2}
        ).text
        assert "Previous page" in page2


def test_csrf_and_permission_denial(bank):
    with httpx.Client(
        base_url=bank["origin"], trust_env=False, follow_redirects=True
    ) as client:
        assert client.post("/ui/sign-in", data={}).status_code == 403
        login(client)
        response = client.get("/ui/accounts/10")
        assert "Permission denied" in response.text
        assert "Current balance" not in response.text


def test_sign_in_destination_is_local_allowlist(bank):
    with httpx.Client(base_url=bank["origin"], trust_env=False) as client:
        response = client.get("/ui/sign-in", params={"next": "https://outside.example"})
        assert 'name="next" value="/ui/search"' in response.text
