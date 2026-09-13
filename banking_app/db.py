"""SQLite is private to the app and independent test harness."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

AS_OF = "2026-09-13T12:00:00Z"


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 260_000
    )
    return f"pbkdf2_sha256$260000${salt}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    _, _, salt, _ = stored.split("$")
    return hmac.compare_digest(password_hash(password, salt), stored)


@contextmanager
def connect(path: str | Path | None = None):
    path = Path(path or os.environ.get("BANK_DB", "var/bank.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def seed(path: str | Path | None = None):
    with connect(path) as con:
        con.executescript("""
        DROP TABLE IF EXISTS audit_events;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS holds;
        DROP TABLE IF EXISTS accounts;
        DROP TABLE IF EXISTS members;
        DROP TABLE IF EXISTS staff_users;
        CREATE TABLE members(id TEXT PRIMARY KEY, display_name TEXT NOT NULL, city TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id), product TEXT NOT NULL,
          last_four TEXT NOT NULL, status TEXT NOT NULL, currency TEXT NOT NULL, current_cents INTEGER NOT NULL,
          restricted INTEGER NOT NULL DEFAULT 0, as_of TEXT NOT NULL);
        CREATE TABLE holds(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
          amount_cents INTEGER NOT NULL CHECK(amount_cents>=0), active INTEGER NOT NULL, description TEXT NOT NULL);
        CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
          posted_at TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL, balance_cents INTEGER NOT NULL);
        CREATE TABLE staff_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
          role TEXT NOT NULL, branch TEXT NOT NULL);
        CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, staff_id INTEGER REFERENCES staff_users(id),
          expires_at INTEGER NOT NULL, csrf TEXT NOT NULL);
        CREATE TABLE audit_events(id INTEGER PRIMARY KEY, happened_at TEXT DEFAULT CURRENT_TIMESTAMP,
          staff_id INTEGER, action TEXT NOT NULL, resource TEXT NOT NULL);
        """)
        names = [
            "Mira Rowan",
            "Ellis Vale",
            "Ellis Vale",
            "Nora Finch",
            "Arlo Reed",
            "Isla Brook",
            "Theo Linden",
            "Lena Moss",
            "Owen Cove",
            "Ava Field",
        ]
        con.executemany(
            "INSERT INTO members VALUES (?,?,?,?)",
            [
                (str(10001 + i), n, "Maple Harbor", "Active")
                for i, n in enumerate(names)
            ],
        )
        accounts = [
            (1, "10001", "Primary Savings", "4102", "Active", 425075, 0),
            (2, "10001", "Everyday Checking", "8821", "Active", 184020, 0),
            (3, "10001", "Holiday Savings", "1934", "Closed", 0, 0),
            (4, "10002", "Primary Savings", "5210", "Active", 912345, 0),
            (5, "10003", "Primary Savings", "3010", "Active", 67000, 0),
            (6, "10004", "Primary Savings", "4410", "Active", 125000, 0),
            (7, "10004", "Education Savings", "4411", "Active", 700000, 0),
            (8, "10005", "Everyday Checking", "5510", "Active", 80000, 0),
            (9, "10006", "Primary Savings", "6610", "Closed", 0, 0),
            (10, "10007", "Primary Savings", "7710", "Active", 180000, 1),
            (11, "10008", "Primary Savings", "8810", "Active", 72000, 0),
            (12, "10009", "Primary Savings", "9910", "Active", 86000, 0),
            (13, "10010", "Primary Savings", "1010", "Active", 94000, 0),
        ]
        for a in accounts:
            aid, mid, product, last, status, cents, restricted = a
            con.execute(
                "INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, mid, product, last, status, "USD", cents, restricted, AS_OF),
            )
            opening = max(0, cents - 15000)
            con.execute(
                "INSERT INTO transactions(account_id,posted_at,description,amount_cents,balance_cents) VALUES (?,?,?,?,?)",
                (aid, "2026-09-10", "Opening ledger balance", opening, opening),
            )
            if cents:
                con.execute(
                    "INSERT INTO transactions(account_id,posted_at,description,amount_cents,balance_cents) VALUES (?,?,?,?,?)",
                    (
                        aid,
                        "2026-09-12",
                        "Synthetic payroll credit",
                        cents - opening,
                        cents,
                    ),
                )
        con.execute("INSERT INTO holds VALUES (1,1,25000,1,'Pending synthetic debit')")
        con.execute("INSERT INTO holds VALUES (2,4,12345,1,'Pending synthetic debit')")
        con.execute("INSERT INTO holds VALUES (3,1,1000,0,'Released hold')")
        for i, user, role in [(1, "teller", "Teller"), (2, "supervisor", "Supervisor")]:
            con.execute(
                "INSERT INTO staff_users VALUES (?,?,?,?,?)",
                (i, user, password_hash("DemoBank!2026"), role, "Maple Harbor"),
            )


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100:,}.{abs(cents) % 100:02d}"
