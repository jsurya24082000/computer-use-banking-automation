import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from banking_app.db import seed
from banking_app.app import set_scenario
from automation.models import Inputs, Tenant, RuntimeConfig
from automation.policy import PolicyConfig


@pytest.fixture(scope="session")
def bank_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("bank")
    db = root / "bank.sqlite3"
    scenario = root / "scenario.json"
    seed(db)
    set_scenario("normal", str(scenario))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "BANK_DB": str(db), "BANK_SCENARIO_FILE": str(scenario)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "banking_app.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(origin, trust_env=False).status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.05)
    else:
        proc.terminate()
        raise RuntimeError("Test bank did not start")
    yield {"origin": origin, "db": db, "scenario": scenario}
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def bank(bank_server, tmp_path):
    set_scenario("normal", str(bank_server["scenario"]))
    return {
        **bank_server,
        "tenant": Tenant(entry_url=bank_server["origin"] + "/"),
        "policy": PolicyConfig(allowed_origins=[bank_server["origin"]]),
        "config": RuntimeConfig(evidence_dir=str(tmp_path / "evidence")),
    }


@pytest.fixture
def inputs():
    return Inputs(
        member_id="10001",
        product_name="Primary Savings",
        staff_username="teller",
        staff_password="DemoBank!2026",
    )
