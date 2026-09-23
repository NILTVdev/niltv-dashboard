"""Functional tests for the brand_accounts registry admin endpoints:
merged listing with pull health + campus-inference readiness, campus/flag
updates, and env-row protection. Runs in CI against the seeded Postgres.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import BrandAccount, BrandSnapshot

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
NOW = datetime(2026, 8, 11, 5, 0, tzinfo=timezone.utc)


def _seed():
    db = SessionLocal()
    try:
        db.query(BrandSnapshot).delete()
        db.query(BrandAccount).delete()
        db.add_all([
            # Campus channel whose nightly profile pull is failing (latest
            # snapshot has the empty username the error path writes), but
            # which succeeded once in the past.
            BrandAccount(account="chapelhilltv", username="chapelhilltv", ig_user_id="101",
                         access_token="tok", network_pull=True),
            BrandAccount(account="dorecitytv", username="dorecitytv", ig_user_id="102",
                         access_token="tok", campus="vanderbilt", network_pull=True),
            BrandAccount(account="pausedtv", username="pausedtv", ig_user_id="103",
                         access_token="tok", active=False),
        ])
        db.add_all([
            BrandSnapshot(account="chapelhilltv", pulled_at=NOW - timedelta(days=3),
                          username="chapelhilltv", followers=1000),
            BrandSnapshot(account="chapelhilltv", pulled_at=NOW, username="", followers=None),
            BrandSnapshot(account="dorecitytv", pulled_at=NOW, username="dorecitytv", followers=2000),
        ])
        db.commit()
    finally:
        db.close()


def test_accounts_requires_key():
    assert client.get("/api/brand/accounts").status_code in (401, 422)


def test_registry_health_and_campus_readiness():
    _seed()
    rows = {r["account"]: r for r in client.get("/api/brand/accounts", headers=AUTH).json()}

    chapel = rows["chapelhilltv"]
    assert chapel["health"] == "failing"          # latest attempt was the error snapshot
    assert chapel["last_pull_ok"] is not None     # but it worked 3 days ago
    assert chapel["campus_ready"] is False        # network channel without a campus
    assert chapel["source"] == "db" and chapel["own_token"] is True
    assert "access_token" not in chapel           # tokens never serialized

    dore = rows["dorecitytv"]
    assert dore["health"] == "ok"
    assert dore["campus"] == "vanderbilt" and dore["campus_ready"] is True

    assert rows["pausedtv"]["active"] is False
    assert rows["pausedtv"]["health"] == "no-data"
    assert rows["pausedtv"]["campus_ready"] is True   # not a network channel

    # The env fallback (@niltv from CI settings) shows up as an env row.
    assert rows["niltv"]["source"] == "env"


def test_update_campus_and_flags():
    _seed()
    r = client.post("/api/brand/accounts/chapelhilltv/update",
                    json={"campus": " UNC "}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["campus"] == "unc"            # normalized lowercase
    assert r.json()["campus_ready"] is True

    # Clearing re-opens the readiness gap for a network channel
    r = client.post("/api/brand/accounts/chapelhilltv/update",
                    json={"campus": None}, headers=AUTH)
    assert r.json()["campus"] is None and r.json()["campus_ready"] is False

    r = client.post("/api/brand/accounts/pausedtv/update",
                    json={"active": True, "notes": "resumed"}, headers=AUTH)
    assert r.json()["active"] is True and r.json()["notes"] == "resumed"


def test_update_rejects_unknown_and_env_rows():
    _seed()
    assert client.post("/api/brand/accounts/nope/update", json={"campus": "x"},
                       headers=AUTH).status_code == 404
    # @niltv exists only as an env fallback in CI — not editable until imported
    r = client.post("/api/brand/accounts/niltv/update", json={"campus": "x"}, headers=AUTH)
    assert r.status_code == 404
    assert "import-env" in r.json()["detail"]


def test_verify_unknown_account_404s():
    _seed()
    assert client.post("/api/brand/accounts/nope/verify", headers=AUTH).status_code == 404
