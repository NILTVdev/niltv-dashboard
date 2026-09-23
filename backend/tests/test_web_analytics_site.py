"""Functional tests for the multi-site web-analytics API.

Runs in CI against the seeded Postgres (migrations already applied). Verifies:
  - /api/health is public
  - the web-analytics endpoints require the X-API-Key
  - the `site` query param actually filters data per site (truebluetv vs niltv)
  - the default site is truebluetv (backwards compatible)
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import GA4DailySnapshot, GSCDailyTotal

client = TestClient(app)
AUTH = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env
NOW = datetime.now(tz=timezone.utc)


def _seed():
    """Reset the two web-analytics tables and insert one row per site."""
    db = SessionLocal()
    try:
        db.query(GA4DailySnapshot).delete()
        db.query(GSCDailyTotal).delete()
        db.add_all([
            GA4DailySnapshot(site="truebluetv", date=NOW, sessions=100, total_users=80, pageviews=200),
            GA4DailySnapshot(site="niltv", date=NOW, sessions=10, total_users=8, pageviews=20),
            GSCDailyTotal(site="truebluetv", date=NOW, clicks=50, impressions=500, ctr=0.1, position=3.0),
            GSCDailyTotal(site="niltv", date=NOW, clicks=5, impressions=50, ctr=0.1, position=4.0),
        ])
        db.commit()
    finally:
        db.close()


def test_health_is_public():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_protected_endpoint_requires_key():
    # Missing header -> 422 (required header); wrong key -> 401. Never 200.
    assert client.get("/api/web-analytics/gsc/summary").status_code in (401, 422)
    assert client.get("/api/web-analytics/gsc/summary",
                      headers={"X-API-Key": "wrong"}).status_code == 401


def test_ga4_filtered_by_site():
    _seed()
    tb = client.get("/api/web-analytics/ga4", params={"site": "truebluetv", "days": 3650}, headers=AUTH)
    nl = client.get("/api/web-analytics/ga4", params={"site": "niltv", "days": 3650}, headers=AUTH)
    assert tb.status_code == 200 and nl.status_code == 200
    assert [r["sessions"] for r in tb.json()] == [100]
    assert [r["sessions"] for r in nl.json()] == [10]


def test_gsc_summary_filtered_by_site():
    _seed()
    tb = client.get("/api/web-analytics/gsc/summary", params={"site": "truebluetv", "days": 3650}, headers=AUTH)
    nl = client.get("/api/web-analytics/gsc/summary", params={"site": "niltv", "days": 3650}, headers=AUTH)
    assert tb.json()["total_clicks"] == 50
    assert nl.json()["total_clicks"] == 5


def test_default_site_is_truebluetv():
    _seed()
    r = client.get("/api/web-analytics/ga4", params={"days": 3650}, headers=AUTH)
    assert [row["sessions"] for row in r.json()] == [100]
