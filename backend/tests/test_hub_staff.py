"""Staff side of the Athlete Content Hub: /api/hub (backend/routers/hub.py).

Runs against the seeded Postgres like the other functional tests. Covers
posting an ask, the counts and spots left on the list, the per-ask claim
board, the approval queue and approving, closing an ask, and that only
admin accounts may use it.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import Application, DashboardUser, HubAsk, HubClaim, HubSubmission

client = TestClient(app)
KEY = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env
EMAILS = ("hub.one@example.com", "hub.two@example.com")
STAFF = ("hub.admin@example.com", "hub.general@example.com")
TITLE_PREFIX = "pytest hub "


def _clean(db):
    db.query(HubAsk).filter(HubAsk.title.like(TITLE_PREFIX + "%")).delete(synchronize_session=False)
    db.query(Application).filter(Application.email.in_(EMAILS)).delete(synchronize_session=False)
    db.query(DashboardUser).filter(DashboardUser.email.in_(STAFF)).delete(synchronize_session=False)
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
def athletes(db):
    apps = [
        Application(email=EMAILS[0], first_name="Ann", last_name="One", university="Duke University",
                    sport="Lacrosse", status="accepted"),
        Application(email=EMAILS[1], first_name="Bo", last_name="Two", university="Duke University",
                    sport="Soccer", status="accepted"),
    ]
    db.add_all(apps)
    db.commit()
    return apps


def _staff(db, email, role):
    u = DashboardUser(email=email, name=email.split("@")[0], role=role, password_hash="x")
    db.add(u)
    db.commit()
    return u


def _as(user):
    return {**KEY, "X-Dashboard-User": str(user.id), "X-Dashboard-Session-Version": str(user.session_version or 1)}


def _post_ask(headers=KEY, **kw):
    body = {"title": TITLE_PREFIX + "trivia", "category": "Trivia", "format": "Reel",
            "tags": ["Football", " lifestyle ", "football"], "summary": "Quiz a teammate.",
            "steps": ["Film vertical", "  ", "Post as a collab"], "due_on": "2026-11-14", "slots": 2}
    body.update(kw)
    return client.post("/api/hub/asks", json=body, headers=headers)


def _claim(db, ask_id, app, status="claimed", link=None):
    claim = HubClaim(ask_id=ask_id, application_id=app.id, status=status)
    db.add(claim)
    db.commit()
    if link:
        db.add(HubSubmission(claim_id=claim.id, url=link))
        claim.submitted_at = datetime.now(tz=timezone.utc)
        db.commit()
    return claim


def test_post_an_ask(db):
    r = _post_ask()
    assert r.status_code == 201, r.text
    ask = r.json()
    assert ask["status"] == "open"
    assert ask["format"] == "Reel"
    assert ask["tags"] == ["football", "lifestyle"]
    assert ask["steps"] == ["Film vertical", "Post as a collab"]
    assert ask["spots_left"] == 2
    assert ask["created_by"] == "staff"   # service caller; an account records its email


def test_post_an_ask_is_validated(db):
    assert _post_ask(title="   ").status_code == 422
    assert _post_ask(slots=0).status_code == 422
    assert _post_ask(status="closed").status_code == 422


def test_list_counts_and_spots_left(db, athletes):
    ask_id = _post_ask().json()["id"]
    _claim(db, ask_id, athletes[0], status="submitted", link="https://instagram.com/reel/a")
    _claim(db, ask_id, athletes[1], status="released")
    r = client.get("/api/hub/asks", headers=KEY)
    assert r.status_code == 200
    row = next(a for a in r.json() if a["id"] == ask_id)
    assert (row["claimed"], row["submitted"], row["approved"]) == (0, 1, 0)
    assert row["spots_left"] == 1   # the released claim gave its spot back


def test_list_filters_by_tag_and_status(db):
    a = _post_ask(tags=["podcast"]).json()["id"]
    b = _post_ask(title=TITLE_PREFIX + "draft", tags=["lifestyle"], status="draft").json()["id"]
    ids = lambda r: {x["id"] for x in r.json()}
    assert a in ids(client.get("/api/hub/asks?tag=Podcast", headers=KEY))
    assert b not in ids(client.get("/api/hub/asks?tag=podcast", headers=KEY))
    assert ids(client.get("/api/hub/asks?status=draft", headers=KEY)) >= {b}
    assert a not in ids(client.get("/api/hub/asks?status=draft", headers=KEY))
    assert client.get("/api/hub/asks?status=live", headers=KEY).status_code == 400


def test_ask_detail_shows_who_claimed_and_their_link(db, athletes):
    ask_id = _post_ask().json()["id"]
    _claim(db, ask_id, athletes[0], status="submitted", link="https://instagram.com/reel/a")
    _claim(db, ask_id, athletes[1])
    r = client.get(f"/api/hub/asks/{ask_id}", headers=KEY)
    assert r.status_code == 200
    claims = r.json()["claims"]
    assert [(c["athlete_name"], c["status"], c["link"]) for c in claims] == [
        ("Ann One", "submitted", "https://instagram.com/reel/a"),
        ("Bo Two", "claimed", None),
    ]
    assert client.get("/api/hub/asks/999999", headers=KEY).status_code == 404


def test_approval_queue_and_approve(db, athletes):
    admin = _staff(db, STAFF[0], "admin")
    ask_id = _post_ask().json()["id"]
    claim = _claim(db, ask_id, athletes[0], status="submitted", link="https://instagram.com/reel/a")
    queue = client.get("/api/hub/claims", headers=KEY).json()
    assert claim.id in [c["id"] for c in queue]

    r = client.post(f"/api/hub/claims/{claim.id}/approve", headers=_as(admin))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["reviewed_by"] == admin.id
    assert claim.id not in [c["id"] for c in client.get("/api/hub/claims", headers=KEY).json()]
    # approving twice, or a claim with nothing submitted, is refused
    assert client.post(f"/api/hub/claims/{claim.id}/approve", headers=KEY).status_code == 409
    other = _claim(db, ask_id, athletes[1])
    assert client.post(f"/api/hub/claims/{other.id}/approve", headers=KEY).status_code == 409
    assert client.post("/api/hub/claims/999999/approve", headers=KEY).status_code == 404


def test_close_an_ask(db):
    ask_id = _post_ask().json()["id"]
    r = client.post(f"/api/hub/asks/{ask_id}/close", headers=KEY)
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert r.json()["closed_at"] is not None
    assert ask_id not in [a["id"] for a in client.get("/api/hub/asks", headers=KEY).json()]


def test_only_admin_accounts_may_use_the_hub(db):
    general = _staff(db, STAFF[1], "general")
    assert client.get("/api/hub/asks").status_code == 401
    assert client.get("/api/hub/asks", headers=_as(general)).status_code == 403
    assert _post_ask(headers=_as(general)).status_code == 403
