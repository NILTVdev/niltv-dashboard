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
from backend.models import BrandSnapshot, NiltvNetworkPost

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


def _seed_posts():
    # Clamped to the month start so a CI run in the first minutes of a UTC month
    # cannot seed these rows into the prior month.
    now = datetime.now(timezone.utc)
    published = max(now - timedelta(minutes=5), now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    db = SessionLocal()
    try:
        db.query(NiltvNetworkPost).delete()
        common = dict(account_username="niltv", collab_accounts="niltv", publish_time=published)
        db.add_all([
            NiltvNetworkPost(post_id="a", post_type="REELS", views=1000, likes=50, **common),
            NiltvNetworkPost(post_id="b", post_type="REELS", views=0, likes=0, **common),
            # Owner hides the count: views unknown, likes visible.
            NiltvNetworkPost(post_id="c", post_type="REELS", views=None, likes=900, **common),
            NiltvNetworkPost(post_id="d", post_type="IMAGE", views=None, likes=10, **common),
        ])
        db.commit()
    finally:
        db.close()


def _clear_posts():
    db = SessionLocal()
    try:
        db.query(NiltvNetworkPost).delete()
        db.commit()
    finally:
        db.close()


def test_averages_and_rates_leave_out_posts_with_no_views():
    _seed()
    _seed_posts()
    try:
        cur = _instagram("month")["current_month"]
    finally:
        _clear_posts()

    assert cur["posts_monthly"] == 4
    assert cur["posts_with_views_monthly"] == 2
    assert cur["total_views_monthly"] == 1000
    # A real 0 counts toward the average; unknown views do not.
    assert cur["avg_views_per_post"] == 500.0
    # Only the likes of posts with views: 50 / 1000, not (50 + 900 + 10) / 1000.
    assert cur["engagement_rate_overall"] == 5.0

    reels = cur["format_breakdown"]["REELS"]
    assert (reels["posts"], reels["posts_with_views"], reels["avg_views"]) == (3, 2, 500.0)
    assert reels["engagement_rate"] == 5.0

    images = cur["format_breakdown"]["IMAGE"]
    assert (images["posts"], images["posts_with_views"], images["avg_views"]) == (1, 0, 0.0)
    assert images["engagement_rate"] is None
