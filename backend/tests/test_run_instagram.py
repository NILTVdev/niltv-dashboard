"""run_instagram writes one short transaction per fetched athlete and survives a
deadlock on one of them. A single long transaction can deadlock with
run_zoomph's precompute and roll back every athlete's snapshot.

Also: the registry hides token stamps on rows that ride on the shared portfolio
token, so a leftover onboarding stamp can no longer read as a real expiry.
Runs in CI against the seeded Postgres.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from psycopg2.errors import DeadlockDetected
from sqlalchemy.exc import OperationalError

from backend.database import SessionLocal
from backend.jobs import run_instagram as job
from backend.main import app
from backend.models import Athlete, AthletePost, AthletePostSnapshot, AthleteSnapshot, BrandAccount, BrandSnapshot
from backend.sources.instagram import IGPost, IGProfile

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
HANDLES = ["ig_dl_alpha", "ig_dl_bravo", "ig_dl_charlie"]
_parked: list[int] = []   # other active athletes set inactive for the run, restored by _clean


def _clean(db):
    ids = [a.id for a in db.query(Athlete).filter(Athlete.ig_handle.in_(HANDLES)).all()]
    if ids:
        post_ids = [p.id for p in db.query(AthletePost).filter(AthletePost.athlete_id.in_(ids)).all()]
        if post_ids:
            db.query(AthletePostSnapshot).filter(AthletePostSnapshot.post_id.in_(post_ids)).delete(synchronize_session=False)
        db.query(AthletePost).filter(AthletePost.athlete_id.in_(ids)).delete(synchronize_session=False)
        db.query(AthleteSnapshot).filter(AthleteSnapshot.athlete_id.in_(ids)).delete(synchronize_session=False)
        db.query(Athlete).filter(Athlete.id.in_(ids)).delete(synchronize_session=False)
    if _parked:
        db.query(Athlete).filter(Athlete.id.in_(_parked)).update({"active": True}, synchronize_session=False)
        _parked.clear()
    db.commit()


def _seed(db):
    _clean(db)
    # Every other active athlete is parked so the job only walks these three.
    others = db.query(Athlete).filter(Athlete.active == True).all()  # noqa: E712
    _parked.extend(a.id for a in others)
    if _parked:
        db.query(Athlete).filter(Athlete.id.in_(_parked)).update({"active": False}, synchronize_session=False)
    db.add_all([Athlete(name=f"Test {h}", ig_handle=h, active=True) for h in HANDLES])
    db.commit()


def _profile(handle: str) -> IGProfile:
    return IGProfile(username=handle, ig_user_id=f"id-{handle}", followers=1234, post_count=1, bio="bio",
                     posts=[IGPost(ig_post_id=f"post-{handle}", posted_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                                   media_type="IMAGE", like_count=10, comment_count=2,
                                   permalink=f"https://www.instagram.com/p/{handle}/", caption="c", media_url=None)])


def _deadlock() -> OperationalError:
    return OperationalError("UPDATE athletes ...", {}, DeadlockDetected("deadlock detected"))


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(job, "fetch_ig_profile", lambda handle: _profile(handle))
    monkeypatch.setattr(job.time, "sleep", lambda *_: None)
    monkeypatch.setattr(job, "upload_to_s3", lambda *_a, **_k: "skipped")


def test_every_fetched_athlete_commits_on_its_own(quiet, monkeypatch):
    db = SessionLocal()
    try:
        _seed(db)
        real_commit = db.commit
        commits = []
        monkeypatch.setattr(db, "commit", lambda: (commits.append(1), real_commit())[1])

        assert job._pull_instagram(db) == 3                      # three new posts

        assert len(commits) >= 3                                  # one per athlete at least
        for h in HANDLES:
            a = db.query(Athlete).filter_by(ig_handle=h).one()
            assert a.ig_checked_at is not None and a.ig_accessible is True and a.ig_user_id == f"id-{h}"
            assert db.query(AthleteSnapshot).filter_by(athlete_id=a.id).count() == 1
            post = db.query(AthletePost).filter_by(ig_post_id=f"post-{h}").one()
            assert db.query(AthletePostSnapshot).filter_by(post_id=post.id).count() == 1
    finally:
        monkeypatch.undo()          # restore the real commit before cleanup
        db.rollback()
        _clean(db)
        db.close()


def test_a_deadlock_on_one_athlete_is_retried_and_loses_nothing(quiet, monkeypatch):
    db = SessionLocal()
    try:
        _seed(db)
        real_commit = db.commit
        state = {"n": 0}

        def flaky_commit():
            state["n"] += 1
            if state["n"] == 2:                                   # second athlete's first commit
                raise _deadlock()
            real_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)
        monkeypatch.setattr(job, "DEADLOCK_RETRY_PAUSE", (0, 0))

        assert job._pull_instagram(db) == 3

        for h in HANDLES:
            a = db.query(Athlete).filter_by(ig_handle=h).one()
            assert a.ig_checked_at is not None
            # exactly one snapshot each: the rolled-back attempt left no duplicate
            assert db.query(AthleteSnapshot).filter_by(athlete_id=a.id).count() == 1
            assert db.query(AthletePost).filter_by(ig_post_id=f"post-{h}").count() == 1
    finally:
        monkeypatch.undo()          # restore the real commit before cleanup
        db.rollback()
        _clean(db)
        db.close()


def test_a_persistent_deadlock_still_fails_the_job(quiet, monkeypatch):
    db = SessionLocal()
    try:
        _seed(db)
        real_commit = db.commit
        state = {"n": 0}

        def stuck_commit():
            state["n"] += 1
            if state["n"] >= 2:
                raise _deadlock()
            real_commit()

        monkeypatch.setattr(db, "commit", stuck_commit)
        monkeypatch.setattr(job, "DEADLOCK_RETRY_PAUSE", (0, 0))
        with pytest.raises(OperationalError):
            job._pull_instagram(db)
        db.rollback()
        # the first athlete's own transaction is intact
        first = db.query(Athlete).filter_by(ig_handle=HANDLES[0]).one()
        assert db.query(AthleteSnapshot).filter_by(athlete_id=first.id).count() == 1
    finally:
        monkeypatch.undo()          # restore the real commit before cleanup
        db.rollback()
        _clean(db)
        db.close()


def test_registry_hides_token_stamps_on_shared_token_rows():
    db = SessionLocal()
    try:
        db.query(BrandSnapshot).delete()
        db.query(BrandAccount).delete()
        stamp = datetime(2026, 10, 18, tzinfo=timezone.utc)
        db.add_all([
            # rides on the shared BRAND_IG_ACCESS_TOKEN grant, leftover onboarding stamp
            BrandAccount(account="sharedtv", username="sharedtv", ig_user_id="1", access_token=None,
                         token_expires_at=stamp, token_refreshed_at=stamp - timedelta(days=60)),
            BrandAccount(account="owntv", username="owntv", ig_user_id="2", access_token="tok",
                         token_expires_at=stamp, token_refreshed_at=stamp - timedelta(days=60)),
        ])
        db.commit()
        rows = {r["account"]: r for r in client.get("/api/brand/accounts", headers=AUTH).json()}
        assert rows["sharedtv"]["own_token"] is False
        assert rows["sharedtv"]["token_expires_at"] is None and rows["sharedtv"]["token_refreshed_at"] is None
        assert rows["owntv"]["own_token"] is True and rows["owntv"]["token_expires_at"].startswith("2026-10-18")
    finally:
        db.query(BrandAccount).filter(BrandAccount.account.in_(["sharedtv", "owntv"])).delete(synchronize_session=False)
        db.commit()
        db.close()
