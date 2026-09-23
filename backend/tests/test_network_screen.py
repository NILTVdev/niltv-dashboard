"""Regression tests for /api/network-screen/summary follower math.

Failed pulls write sentinel brand_snapshots rows with followers=NULL
(run_brand_ig's error path). Those rows must never be picked as a
baseline: `followers or 0` would coerce the NULL to 0 and report the
entire follower count as "new" on the Channel Insights screen.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import BrandSnapshot

client = TestClient(app)
AUTH = {"X-API-Key": "test"}


def _seed():
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    db = SessionLocal()
    try:
        db.query(BrandSnapshot).delete()
        db.add_all([
            # Last real count before the current month started.
            BrandSnapshot(account="niltv", username="niltv",
                          pulled_at=month_start - timedelta(days=40), followers=100),
            # Failed-pull sentinel right at the month boundary — the row the
            # error path writes (empty username, NULL followers).
            BrandSnapshot(account="niltv", username="",
                          pulled_at=month_start - timedelta(hours=1), followers=None),
            # Current count. Clamped to month_start so a CI run in the first
            # minutes of a UTC month cannot seed this row into the prior month.
            BrandSnapshot(account="niltv", username="niltv",
                          pulled_at=max(now - timedelta(minutes=5), month_start),
                          followers=150),
        ])
        db.commit()
    finally:
        db.close()


def _instagram(mode: str) -> dict:
    r = client.get(f"/api/network-screen/summary?mode={mode}", headers=AUTH)
    assert r.status_code == 200
    return next(p for p in r.json()["platforms"] if p["platform"] == "instagram")


def test_summary_requires_key():
    assert client.get("/api/network-screen/summary").status_code in (401, 422)


def test_null_sentinel_is_not_a_zero_baseline():
    _seed()
    cur = _instagram("month")["current_month"]
    assert cur["followers"] == 150
    # Baseline must be the last REAL count (100), not the sentinel's NULL
    # coerced to 0 — which would report all 150 followers as new.
    assert cur["new_followers_monthly"] == 50


def test_prior_month_lands_on_last_real_count():
    _seed()
    prior = _instagram("month")["prior_month"]
    # The only real snapshot before the current month is the 100 row, and it
    # also precedes the prior month's start, so the prior column reads a flat
    # 100 followers with a 0 delta — never the full count.
    assert prior["followers"] == 100
    assert prior["new_followers_monthly"] == 0


def test_prevmonth_mode_shows_last_complete_month():
    _seed()
    ig = _instagram("prevmonth")
    # Primary column is the last COMPLETE month: its follower count is the
    # 100 row (the only real snapshot before the current month started).
    cur = ig["current_month"]
    assert cur["followers"] == 100
    assert cur["new_followers_monthly"] == 0
