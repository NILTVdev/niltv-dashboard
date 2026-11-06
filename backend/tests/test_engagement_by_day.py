"""/api/posts/athletes/{id}/engagement-by-day returns gains, not running totals.

The Player Details likes chart adds these values up for its Cumulative view, so
each value must be that day's change or the chart multiplies the athlete's
total by the number of snapshot days.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import Athlete, AthletePost, AthletePostSnapshot

client = TestClient(app)
AUTH = {"X-API-Key": "test"}


def _day(n: int) -> datetime:
    return datetime(2026, 10, n, 2, 0, tzinfo=timezone.utc)


def _engagement(history: dict[str, list[tuple[int, int | None, int | None]]]) -> list[dict]:
    """history maps a post id to (day, likes, comments) snapshots."""
    db = SessionLocal()
    athlete = Athlete(name="Test Athlete", ig_handle="engagement_by_day_test")
    db.add(athlete)
    db.flush()
    try:
        for ig_post_id, snapshots in history.items():
            post = AthletePost(athlete_id=athlete.id, ig_post_id=ig_post_id)
            db.add(post)
            db.flush()
            db.add_all(
                AthletePostSnapshot(post_id=post.id, captured_at=_day(day), like_count=likes, comment_count=comments)
                for day, likes, comments in snapshots
            )
        db.commit()
        r = client.get(f"/api/posts/athletes/{athlete.id}/engagement-by-day", headers=AUTH)
        assert r.status_code == 200
        return r.json()
    finally:
        db.delete(athlete)
        db.commit()
        db.close()


def test_days_add_up_to_the_current_total():
    rows = _engagement({"p1": [(1, 100, 5), (2, 110, 6), (3, 125, 6)]})
    assert rows == [
        {"date": "2026-10-01", "likes": 100, "comments": 5},
        {"date": "2026-10-02", "likes": 10, "comments": 1},
        {"date": "2026-10-03", "likes": 15, "comments": 0},
    ]
    assert sum(r["likes"] for r in rows) == 125


def test_a_post_leaving_the_pull_is_not_a_loss():
    rows = _engagement({
        "old": [(1, 1000, 0), (2, 1000, 0)],
        "new": [(2, 10, 0), (3, 30, 0)],
    })
    assert [r["likes"] for r in rows] == [1000, 10, 20]


def test_hidden_counts_keep_the_last_known_value():
    rows = _engagement({
        "null": [(1, 200, 1), (2, None, 1), (3, 210, 1)],
        "zero": [(1, 50, 1), (2, 0, 1), (3, 55, 1)],
    })
    assert [r["likes"] for r in rows] == [250, 0, 15]


def test_a_post_that_starts_at_zero_still_counts_later_gains():
    assert [r["likes"] for r in _engagement({"p": [(1, 0, 0), (2, 4, 0)]})] == [0, 4]


def test_unlikes_lower_the_day():
    assert [r["likes"] for r in _engagement({"p": [(1, 100, 0), (2, 97, 0)]})] == [100, -3]
