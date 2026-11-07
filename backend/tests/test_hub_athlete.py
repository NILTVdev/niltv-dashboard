"""Athlete side of the Content Hub: /api/hub/athlete (backend/routers/hub_athlete.py).

Runs against the seeded Postgres like the other functional tests. The site
account check is monkeypatched at cognito.verify, as in test_community_star.
Covers who may use the hub, the ask list and its ``mine`` field, claim and
the spot limit, unclaim, one link per claim, and that approved work is locked.
"""

import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import Application, HubAsk, HubClaim
from backend.onboarding import cognito

client = TestClient(app)
BASE = "/api/hub/athlete"
BEARER = {"Authorization": "Bearer token"}
ANN, BO, NEW = "hub.ann@example.com", "hub.bo@example.com", "hub.new@example.com"
TITLE_PREFIX = "pytest athlete hub "


def _clean(db):
    db.query(HubAsk).filter(HubAsk.title.like(TITLE_PREFIX + "%")).delete(synchronize_session=False)
    db.query(Application).filter(Application.email.in_((ANN, BO, NEW))).delete(synchronize_session=False)
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
    db.add_all([
        Application(email=ANN, first_name="Ann", status="accepted"),
        Application(email=BO, first_name="Bo", status="signed"),
        Application(email=NEW, first_name="New", status="applicant"),   # no signed agreement yet
    ])
    db.commit()


def _as(monkeypatch, email, verified=True):
    monkeypatch.setattr(cognito, "verify", lambda token: cognito.Account(
        sub="sub-" + email, email=email, email_verified=verified, pool_id="pool"))


def _ask(db, **kw):
    fields = dict(title=TITLE_PREFIX + "trivia", category="Trivia", format="Reel", tags=["football"],
                  summary="Quiz a teammate.", steps=["Film vertical"], slots=None, status="open")
    fields.update(kw)
    ask = HubAsk(**fields)
    db.add(ask)
    db.commit()
    return ask


def _asks():
    r = client.get(f"{BASE}/asks", headers=BEARER)
    assert r.status_code == 200, r.text
    return {a["id"]: a for a in r.json()["asks"]}


def test_only_signed_athletes_get_in(db, athletes, monkeypatch):
    assert client.get(f"{BASE}/asks").status_code == 401            # no token at all
    _as(monkeypatch, NEW)
    assert client.get(f"{BASE}/asks", headers=BEARER).status_code == 403
    _as(monkeypatch, "stranger@example.com")
    assert client.get(f"{BASE}/asks", headers=BEARER).status_code == 403
    _as(monkeypatch, ANN, verified=False)
    assert client.get(f"{BASE}/asks", headers=BEARER).status_code == 403
    _as(monkeypatch, ANN)
    r = client.get(f"{BASE}/asks", headers=BEARER)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_list_shows_open_asks_only(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    open_ = _ask(db)
    draft = _ask(db, title=TITLE_PREFIX + "draft", status="draft")
    closed = _ask(db, title=TITLE_PREFIX + "closed", status="closed")
    asks = _asks()
    assert open_.id in asks and draft.id not in asks and closed.id not in asks
    a = asks[open_.id]
    assert (a["title"], a["format"], a["tags"], a["claimed"], a["mine"]) == (
        TITLE_PREFIX + "trivia", "Reel", ["football"], 0, None)


def test_claim_then_unclaim(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    ask = _ask(db, slots=2)
    r = client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    assert r.status_code == 200, r.text
    assert r.json()["mine"]["status"] == "claimed"
    assert r.json()["claimed"] == 1
    assert client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER).json()["claimed"] == 1   # twice is fine
    r = client.post(f"{BASE}/asks/{ask.id}/unclaim", headers=BEARER)
    assert r.json()["mine"] is None and r.json()["claimed"] == 0
    # a re-claim reuses the same row
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    assert db.query(HubClaim).filter(HubClaim.ask_id == ask.id).count() == 1


def test_last_spot_goes_to_one_athlete(db, athletes, monkeypatch):
    ask = _ask(db, slots=1)
    _as(monkeypatch, ANN)
    assert client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER).status_code == 200
    _as(monkeypatch, BO)
    assert client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER).status_code == 409
    # Ann lets it go; now Bo can have it
    _as(monkeypatch, ANN)
    client.post(f"{BASE}/asks/{ask.id}/unclaim", headers=BEARER)
    _as(monkeypatch, BO)
    assert client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER).status_code == 200


def test_closed_and_draft_asks_cannot_be_claimed(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    closed = _ask(db, status="closed")
    draft = _ask(db, title=TITLE_PREFIX + "draft", status="draft")
    assert client.post(f"{BASE}/asks/{closed.id}/claim", headers=BEARER).status_code == 409
    assert client.post(f"{BASE}/asks/{draft.id}/claim", headers=BEARER).status_code == 404
    assert client.post(f"{BASE}/asks/999999/claim", headers=BEARER).status_code == 404


def test_submit_one_link_and_replace_it(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    ask = _ask(db)
    assert client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER,
                       json={"url": "https://instagram.com/reel/a"}).status_code == 409   # not claimed yet
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    r = client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER,
                    json={"url": "instagram.com/reel/a", "note": " first cut "})
    assert r.status_code == 200, r.text
    mine = r.json()["mine"]
    assert (mine["status"], mine["url"], mine["note"]) == ("submitted", "https://instagram.com/reel/a", "first cut")
    r = client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER, json={"url": "https://drive.google.com/file/b"})
    assert r.json()["mine"]["url"] == "https://drive.google.com/file/b"
    assert r.json()["mine"]["note"] is None
    claim = db.query(HubClaim).filter(HubClaim.ask_id == ask.id).one()
    assert [s.replaced_at is None for s in claim.submissions] == [False, True]


def test_submit_checks_the_link(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    ask = _ask(db)
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    for bad in ("", "not a link", "javascript:alert(1)", "https://localhost/x"):
        assert client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER,
                           json={"url": bad}).status_code == 422, bad
    assert client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER,
                       json={"url": "https://a.co/x", "note": "x" * 201}).status_code == 422


def test_my_claim_on_a_closed_ask_still_shows(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    ask = _ask(db)
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    ask.status = "closed"
    db.commit()
    assert _asks()[ask.id]["mine"]["status"] == "claimed"


def test_approved_work_is_locked(db, athletes, monkeypatch):
    _as(monkeypatch, ANN)
    ask = _ask(db)
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER, json={"url": "https://instagram.com/reel/a"})
    claim = db.query(HubClaim).filter(HubClaim.ask_id == ask.id).one()
    claim.status = "approved"
    db.commit()
    assert client.post(f"{BASE}/asks/{ask.id}/unclaim", headers=BEARER).status_code == 409
    assert client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER,
                       json={"url": "https://instagram.com/reel/b"}).status_code == 409
    assert _asks()[ask.id]["mine"]["status"] == "approved"


def test_athletes_only_see_their_own_claims(db, athletes, monkeypatch):
    ask = _ask(db)
    _as(monkeypatch, ANN)
    client.post(f"{BASE}/asks/{ask.id}/claim", headers=BEARER)
    client.post(f"{BASE}/asks/{ask.id}/submit", headers=BEARER, json={"url": "https://instagram.com/reel/ann"})
    _as(monkeypatch, BO)
    a = _asks()[ask.id]
    assert a["mine"] is None and a["claimed"] == 1
    assert "ann" not in str(a)
