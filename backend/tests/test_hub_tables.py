"""Schema tests for the Athlete Content Hub tables (migration 030).

Runs against the seeded Postgres like the other functional tests. Covers the
rules the schema itself enforces: one claim row per athlete per ask, the
spot-limit and status checks, cascading deletes, and the one-row-per-link
submission history.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from backend.database import SessionLocal
from backend.models import Application, HubAsk, HubClaim, HubSubmission

EMAIL = "hub.tester@example.com"


def _clean(db):
    db.query(HubAsk).filter(HubAsk.created_by == "pytest").delete()
    db.query(Application).filter(Application.email == EMAIL).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    session.rollback()
    _clean(session)
    session.close()


@pytest.fixture()
def athlete(db):
    app = Application(email=EMAIL, first_name="Test", last_name="Athlete", status="accepted")
    db.add(app)
    db.commit()
    return app


def _ask(db, **kw):
    fields = dict(title="Training Table Trivia", category="Trivia", summary="Quiz a teammate.",
                  steps=["Film vertical", "Post as a collab"], due_on=date(2026, 11, 14),
                  slots=None, created_by="pytest")
    fields.update(kw)
    ask = HubAsk(**fields)
    db.add(ask)
    db.commit()
    return ask


def test_ask_defaults(db):
    ask = _ask(db)
    db.refresh(ask)
    assert ask.status == "open"
    assert ask.steps == ["Film vertical", "Post as a collab"]
    assert ask.slots is None
    assert ask.created_at is not None
    assert ask.closed_at is None


def test_slots_must_be_positive(db):
    with pytest.raises(IntegrityError):
        _ask(db, slots=0)
    db.rollback()
    _ask(db, slots=1)   # the single-athlete case is allowed


def test_status_is_checked(db):
    with pytest.raises(IntegrityError):
        _ask(db, status="live")
    db.rollback()


def test_one_claim_row_per_athlete_per_ask(db, athlete):
    ask = _ask(db)
    db.add(HubClaim(ask_id=ask.id, application_id=athlete.id, account_sub="sub-1"))
    db.commit()
    db.add(HubClaim(ask_id=ask.id, application_id=athlete.id, account_sub="sub-1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_release_and_reclaim_reuse_the_row(db, athlete):
    ask = _ask(db)
    claim = HubClaim(ask_id=ask.id, application_id=athlete.id)
    db.add(claim)
    db.commit()
    db.refresh(claim)
    assert claim.status == "claimed"
    claim.status = "released"
    claim.released_at = datetime.now(tz=timezone.utc)
    db.commit()
    claim.status = "claimed"
    claim.released_at = None
    db.commit()
    assert db.query(HubClaim).filter(HubClaim.ask_id == ask.id).count() == 1


def test_submissions_keep_history(db, athlete):
    ask = _ask(db)
    claim = HubClaim(ask_id=ask.id, application_id=athlete.id)
    db.add(claim)
    db.commit()
    first = HubSubmission(claim_id=claim.id, url="https://instagram.com/reel/one", note="first cut")
    db.add(first)
    db.commit()
    first.replaced_at = datetime.now(tz=timezone.utc)
    db.add(HubSubmission(claim_id=claim.id, url="https://instagram.com/reel/two"))
    claim.status = "submitted"
    claim.submitted_at = datetime.now(tz=timezone.utc)
    db.commit()
    db.refresh(claim)
    assert [s.url for s in claim.submissions] == ["https://instagram.com/reel/one", "https://instagram.com/reel/two"]
    current = [s for s in claim.submissions if s.replaced_at is None]
    assert [s.url for s in current] == ["https://instagram.com/reel/two"]


def test_deleting_an_ask_removes_its_claims_and_links(db, athlete):
    ask = _ask(db)
    claim = HubClaim(ask_id=ask.id, application_id=athlete.id)
    db.add(claim)
    db.commit()
    db.add(HubSubmission(claim_id=claim.id, url="https://instagram.com/reel/x"))
    db.commit()
    claim_id = claim.id
    db.delete(ask)
    db.commit()
    assert db.query(HubClaim).filter(HubClaim.id == claim_id).count() == 0
    assert db.query(HubSubmission).filter(HubSubmission.claim_id == claim_id).count() == 0


def test_deleting_the_athlete_removes_their_claims(db, athlete):
    ask = _ask(db)
    db.add(HubClaim(ask_id=ask.id, application_id=athlete.id))
    db.commit()
    db.delete(athlete)
    db.commit()
    assert db.query(HubClaim).filter(HubClaim.ask_id == ask.id).count() == 0
    assert db.query(HubAsk).filter(HubAsk.id == ask.id).count() == 1   # the ask itself stays
