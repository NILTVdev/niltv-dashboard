"""Functional tests for Community Star finalists, votes and winners (migration 034).

Runs in CI against the seeded Postgres. SES, S3, DNS and Turnstile are never
called: each is monkeypatched. Time is set through the program's dev clock, the
same way staff rehearse on dev.
"""

import inspect
import io
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dns.resolver
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from backend import accounts
from backend.config import get_settings
from backend.database import SessionLocal, engine
from backend.jobs import export_community_star_sheet as export_job
from backend.main import app
from backend.models import CommunityStarApplication, CommunityStarProgram, CommunityStarVote, DashboardUser
from backend.onboarding import card_photo, mailer, vote_guard, vote_outbox
from backend.routers import community_star as cs
from backend.routers import community_star_voting as voting

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
BASE = "/api/community-star"
FEED = f"{BASE}/public"
VOTES = f"{BASE}/votes"
PUBLISH = f"{BASE}/program/publish"

BEFORE_FINALISTS = "2026-11-25T22:59:59+00:00"
FINALISTS_AT = "2026-11-25T23:00:00+00:00"
DURING_FINALISTS = "2026-12-01T12:00:00+00:00"
VOTE_OPENS = "2026-12-11T14:00:00+00:00"
DURING_VOTE = "2026-12-12T12:00:00+00:00"
LAST_SECOND = "2026-12-14T07:59:59+00:00"
VOTE_CLOSES = "2026-12-14T08:00:00+00:00"
AFTER_CLOSE = "2026-12-15T12:00:00+00:00"


def _clean(db):
    db.query(CommunityStarVote).delete()
    db.query(CommunityStarProgram).delete()
    db.query(CommunityStarApplication).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    voting.clear_feed_cache()
    voting._vote_hits.clear()
    yield session
    session.rollback()
    _clean(session)
    session.close()
    voting.clear_feed_cache()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(vote_guard, "has_mail_route", lambda domain: True)
    monkeypatch.setattr(vote_outbox, "_MIN_GAP", 0)
    monkeypatch.setattr(get_settings(), "turnstile_secret", "")


@pytest.fixture()
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_community_star_vote_confirm",
                        lambda to, name, link: sent.append({"to": to, "name": name, "link": link}) or True)
    return sent


def add_finalist(db, name="Jane Doe", stage="finalist", **fields):
    n = db.query(CommunityStarApplication).count() + 1
    a = CommunityStarApplication(
        season=cs.SEASON, email=f"applicant{n}@example.com", full_name=name, phone="9195550100",
        school="Duke University", sport="Lacrosse", class_year="Jr", instagram=f"handle{n}",
        post_url=f"https://www.instagram.com/reel/abc{n}/", community="Durham, NC", work="Reading hour",
        stage=stage, notes="private staff note", ip="203.0.113.7", **fields)
    db.add(a)
    db.commit()
    return a


def set_clock(when):
    r = client.post(f"{BASE}/program/dev-clock", headers=AUTH, json={"now": when})
    assert r.status_code == 200, r.text


def publish(what, on=True):
    return client.post(PUBLISH, headers=AUTH, json={"what": what, "publish": on})


def settings(**values):
    r = client.post(f"{BASE}/program/settings", headers=AUTH, json=values)
    assert r.status_code == 200, r.text


def feed():
    voting.clear_feed_cache()
    r = client.get(FEED)
    assert r.status_code == 200, r.text
    return r.json()


def open_voting(db, *names):
    """Finalists published and the clock inside the vote. Returns the rows."""
    rows = [add_finalist(db, name) for name in (names or ("Jane Doe",))]
    assert publish("finalists").status_code == 200
    set_clock(DURING_VOTE)
    return rows


def vote(finalist, email="fan@example.com", **extra):
    return client.post(VOTES, json={"finalistId": finalist.id, "email": email, "turnstileToken": "t", **extra})


def token_of(sent):
    return sent["link"].rsplit("#confirm=", 1)[1]


def confirm(token):
    return client.post(f"{VOTES}/confirm", json={"token": token})


def confirmed_vote(finalist, email, mail):
    assert vote(finalist, email).status_code == 200
    assert confirm(token_of(mail[-1])).json() == {"status": "confirmed"}


def row_for(db, email="fan@example.com"):
    db.expire_all()
    return db.query(CommunityStarVote).filter(
        CommunityStarVote.email_norm == vote_guard.normalize_email(email)).one()


# -- Stage --------------------------------------------------------------------

def _at(iso):
    return datetime.fromisoformat(iso)


def _program(finalists=True, top5=False, winners=False):
    stamp = _at("2026-11-20T00:00:00+00:00")
    return CommunityStarProgram(
        season=cs.SEASON, settings={},
        finalists_published_at=stamp if finalists else None,
        top5_published_at=stamp if top5 else None,
        winners_published_at=stamp if winners else None)


@pytest.mark.parametrize("when, published, stage", [
    ("2026-11-02T13:59:59+00:00", True, "coming"),
    ("2026-11-02T14:00:00+00:00", False, "open"),
    ("2026-11-24T07:59:59+00:00", False, "open"),
    ("2026-11-24T08:00:00+00:00", False, "closed"),
    (BEFORE_FINALISTS, True, "closed"),
    (FINALISTS_AT, False, "closed"),
    (FINALISTS_AT, True, "finalists"),
    ("2026-12-11T13:59:59+00:00", True, "finalists"),
    (VOTE_OPENS, True, "voting"),
    (VOTE_OPENS, False, "closed"),
    (LAST_SECOND, True, "voting"),
    (VOTE_CLOSES, True, "top5"),
    (VOTE_CLOSES, False, "closed"),
])
def test_stage_edges(when, published, stage):
    assert voting.stage_at(_at(when), _program(finalists=published)) == stage


def test_winners_follow_the_publish_action_not_the_date():
    dec_18 = _at("2026-12-18T14:00:00+00:00")
    assert voting.stage_at(dec_18, _program(top5=True)) == "top5"
    assert voting.stage_at(_at("2027-02-01T00:00:00+00:00"), _program(top5=True)) == "top5"
    assert voting.stage_at(_at(AFTER_CLOSE), _program(top5=True, winners=True)) == "winners"
    assert voting.stage_at(_at(DURING_VOTE), _program(top5=True, winners=True)) == "voting"


def test_paused_keeps_the_voting_stage(db):
    open_voting(db)
    settings(voting_paused=True)
    body = feed()
    assert body["stage"] == "voting" and voting.stage_now(db) == "voting"
    assert body["voting"] == {"open": False, "paused": True, "turnstile": False}


# -- Invariant 1: no name before publish and the finalists time ---------------

def test_marking_a_finalist_publishes_nothing(db):
    add_finalist(db, "Secret Name")
    set_clock(DURING_FINALISTS)
    r = client.get(FEED)
    assert r.json()["stage"] == "closed" and r.json()["finalists"] == []
    assert "Secret Name" not in r.text


def test_publish_alone_waits_for_the_clock(db):
    add_finalist(db, "Secret Name")
    set_clock(BEFORE_FINALISTS)
    assert publish("finalists").status_code == 200
    voting.clear_feed_cache()
    r = client.get(FEED)
    assert r.json()["finalists"] == [] and "Secret Name" not in r.text
    set_clock(FINALISTS_AT)
    assert [f["name"] for f in feed()["finalists"]] == ["Secret Name"]


def test_unpublish_takes_names_off_at_once(db):
    add_finalist(db, "Secret Name")
    assert publish("finalists").status_code == 200
    set_clock(DURING_FINALISTS)
    assert client.get(FEED).json()["finalists"]
    assert publish("finalists", False).status_code == 200
    assert client.get(FEED).json()["finalists"] == []   # no clear: publish cleared the cache


def test_sheet_stage_edit_publishes_nothing(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    a = add_finalist(db, "Secret Name", stage="applied")
    export_job.export_community_star(db)
    sheet.edit(a.id, "Stage", "Finalist")
    export_job.export_community_star(db)
    db.refresh(a)
    assert a.stage == "finalist"
    set_clock(DURING_FINALISTS)
    assert feed()["finalists"] == []


def test_top5_and_winner_marks_stay_hidden_until_published(db):
    a = add_finalist(db, "Ann Top", stage="top5")
    b = add_finalist(db, "Bea Winner", stage="winner")
    add_finalist(db, "Cal Finalist")
    open_voting(db, "Dee Finalist")
    for f in feed()["finalists"]:
        assert f["top5"] is False and f["winner"] is False
    set_clock(AFTER_CLOSE)
    body = feed()
    assert body["stage"] == "top5" and body["top5_published"] is False
    assert not any(f["top5"] or f["winner"] for f in body["finalists"])

    assert publish("top5").status_code == 200
    body = feed()
    assert {f["id"] for f in body["finalists"] if f["top5"]} == {a.id, b.id}
    assert not any(f["winner"] for f in body["finalists"])
    assert body["top5_published"] is True and body["winners_published"] is False

    assert publish("winners").status_code == 200
    body = feed()
    assert body["stage"] == "winners" and body["winners_published"] is True
    assert [f["id"] for f in body["finalists"] if f["winner"]] == [b.id]


# -- Feed shape and privacy ---------------------------------------------------

CARD_KEYS = {"id", "slug", "name", "school", "sport", "community", "cause", "photo", "youtube", "top5", "winner"}


def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)


def test_feed_shape_and_cache_header(db):
    a = add_finalist(db, "Jane Doe")
    open_voting(db, "Zed Last")
    voting.clear_feed_cache()
    r = client.get(FEED)
    assert r.headers["cache-control"] == "public, max-age=15"
    body = r.json()
    assert set(body) == {"server_time", "stage", "times", "voting", "finalists", "board",
                         "top5_published", "winners_published"}
    assert body["times"] == {
        "opens": "2026-11-02T14:00:00Z", "closes": "2026-11-24T08:00:00Z", "finalists": "2026-11-25T23:00:00Z",
        "vote_opens": "2026-12-11T14:00:00Z", "vote_closes": "2026-12-14T08:00:00Z"}
    card = body["finalists"][0]
    assert set(card) == CARD_KEYS
    assert card["slug"] == f"jane-doe-{a.id}"
    assert card["cause"] == "" and card["photo"] == "" and card["youtube"] == ""


def test_no_private_field_in_any_public_response(db, mail):
    a, b = open_voting(db, "Jane Doe", "Sam Roe")
    a.cause = "Reading hour"
    db.commit()
    confirmed_vote(a, "fan.private@example.com", mail)
    assert vote(b, "pending.fan@example.com").status_code == 200
    token = token_of(mail[-1])

    responses = [client.get(FEED)]
    voting.clear_feed_cache()
    responses.append(client.get(FEED))
    responses.append(client.post(f"{VOTES}/preview", json={"token": token}))
    set_clock(AFTER_CLOSE)
    voting.clear_feed_cache()
    responses.append(client.get(FEED))

    banned_keys = {"email", "phone", "notes", "ip", "votes", "count", "confirmed", "pending", "total", "void"}
    for r in responses:
        assert not (set(_keys(r.json())) & banned_keys)
        for secret in ("fan.private", "pending.fan", "applicant", "9195550100", "private staff note", "203.0.113"):
            assert secret not in r.text
    assert set(responses[1].json()["board"]["rows"][0]) == {"rank", "id", "name"}


def test_cached_feed_keeps_server_time_moving(db):
    add_finalist(db)
    assert client.get(FEED).status_code == 200
    first = voting._feed["body"]
    assert client.get(FEED).status_code == 200
    assert voting._feed["body"] is first
    assert "server_time" not in first


def test_card_overrides_and_fallbacks(db):
    a = add_finalist(db, "Jane Marie Doe")
    r = client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={
        "card_name": "Jane Doe", "card_school": "Duke", "card_sport": "LAX", "card_community": "Durham",
        "cause": "Reading hour for Durham kids", "youtube_id": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.status_code == 200, r.text
    out = r.json()["application"]
    assert out["card_name"] == "Jane Doe" and out["card_community"] == "Durham"
    open_voting(db, "Other Person")
    card = next(f for f in feed()["finalists"] if f["id"] == a.id)
    assert (card["name"], card["school"], card["sport"], card["community"]) == ("Jane Doe", "Duke", "LAX", "Durham")
    assert card["slug"] == f"jane-doe-{a.id}"
    assert card["cause"] == "Reading hour for Durham kids" and card["youtube"] == "dQw4w9WgXcQ"
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"card_school": ""})
    assert next(f for f in feed()["finalists"] if f["id"] == a.id)["school"] == "Duke University"


def test_disqualified_rows_drop_out(db):
    a, b = open_voting(db, "Jane Doe", "Sam Roe")
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "disqualified"})
    assert [f["id"] for f in feed()["finalists"]] == [b.id]
    assert vote(a).status_code == 400


def test_card_order_setting(db):
    open_voting(db, "Zed Last", "amy first", "Mid Dle", "Bob Two", "Cy Three")
    assert [f["name"] for f in feed()["finalists"]] == ["amy first", "Bob Two", "Cy Three", "Mid Dle", "Zed Last"]
    settings(card_order="shuffled")
    first = [f["id"] for f in feed()["finalists"]]
    assert first == [f["id"] for f in feed()["finalists"]]
    assert first == sorted(first, key=lambda i: voting.hashlib.sha256(f"{cs.SEASON}:{i}".encode()).hexdigest())


def test_samples_never_come_from_the_api(db):
    body = feed()
    assert body["finalists"] == [] and body["board"] == {"state": "hidden", "rows": []}


# -- Board --------------------------------------------------------------------

def test_board_ranks_by_votes_then_earliest_last_confirm(db, mail):
    a, b, c = open_voting(db, "Ann", "Bea", "Cal")
    confirmed_vote(b, "b1@example.com", mail)
    confirmed_vote(a, "a1@example.com", mail)
    confirmed_vote(a, "a2@example.com", mail)
    confirmed_vote(c, "c1@example.com", mail)
    board = feed()["board"]
    assert board["state"] == "live"
    assert board["rows"] == [{"rank": 1, "id": a.id, "name": "Ann"}, {"rank": 2, "id": b.id, "name": "Bea"},
                             {"rank": 3, "id": c.id, "name": "Cal"}]


def test_board_ties_on_the_same_instant_go_by_name(db, mail):
    a, b = open_voting(db, "Zoe", "Abe")
    confirmed_vote(a, "z@example.com", mail)
    confirmed_vote(b, "y@example.com", mail)
    stamp = datetime(2026, 12, 12, tzinfo=timezone.utc)
    db.query(CommunityStarVote).update({"confirmed_at": stamp})
    db.commit()
    assert [r["name"] for r in feed()["board"]["rows"]] == ["Abe", "Zoe"]


def test_board_shows_five_rows_at_most(db, mail):
    rows = open_voting(db, "A1", "A2", "A3", "A4", "A5", "A6")
    for i, f in enumerate(rows):
        confirmed_vote(f, f"v{i}@example.com", mail)
    assert [r["rank"] for r in feed()["board"]["rows"]] == [1, 2, 3, 4, 5]


def test_board_counts_only_confirmed_unvoided_active_votes(db, mail):
    a, b, c = open_voting(db, "Ann", "Bea", "Cal")
    assert vote(a, "pending@example.com").status_code == 200
    assert feed()["board"] == {"state": "empty", "rows": []}
    confirmed_vote(b, "bea.fan@example.com", mail)
    confirmed_vote(c, "cal.fan@example.com", mail)
    assert {r["id"] for r in feed()["board"]["rows"]} == {b.id, c.id}
    bad = row_for(db, "bea.fan@example.com")
    assert client.post(f"{VOTES}/{bad.id}/void", headers=AUTH, json={"reason": "bot"}).status_code == 200
    client.post(f"{BASE}/applications/{c.id}/update", headers=AUTH, json={"stage": "disqualified"})
    assert feed()["board"] == {"state": "empty", "rows": []}


def test_board_min_votes_and_hidden(db, mail):
    a, = open_voting(db)
    settings(board_min_votes=2)
    confirmed_vote(a, "one@example.com", mail)
    assert feed()["board"] == {"state": "empty", "rows": []}
    confirmed_vote(a, "two@example.com", mail)
    assert feed()["board"]["state"] == "live"
    settings(leaderboard_visible=False)
    assert feed()["board"] == {"state": "hidden", "rows": []}


def test_no_board_before_voting(db):
    add_finalist(db)
    publish("finalists")
    set_clock(DURING_FINALISTS)
    assert feed()["board"] == {"state": "hidden", "rows": []}


# -- Freeze -------------------------------------------------------------------

def test_board_freezes_once_and_later_voids_do_not_change_it(db, mail):
    a, b = open_voting(db, "Ann", "Bea")
    confirmed_vote(a, "a1@example.com", mail)
    confirmed_vote(a, "a2@example.com", mail)
    confirmed_vote(b, "b1@example.com", mail)
    set_clock(VOTE_CLOSES)
    frozen = feed()["board"]
    assert frozen["state"] == "frozen" and [r["id"] for r in frozen["rows"]] == [a.id, b.id]
    db.expire_all()
    program = db.get(CommunityStarProgram, cs.SEASON)
    assert program.frozen_at is not None
    stamp = program.frozen_at

    for email in ("a1@example.com", "a2@example.com"):
        vote_id = row_for(db, email).id
        assert client.post(f"{VOTES}/{vote_id}/void", headers=AUTH, json={"reason": "bot"}).status_code == 200
    assert feed()["board"] == frozen
    db.expire_all()
    assert db.get(CommunityStarProgram, cs.SEASON).frozen_at == stamp
    assert client.get(f"{VOTES}/summary", headers=AUTH).json()["totals"]["void"] == 2


def test_finalist_disqualified_after_close_leaves_the_frozen_board(db, mail):
    a, b, c = open_voting(db, "Ann", "Bea", "Cam")
    confirmed_vote(a, "a1@example.com", mail)
    confirmed_vote(a, "a2@example.com", mail)
    confirmed_vote(a, "a3@example.com", mail)
    confirmed_vote(b, "b1@example.com", mail)
    confirmed_vote(b, "b2@example.com", mail)
    confirmed_vote(c, "c1@example.com", mail)
    set_clock(VOTE_CLOSES)
    assert [r["rank"] for r in feed()["board"]["rows"]] == [1, 2, 3]
    stored = db.get(CommunityStarProgram, cs.SEASON).frozen_board

    assert client.post(f"{BASE}/applications/{b.id}/update", headers=AUTH,
                       json={"stage": "disqualified"}).status_code == 200
    board = feed()["board"]
    assert board["state"] == "frozen"
    assert [(r["rank"], r["name"]) for r in board["rows"]] == [(1, "Ann"), (3, "Cam")]
    db.expire_all()
    assert db.get(CommunityStarProgram, cs.SEASON).frozen_board == stored


def test_grace_holds_the_board_open_then_freezes(db, mail):
    a, = open_voting(db)
    settings(confirm_grace_minutes=30)
    assert vote(a, "late@example.com").status_code == 200
    token = token_of(mail[-1])
    set_clock("2026-12-14T08:10:00+00:00")
    body = feed()
    assert body["stage"] == "top5" and body["voting"]["open"] is False and body["board"]["state"] == "empty"
    assert vote(a, "too.late@example.com").status_code == 410
    assert confirm(token).json() == {"status": "confirmed"}
    assert feed()["board"]["state"] == "live"
    set_clock("2026-12-14T08:30:00+00:00")
    assert feed()["board"]["state"] == "frozen"


def test_grace_cannot_change_after_the_freeze(db):
    open_voting(db)
    set_clock(AFTER_CLOSE)
    feed()
    r = client.post(f"{BASE}/program/settings", headers=AUTH, json={"confirm_grace_minutes": 60})
    assert r.status_code == 409


def test_nothing_freezes_without_published_finalists(db):
    add_finalist(db)
    set_clock(AFTER_CLOSE)
    body = feed()
    assert body["stage"] == "closed" and body["board"]["state"] == "hidden"
    db.expire_all()
    assert db.get(CommunityStarProgram, cs.SEASON).frozen_board is None


def test_outbox_tick_freezes_without_a_visitor(db):
    open_voting(db)
    set_clock(AFTER_CLOSE)
    voting.ensure_frozen(db)
    db.expire_all()
    assert db.get(CommunityStarProgram, cs.SEASON).frozen_at is not None


# -- Casting a vote -----------------------------------------------------------

def test_vote_is_pending_until_confirmed(db, mail):
    a, = open_voting(db)
    r = vote(a, "Fan@Example.com")
    assert r.status_code == 200 and r.json() == {"status": "pending"}
    row = row_for(db)
    assert row.status == "pending" and row.email == "fan@example.com" and row.finalist_id == a.id
    assert row.mail_status == "sent" and row.sends == 1 and row.ip == "testclient"
    assert feed()["board"]["state"] == "empty"
    assert mail == [{"to": "fan@example.com", "name": "Jane Doe", "link": mail[0]["link"]}]


def test_confirm_link_carries_the_token_in_the_fragment_and_it_is_stored_hashed(db, mail):
    a, = open_voting(db)
    vote(a)
    link = mail[0]["link"]
    assert re.fullmatch(r"https://niltv\.com/communitystar/#confirm=[A-Za-z0-9_-]{43}", link)
    token = token_of(mail[0])
    row = row_for(db)
    assert row.token_hash == vote_outbox.hash_token(token) and token not in row.token_hash
    assert len(row.token_hash) == 64
    stored = db.execute(text("SELECT row_to_json(v)::text FROM community_star_votes v")).scalar()
    assert token not in stored


def test_token_expires_in_48_hours(db, mail):
    a, = open_voting(db)
    vote(a)
    assert row_for(db).token_expires == _at(DURING_VOTE) + timedelta(hours=48)


@pytest.mark.parametrize("first, second", [
    ("jane.doe@gmail.com", "janedoe@gmail.com"),
    ("janedoe@gmail.com", "JANE.DOE+vote@googlemail.com"),
    ("fan@example.com", "fan+second@example.com"),
    ("fan@example.com", "FAN@EXAMPLE.COM"),
])
def test_one_vote_per_normalised_email(db, mail, first, second):
    a, b = open_voting(db, "Ann", "Bea")
    assert vote(a, first).status_code == 200
    assert confirm(token_of(mail[-1])).status_code == 200
    r = vote(b, second)
    assert r.status_code == 409
    assert db.query(CommunityStarVote).count() == 1
    assert row_for(db, first).finalist_id == a.id


def test_different_dotted_addresses_stay_separate_off_gmail(db, mail):
    a, = open_voting(db)
    assert vote(a, "jane.doe@example.com").status_code == 200
    assert vote(a, "janedoe@example.com").status_code == 200
    assert db.query(CommunityStarVote).count() == 2


@pytest.mark.parametrize("when, status", [
    ("2026-12-11T13:59:59+00:00", 410),
    (VOTE_OPENS, 200),
    (LAST_SECOND, 200),
    (VOTE_CLOSES, 410),
])
def test_vote_window_edges(db, mail, when, status):
    a = add_finalist(db)
    publish("finalists")
    set_clock(when)
    assert vote(a).status_code == status


def test_no_vote_without_published_finalists(db, mail):
    a = add_finalist(db)
    set_clock(DURING_VOTE)
    assert vote(a).status_code == 410
    assert db.query(CommunityStarVote).count() == 0


def test_paused_rejects_votes_and_confirms(db, mail):
    a, = open_voting(db)
    vote(a)
    settings(voting_paused=True)
    assert vote(a, "two@example.com").status_code == 503
    assert confirm(token_of(mail[0])).status_code == 503
    assert row_for(db).status == "pending"
    settings(voting_paused=False)
    assert confirm(token_of(mail[0])).status_code == 200


def test_honeypot_answers_200_and_keeps_nothing(db, mail):
    r = client.post(VOTES, json={"finalistId": 1, "email": "bot@example.com", "website": "http://spam.example"})
    assert r.status_code == 200 and r.json() == {"status": "pending"}
    assert db.query(CommunityStarVote).count() == 0 and mail == []


def test_per_ip_rate_limit(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(get_settings(), "community_star_vote_rate_per_hour", 2)
    assert vote(a, "one@example.com").status_code == 200
    assert vote(a, "two@example.com").status_code == 200
    assert vote(a, "three@example.com").status_code == 429


def test_body_size_limit(db):
    r = client.post(VOTES, content=b"{" + b" " * 9000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413


@pytest.mark.parametrize("body, needle", [
    ({"email": "not-an-email"}, "valid email"),
    ({"email": "a,b@example.com"}, "valid email"),
    ({"email": "+tag@example.com"}, "valid email"),
    ({"email": 42}, "valid email"),
    ({"email": "fan@mailinator.com"}, "permanent"),
    ({"email": "fan@sub.mailinator.com"}, "permanent"),
    ({"finalistId": 999999}, "finalist"),
    ({"finalistId": "1"}, "finalist"),
    ({"finalistId": True}, "finalist"),
])
def test_bad_votes_get_a_safe_400(db, mail, body, needle):
    a, = open_voting(db)
    r = client.post(VOTES, json={"finalistId": a.id, "email": "fan@example.com", **body})
    assert r.status_code == 400
    assert needle in r.json()["detail"]
    assert db.query(CommunityStarVote).count() == 0


def test_applicant_who_is_not_a_finalist_cannot_be_voted_for(db, mail):
    open_voting(db)
    other = add_finalist(db, "Not Picked", stage="applied")
    assert vote(other).status_code == 400


def test_domain_without_mail_is_refused(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(vote_guard, "has_mail_route", lambda domain: False)
    assert vote(a).status_code == 400


def test_check_order_window_before_pause_before_rate(db, mail, monkeypatch):
    a = add_finalist(db)
    publish("finalists")
    settings(voting_paused=True)
    monkeypatch.setattr(get_settings(), "community_star_vote_rate_per_hour", 0)
    set_clock(AFTER_CLOSE)
    assert vote(a).status_code == 410
    set_clock(DURING_VOTE)
    assert vote(a).status_code == 503
    settings(voting_paused=False)
    assert vote(a).status_code == 429


# -- Resend and changing a pending pick ---------------------------------------

def _age_last_send(db, email="fan@example.com"):
    row = row_for(db, email)
    row.last_sent_at = datetime.now(tz=timezone.utc) - timedelta(seconds=61)
    db.commit()


def test_resend_rotates_the_token_and_kills_the_old_link(db, mail):
    a, = open_voting(db)
    vote(a)
    _age_last_send(db)
    assert vote(a).status_code == 200
    assert len(mail) == 2 and token_of(mail[0]) != token_of(mail[1])
    assert confirm(token_of(mail[0])).status_code == 404
    assert confirm(token_of(mail[1])).json() == {"status": "confirmed"}


def test_resend_spacing_and_cap(db, mail):
    a, = open_voting(db)
    vote(a)
    assert vote(a).status_code == 429          # inside 60 seconds
    _age_last_send(db)
    assert vote(a).status_code == 200
    _age_last_send(db)
    assert vote(a).status_code == 200
    _age_last_send(db)
    assert vote(a).status_code == 429          # three sends is the cap
    assert len(mail) == 3 and row_for(db).sends == 3


def _use_up_sends(db, finalist):
    vote(finalist)
    for _ in range(2):
        _age_last_send(db)
        assert vote(finalist).status_code == 200
    _age_last_send(db)


def test_expired_link_earns_one_more_send_past_the_cap(db, mail):
    a, = open_voting(db)
    set_clock(VOTE_OPENS)
    _use_up_sends(db, a)
    assert vote(a).status_code == 429          # the third link is still good
    set_clock("2026-12-13T14:00:00+00:00")     # 48 hours on
    assert client.post(f"{VOTES}/preview", json={"token": token_of(mail[-1])}).json()["status"] == "expired"

    assert vote(a).status_code == 200
    assert len(mail) == 4
    _age_last_send(db)
    assert vote(a).status_code == 429          # the new link holds the cap again
    assert confirm(token_of(mail[-1])).json() == {"status": "confirmed"}


def test_staff_can_reset_the_send_cap(db, mail):
    a, = open_voting(db)
    _use_up_sends(db, a)
    assert vote(a).status_code == 429
    vote_id = row_for(db).id

    r = client.post(f"{VOTES}/{vote_id}/reset-sends", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["sends"] == 0 and r.json()["sends_reset_by"] and r.json()["sends_reset_at"]
    assert r.json()["status"] == "pending" and len(mail) == 3      # sends nothing, confirms nothing

    assert vote(a).status_code == 200
    assert len(mail) == 4


@pytest.mark.parametrize("void", [False, True])
def test_only_a_pending_vote_can_reset_sends(db, mail, void):
    a, = open_voting(db)
    confirmed_vote(a, "fan@example.com", mail)
    vote_id = row_for(db).id
    if void:
        client.post(f"{VOTES}/{vote_id}/void", headers=AUTH, json={"reason": "fake"})
    assert client.post(f"{VOTES}/{vote_id}/reset-sends", headers=AUTH).status_code == 409
    assert client.post(f"{VOTES}/999999/reset-sends", headers=AUTH).status_code == 404


def test_pending_pick_can_change_by_default(db, mail):
    a, b = open_voting(db, "Ann", "Bea")
    vote(a)
    _age_last_send(db)
    assert vote(b).status_code == 200
    assert row_for(db).finalist_id == b.id and mail[-1]["name"] == "Bea"
    assert db.query(CommunityStarVote).count() == 1


def test_pending_pick_is_kept_when_the_setting_is_off(db, mail):
    a, b = open_voting(db, "Ann", "Bea")
    settings(allow_pending_change=False)
    vote(a)
    _age_last_send(db)
    assert vote(b).status_code == 200
    assert row_for(db).finalist_id == a.id and mail[-1]["name"] == "Ann"


def test_voided_voter_cannot_vote_again(db, mail):
    a, = open_voting(db)
    vote(a)
    client.post(f"{VOTES}/{row_for(db).id}/void", headers=AUTH, json={"reason": "fake"})
    assert vote(a).status_code == 409


# -- Confirming ---------------------------------------------------------------

def test_token_is_single_use(db, mail):
    a, = open_voting(db)
    vote(a)
    token = token_of(mail[0])
    r = client.post(f"{VOTES}/confirm", json={"token": token}, headers={"User-Agent": "phone"})
    assert r.json() == {"status": "confirmed"}
    row = row_for(db)
    assert row.status == "confirmed" and row.confirmed_at and row.confirm_ip == "testclient"
    assert row.confirm_user_agent == "phone"
    stamp = row.confirmed_at
    assert confirm(token).json() == {"status": "already"}
    assert row_for(db).confirmed_at == stamp


def test_get_never_counts_a_vote(db, mail):
    a, = open_voting(db)
    vote(a)
    token = token_of(mail[0])
    for path in (f"{VOTES}/confirm?token={token}", f"{VOTES}/preview?token={token}",
                 f"{VOTES}/confirm/{token}", f"/communitystar/?confirm={token}"):
        assert client.get(path).status_code in (404, 405)
    assert client.get(VOTES, params={"token": token}).status_code == 401
    assert row_for(db).status == "pending"


def test_no_get_route_can_reach_confirm():
    for route in app.routes:
        if "confirm" in getattr(route, "path", "") and "community-star" in route.path:
            assert route.methods == {"POST"}


def test_preview_changes_nothing_and_names_the_finalist(db, mail):
    a, = open_voting(db)
    vote(a)
    token = token_of(mail[0])
    for _ in range(3):
        r = client.post(f"{VOTES}/preview", json={"token": token})
        assert r.json() == {"status": "pending", "finalist": {"id": a.id, "name": "Jane Doe"}}
    row = row_for(db)
    assert row.status == "pending" and row.confirmed_at is None and row.confirm_ip is None
    assert confirm(token).status_code == 200
    assert client.post(f"{VOTES}/preview", json={"token": token}).json()["status"] == "confirmed"


def test_expired_token(db, mail):
    a, = open_voting(db)
    vote(a)
    token = token_of(mail[0])
    set_clock("2026-12-14T12:00:00+00:00")
    assert client.post(f"{VOTES}/preview", json={"token": token}).json()["status"] == "closed"
    set_clock(DURING_VOTE)
    row = row_for(db)
    row.token_expires = _at(DURING_VOTE)     # expiry is exclusive
    db.commit()
    assert client.post(f"{VOTES}/preview", json={"token": token}).json()["status"] == "expired"
    r = confirm(token)
    assert r.status_code == 410 and r.json()["detail"] == "expired"
    assert row_for(db).status == "pending"


def test_closed_confirm(db, mail):
    a, = open_voting(db)
    vote(a)
    set_clock(VOTE_CLOSES)
    r = confirm(token_of(mail[0]))
    assert r.status_code == 410 and r.json()["detail"] == "closed"
    assert row_for(db).status == "pending"


@pytest.mark.parametrize("token", ["", "x", "y" * 200, None, 5])
def test_invalid_token(db, token):
    assert client.post(f"{VOTES}/confirm", json={"token": token}).status_code == 404
    assert client.post(f"{VOTES}/preview", json={"token": token}).json() == {"status": "invalid", "finalist": None}


def test_void_kills_the_token(db, mail):
    a, = open_voting(db)
    vote(a)
    client.post(f"{VOTES}/{row_for(db).id}/void", headers=AUTH, json={"reason": "fake"})
    assert confirm(token_of(mail[0])).status_code == 404
    assert client.post(f"{VOTES}/preview", json={"token": token_of(mail[0])}).json()["status"] == "invalid"


def test_disqualified_finalist_cannot_gain_a_confirm(db, mail):
    a, = open_voting(db)
    vote(a)
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "disqualified"})
    r = confirm(token_of(mail[0]))
    assert r.status_code == 410 and r.json()["detail"] == "finalist_out"
    assert client.post(f"{VOTES}/preview", json={"token": token_of(mail[0])}).json() == {
        "status": "finalist_out", "finalist": None}
    assert row_for(db).status == "pending"


def test_after_the_close_a_disqualified_pick_reads_closed(db, mail):
    a, = open_voting(db)
    vote(a)
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "disqualified"})
    set_clock(VOTE_CLOSES)
    assert client.post(f"{VOTES}/preview", json={"token": token_of(mail[0])}).json()["status"] == "closed"


@pytest.mark.parametrize("allow_change", [True, False])
def test_voter_with_a_disqualified_pick_can_choose_again(db, mail, allow_change):
    a, b = open_voting(db, "Ann", "Bea")
    settings(allow_pending_change=allow_change)
    _use_up_sends(db, a)
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "disqualified"})

    assert vote(b).status_code == 200
    assert row_for(db).finalist_id == b.id and mail[-1]["name"] == "Bea"
    assert confirm(token_of(mail[-1])).json() == {"status": "confirmed"}


def test_no_setting_can_confirm_a_vote(db, mail):
    a, = open_voting(db)
    settings(confirm_grace_minutes=1440, allow_pending_change=True, voting_paused=False)
    vote(a)
    assert row_for(db).status == "pending"
    for key in ("auto_confirm", "skip_confirm", "bypass"):
        r = client.post(f"{BASE}/program/settings", headers=AUTH, json={key: True})
        assert r.status_code == 400


# -- Turnstile ----------------------------------------------------------------

def test_turnstile_fails_closed_in_production(db, mail, monkeypatch):
    a, = open_voting(db)
    s = get_settings()
    s_clock = _at(DURING_VOTE)
    monkeypatch.setattr(voting, "official_now", lambda db: s_clock)
    monkeypatch.setattr(s, "environment", "production")
    r = vote(a)
    assert r.status_code == 503
    assert db.query(CommunityStarVote).count() == 0
    assert feed()["voting"] == {"open": False, "paused": True, "turnstile": False}


def test_turnstile_skipped_when_empty_on_dev(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(vote_guard, "turnstile_ok", lambda *args: pytest.fail("must not call Cloudflare"))
    assert vote(a).status_code == 200


def test_turnstile_rejects_a_bad_token(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(get_settings(), "turnstile_secret", "secret")
    seen = []
    monkeypatch.setattr(vote_guard, "turnstile_ok", lambda secret, token, ip: seen.append((secret, token, ip)) or False)
    r = vote(a, turnstileToken="bad")
    assert r.status_code == 400
    assert seen == [("secret", "bad", "testclient")]
    assert db.query(CommunityStarVote).count() == 0


def test_turnstile_outage_refuses_the_vote(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(get_settings(), "turnstile_secret", "secret")

    def down(*args):
        raise vote_guard.TurnstileUnavailable

    monkeypatch.setattr(vote_guard, "turnstile_ok", down)
    assert vote(a).status_code == 503
    assert db.query(CommunityStarVote).count() == 0


def test_turnstile_passes_a_good_token(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(get_settings(), "turnstile_secret", "secret")
    monkeypatch.setattr(vote_guard, "turnstile_ok", lambda *args: True)
    assert vote(a).status_code == 200
    assert feed()["voting"]["turnstile"] is True


def test_turnstile_network_errors_become_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise vote_guard.httpx.ConnectError("down")

    monkeypatch.setattr(vote_guard.httpx, "post", boom)
    with pytest.raises(vote_guard.TurnstileUnavailable):
        vote_guard.turnstile_ok("secret", "token", "1.1.1.1")
    assert vote_guard.turnstile_ok("secret", "", "1.1.1.1") is False


# -- Dev clock ----------------------------------------------------------------

def test_dev_clock_refused_in_production(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment", "production")
    r = client.post(f"{BASE}/program/dev-clock", headers=AUTH, json={"now": DURING_VOTE})
    assert r.status_code == 403
    assert db.get(CommunityStarProgram, cs.SEASON) is None or db.get(CommunityStarProgram, cs.SEASON).dev_now is None


def test_stored_dev_clock_is_ignored_in_production(db, monkeypatch):
    set_clock(DURING_VOTE)
    assert cs.official_now(db) == _at(DURING_VOTE)
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert cs.official_now(db) != _at(DURING_VOTE)
    assert client.get(f"{BASE}/program", headers=AUTH).json()["dev_now"] is None


def test_dev_clock_bad_values_and_clearing(db):
    r = client.post(f"{BASE}/program/dev-clock", headers=AUTH, json={"now": "next tuesday"})
    assert r.status_code == 400
    set_clock("2026-12-12T12:00:00Z")
    assert client.get(f"{BASE}/program", headers=AUTH).json()["dev_now"].startswith("2026-12-12T12:00:00")
    set_clock(None)
    assert client.get(f"{BASE}/program", headers=AUTH).json()["dev_now"] is None


def test_rehearsing_before_the_close_clears_the_freeze(db):
    open_voting(db)
    set_clock(AFTER_CLOSE)
    assert feed()["board"]["state"] == "frozen"
    set_clock(DURING_VOTE)
    db.expire_all()
    program = db.get(CommunityStarProgram, cs.SEASON)
    assert program.frozen_board is None and program.frozen_at is None
    assert db.execute(text("SELECT frozen_board IS NULL FROM community_star_program")).scalar() is True


def test_the_application_form_follows_the_dev_clock(db, monkeypatch):
    set_clock("2026-11-10T12:00:00+00:00")
    assert cs.is_open(cs.official_now(db)) is True
    set_clock(AFTER_CLOSE)
    assert client.post(f"{BASE}/applications", json={}).status_code == 410


# -- Publish rules ------------------------------------------------------------

def test_finalists_publish_needs_a_finalist(db):
    assert publish("finalists").status_code == 409
    add_finalist(db, stage="shortlist")
    assert publish("finalists").status_code == 409
    add_finalist(db)
    assert publish("finalists").status_code == 200


def test_top5_refused_before_the_close(db):
    add_finalist(db, stage="top5")
    publish("finalists")
    set_clock(LAST_SECOND)
    assert publish("top5").status_code == 409
    set_clock(VOTE_CLOSES)
    assert publish("top5").status_code == 200


def test_top5_needs_published_finalists_and_marks(db):
    add_finalist(db)
    set_clock(AFTER_CLOSE)
    assert publish("top5").status_code == 409
    publish("finalists")
    assert publish("top5").status_code == 409


def test_winners_need_the_top5_and_a_winner_row(db):
    a = add_finalist(db, stage="top5")
    publish("finalists")
    set_clock(AFTER_CLOSE)
    assert publish("winners").status_code == 409
    publish("top5")
    assert publish("winners").status_code == 409
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "winner"})
    assert publish("winners").status_code == 200


def test_unpublish_goes_in_reverse_order(db):
    add_finalist(db, stage="winner")
    publish("finalists")
    set_clock(AFTER_CLOSE)
    publish("top5")
    publish("winners")
    assert publish("top5", False).status_code == 409
    assert publish("finalists", False).status_code == 409
    assert publish("winners", False).status_code == 200
    assert feed()["stage"] == "top5"
    assert publish("top5", False).status_code == 200
    assert feed()["top5_published"] is False
    assert publish("finalists", False).status_code == 200
    assert feed()["stage"] == "closed"


@pytest.mark.parametrize("body", [{"what": "everything", "publish": True}, {"what": "top5"}, {"what": "top5", "publish": "yes"}])
def test_publish_rejects_bad_bodies(db, body):
    assert client.post(PUBLISH, headers=AUTH, json=body).status_code == 400


def test_publish_records_who_and_clears_the_cache(db):
    add_finalist(db, "Jane Doe")
    set_clock(DURING_FINALISTS)
    assert client.get(FEED).json()["finalists"] == []
    out = publish("finalists").json()
    assert out["published_by"] == "dashboard" and out["finalists_published_at"]
    assert out["stage"] == "finalists"
    assert len(client.get(FEED).json()["finalists"]) == 1


# -- Staff access and settings ------------------------------------------------

STAFF_GETS = ["/program", "/votes/summary", "/votes", "/votes.csv"]
STAFF_POSTS = ["/program/publish", "/program/settings", "/program/dev-clock", "/votes/1/void", "/votes/1/restore",
               "/votes/1/reset-sends"]


@pytest.mark.parametrize("path", STAFF_GETS)
def test_staff_reads_need_the_key(db, path):
    assert client.get(BASE + path).status_code == 401


@pytest.mark.parametrize("path", STAFF_POSTS + ["/applications/1/photo"])
def test_staff_writes_need_the_key(db, path):
    assert client.post(BASE + path, json={}).status_code == 401


@pytest.mark.parametrize("role", ["general", "demo"])
def test_vote_counts_are_admin_only(role):
    for path in STAFF_GETS:
        assert accounts.allowed(role, "GET", BASE + path) is False
    for path in STAFF_POSTS:
        assert accounts.allowed(role, "POST", BASE + path) is False
    assert accounts.allowed("admin", "POST", PUBLISH) is True


def test_general_account_gets_403(db):
    user = DashboardUser(email="reader@example.com", name="Reader", role="general", password_hash="x")
    db.add(user)
    db.commit()
    try:
        r = client.get(f"{VOTES}/summary", headers={
            **AUTH, "X-Dashboard-User": str(user.id), "X-Dashboard-Session-Version": str(user.session_version)})
        assert r.status_code == 403
    finally:
        db.delete(user)
        db.commit()


@pytest.mark.parametrize("body", [
    {"confirm_grace_minutes": -1}, {"confirm_grace_minutes": "5"}, {"confirm_grace_minutes": True},
    {"board_min_votes": 0}, {"card_order": "random"}, {"voting_paused": "false"},
    {"leaderboard_visible": 1}, {"unknown": 1}, {},
])
def test_settings_validation(db, body):
    assert client.post(f"{BASE}/program/settings", headers=AUTH, json=body).status_code == 400


def test_settings_defaults_and_partial_save(db):
    out = client.get(f"{BASE}/program", headers=AUTH).json()
    assert out["settings"] == {"confirm_grace_minutes": 0, "allow_pending_change": True, "leaderboard_visible": True,
                               "board_min_votes": 1, "card_order": "alphabetical", "voting_paused": False}
    settings(board_min_votes=5)
    settings(card_order="shuffled")
    out = client.get(f"{BASE}/program", headers=AUTH).json()["settings"]
    assert out["board_min_votes"] == 5 and out["card_order"] == "shuffled"


def test_program_readiness_and_counts(db):
    add_finalist(db, stage="finalist", photo_url="https://cdn.example/a.webp", cause="x", youtube_id="dQw4w9WgXcQ")
    add_finalist(db, stage="top5")
    add_finalist(db, stage="disqualified")
    out = client.get(f"{BASE}/program", headers=AUTH).json()
    assert out["counts"] == {"finalists": 2, "top5": 1, "winners": 0,
                             "missing_photo": 1, "missing_cause": 1, "missing_youtube": 1}
    ready = {r["key"]: r for r in out["readiness"]}
    assert set(ready) == {"turnstile", "finalists", "photos", "videos", "mail"}
    assert ready["turnstile"]["ok"] is False and ready["finalists"]["ok"] is True
    assert ready["photos"]["ok"] is False and ready["mail"]["ok"] is True
    assert out["production"] is False and out["stage"] and out["times"]["vote_closes"]


# -- Staff votes --------------------------------------------------------------

def test_votes_summary_counts_and_mail(db, mail):
    a, b = open_voting(db, "Ann", "Bea")
    confirmed_vote(a, "a1@example.com", mail)
    confirmed_vote(a, "a2@example.com", mail)
    vote(b, "b1@example.com")
    confirmed_vote(b, "b2@example.com", mail)
    client.post(f"{VOTES}/{row_for(db, 'b2@example.com').id}/void", headers=AUTH, json={"reason": "bot"})
    out = client.get(f"{VOTES}/summary", headers=AUTH).json()
    rows = {r["id"]: r for r in out["finalists"]}
    assert (rows[a.id]["confirmed"], rows[a.id]["pending"], rows[a.id]["void"]) == (2, 0, 0)
    assert (rows[b.id]["confirmed"], rows[b.id]["pending"], rows[b.id]["void"]) == (0, 1, 1)
    assert out["totals"] == {"confirmed": 2, "pending": 1, "void": 1}
    assert out["mail"] == {"queued": 0, "sent": 4, "failed": 0}


def test_summary_keeps_votes_of_a_disqualified_finalist(db, mail):
    a, = open_voting(db)
    confirmed_vote(a, "a1@example.com", mail)
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "disqualified"})
    assert client.get(f"{VOTES}/summary", headers=AUTH).json()["finalists"][0]["confirmed"] == 1


def _bulk_votes(db, finalist, emails, ip="198.51.100.9", **fields):
    now = datetime.now(tz=timezone.utc)
    for e in emails:
        db.add(CommunityStarVote(season=cs.SEASON, finalist_id=finalist.id, email=e,
                                 email_norm=vote_guard.normalize_email(e), ip=ip, created_at=now,
                                 status="pending", mail_status="sent", **fields))
    db.commit()


def test_flags_are_hints_for_staff(db):
    a = add_finalist(db)
    _bulk_votes(db, a, [f"unrelated{c}x@example.com" for c in "abcdefghij"])
    _bulk_votes(db, a, ["jane1@mail.example", "jane2@mail.example", "jane3@mail.example"], ip="198.51.100.10")
    now = datetime.now(tz=timezone.utc)
    _bulk_votes(db, a, ["quick@other.example"], ip="198.51.100.11", last_sent_at=now,
                confirmed_at=now + timedelta(seconds=2))
    flags = {f["kind"]: f for f in client.get(f"{VOTES}/summary", headers=AUTH).json()["flags"]}
    assert len(flags["ip_burst"]["vote_ids"]) == 10 and "198.51.100.9" in flags["ip_burst"]["label"]
    assert len(flags["fast_confirm"]["vote_ids"]) == 1
    assert len(flags["similar_email"]["vote_ids"]) == 3
    db.expire_all()
    assert db.query(CommunityStarVote).filter(CommunityStarVote.status == "void").count() == 0


def test_list_votes_filters_and_hides_the_token(db, mail):
    a, b = open_voting(db, "Ann", "Bea")
    confirmed_vote(a, "a1@example.com", mail)
    vote(b, "b1@example.com")
    rows = client.get(VOTES, headers=AUTH).json()
    assert len(rows) == 2 and "token_hash" not in rows[0]
    assert {r["finalist_name"] for r in rows} == {"Ann", "Bea"}
    assert [r["email"] for r in client.get(VOTES, headers=AUTH, params={"status": "pending"}).json()] == ["b1@example.com"]
    assert [r["email"] for r in client.get(VOTES, headers=AUTH, params={"finalist_id": a.id}).json()] == ["a1@example.com"]
    assert len(client.get(VOTES, headers=AUTH, params={"limit": 1}).json()) == 1
    assert client.get(VOTES, headers=AUTH, params={"status": "bogus"}).status_code == 422


def test_votes_csv_neutralises_formulas(db, mail):
    a, = open_voting(db)
    vote(a)
    client.post(f"{VOTES}/{row_for(db).id}/void", headers=AUTH, json={"reason": "=HYPERLINK(1)"})
    r = client.get(f"{BASE}/votes.csv", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "fan@example.com" in r.text and "'=HYPERLINK(1)" in r.text and "token" not in r.text


def test_void_needs_a_reason_and_records_who(db, mail):
    a, = open_voting(db)
    confirmed_vote(a, "fan@example.com", mail)
    row_id = row_for(db).id
    assert client.post(f"{VOTES}/{row_id}/void", headers=AUTH, json={"reason": "  "}).status_code == 400
    r = client.post(f"{VOTES}/{row_id}/void", headers=AUTH, json={"reason": "Temporary address"})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "void" and out["void_reason"] == "Temporary address"
    assert out["voided_by"] == "dashboard" and out["voided_at"]
    assert client.post(f"{VOTES}/{row_id}/void", headers=AUTH, json={"reason": "again"}).status_code == 409
    assert client.post(f"{VOTES}/999999/void", headers=AUTH, json={"reason": "x"}).status_code == 404


def test_restore_returns_the_vote_to_what_it_was(db, mail):
    a, = open_voting(db)
    confirmed_vote(a, "confirmed@example.com", mail)
    vote(a, "pending@example.com")
    for email, status in (("confirmed@example.com", "confirmed"), ("pending@example.com", "pending")):
        row_id = row_for(db, email).id
        assert client.post(f"{VOTES}/{row_id}/restore", headers=AUTH).status_code == 409
        client.post(f"{VOTES}/{row_id}/void", headers=AUTH, json={"reason": "check"})
        out = client.post(f"{VOTES}/{row_id}/restore", headers=AUTH).json()
        assert out["status"] == status and out["restored_by"] == "dashboard" and out["void_reason"] == "check"
    assert [r["name"] for r in feed()["board"]["rows"]] == ["Jane Doe"]


def test_voter_emails_stay_out_of_the_newsletter_and_partner_paths(db, mail):
    """Rule 15: the vote code writes to its own table and mails only the confirm."""
    source = Path(voting.__file__).read_text(encoding="utf-8") + Path(vote_outbox.__file__).read_text(encoding="utf-8")
    for word in ("newsletter", "brevo", "partner", "subscribe"):
        assert word not in source.lower()


# -- Outbox -------------------------------------------------------------------

def _queued(db, finalist, email="fan@example.com"):
    row = CommunityStarVote(season=cs.SEASON, finalist_id=finalist.id, email=email,
                            email_norm=vote_guard.normalize_email(email), status="pending", mail_status="queued",
                            mail_next_at=datetime.now(tz=timezone.utc))
    db.add(row)
    db.commit()
    return row


def _deadline():
    return datetime(2099, 1, 1, tzinfo=timezone.utc)


def _make_due(db, row):
    row.mail_next_at = datetime.now(tz=timezone.utc)
    db.commit()


def test_outbox_backs_off_then_fails(db, monkeypatch):
    a = add_finalist(db)
    row = _queued(db, a)
    tokens = []
    monkeypatch.setattr(mailer, "send_community_star_vote_confirm",
                        lambda to, name, link: tokens.append(link) or False)
    for minutes in vote_outbox.BACKOFF_MINUTES:
        before = datetime.now(tz=timezone.utc)
        assert vote_outbox.drain(db, _deadline()) == 1
        db.refresh(row)
        assert row.mail_status == "queued" and row.mail_last_error == "send failed"
        gap = (row.mail_next_at - before).total_seconds() / 60
        assert minutes - 0.1 < gap < minutes + 0.5
        assert vote_outbox.drain(db, _deadline()) == 0     # not due yet
        _make_due(db, row)
    assert vote_outbox.drain(db, _deadline()) == 1
    db.refresh(row)
    assert row.mail_status == "failed" and row.mail_attempts == 5 and row.sends == 0
    assert len(set(tokens)) == 5                            # every try made a new token
    assert row.status == "pending"                          # a failed mail never confirms a vote


def test_outbox_retry_succeeds_and_the_last_token_works(db, monkeypatch):
    a, = open_voting(db)
    row = _queued(db, a)
    attempts = []

    def flaky(to, name, link):
        attempts.append(link)
        return len(attempts) > 1

    monkeypatch.setattr(mailer, "send_community_star_vote_confirm", flaky)
    vote_outbox.drain(db, _deadline())
    _make_due(db, row)
    vote_outbox.drain(db, _deadline())
    db.refresh(row)
    assert row.mail_status == "sent" and row.sends == 1 and row.mail_next_at is None
    assert confirm(attempts[0].rsplit("=", 1)[1]).status_code == 404
    assert confirm(attempts[1].rsplit("=", 1)[1]).json() == {"status": "confirmed"}


def test_outbox_survives_a_raising_mailer(db, monkeypatch):
    a = add_finalist(db)
    row = _queued(db, a)

    def boom(*args):
        raise RuntimeError("smtp")

    monkeypatch.setattr(mailer, "send_community_star_vote_confirm", boom)
    assert vote_outbox.drain(db, _deadline()) == 1
    db.refresh(row)
    assert row.mail_status == "queued" and row.mail_attempts == 1


def test_outbox_skips_void_rows_and_stops_after_close(db, mail):
    a = add_finalist(db)
    row = _queued(db, a)
    row.status = "void"
    db.commit()
    assert vote_outbox.drain(db, _deadline()) == 0
    other = _queued(db, a, "other@example.com")
    assert vote_outbox.drain(db, datetime(2020, 1, 1, tzinfo=timezone.utc)) == 1
    db.refresh(other)
    assert other.mail_status == "failed" and mail == []


def test_outbox_claim_skips_a_locked_row(db, mail):
    a = add_finalist(db)
    _queued(db, a)
    other = SessionLocal()
    try:
        other.query(CommunityStarVote).with_for_update().all()
        assert vote_outbox.drain(db, _deadline()) == 0
    finally:
        other.rollback()
        other.close()
    assert vote_outbox.drain(db, _deadline()) == 1


def test_resend_during_a_send_keeps_the_newer_token(db, mail):
    a = add_finalist(db)
    row = _queued(db, a)
    claimed = vote_outbox._claim(db, _deadline())
    voting._requeue(row, datetime.now(tz=timezone.utc))
    db.commit()
    vote_outbox._finish(db, claimed[0], claimed[1], True)
    db.refresh(row)
    assert row.mail_status == "queued" and row.sends == 0 and row.token_hash is None


def test_vote_rush_holds_no_connection_during_the_send(db, monkeypatch):
    """More posts than the pool has connections, every mail stuck in the mailer.
    get_db closes after the background task, so a session left in a transaction
    would pin a connection each and the sends could never claim their rows."""
    posts = engine.pool.size() + engine.pool._max_overflow + 5
    a, = open_voting(db)
    finalist_id = a.id
    db.rollback()
    release = threading.Event()
    entered = threading.Semaphore(0)

    def held(to, name, link):
        entered.release()
        return release.wait(30)

    monkeypatch.setattr(mailer, "send_community_star_vote_confirm", held)

    def post(n):
        return client.post(VOTES, json={"finalistId": finalist_id, "email": f"fan{n}@example.com"}).status_code

    with ThreadPoolExecutor(max_workers=posts) as pool:
        futures = [pool.submit(post, n) for n in range(posts)]
        try:
            for _ in range(posts):
                assert entered.acquire(timeout=20), "a send never reached the mailer"
            assert engine.pool.checkedout() == 0
        finally:
            release.set()
        assert [f.result(timeout=30) for f in futures] == [200] * posts
    assert db.query(CommunityStarVote).filter(CommunityStarVote.mail_status == "sent").count() == posts


def test_vote_routes_stay_off_the_event_loop():
    for route in (voting.cast_vote, voting.preview_vote, voting.confirm_vote, voting.publish, voting.save_settings,
                  voting.dev_clock, voting.void_vote, voting.restore_vote, voting.reset_sends):
        assert not inspect.iscoroutinefunction(route), route.__name__


def test_a_mail_backlog_leaves_the_row_for_the_thread(db, mail, monkeypatch):
    a, = open_voting(db)
    monkeypatch.setattr(vote_outbox, "_next_slot", vote_outbox.time.monotonic() + 60)
    assert vote(a).status_code == 200
    assert mail == [] and row_for(db).mail_status == "queued"

    monkeypatch.setattr(vote_outbox, "_next_slot", 0.0)
    assert vote_outbox.drain(db, _deadline()) == 1
    assert len(mail) == 1


def test_outbox_thread_is_off_under_tests():
    with TestClient(app):
        assert vote_outbox._thread is None


def test_vote_mail_uses_the_shell(monkeypatch):
    sent = {}

    def fake(to, subject, text_body, html_body, preheader=""):
        sent.update(to=to, subject=subject, text=text_body, html=html_body)
        return True

    monkeypatch.setattr(mailer, "_send", fake)
    link = "https://niltv.com/communitystar/#confirm=abc"
    assert mailer.send_community_star_vote_confirm("fan@example.com", "Jane <b>Doe", link) is True
    assert sent["subject"] == "Confirm your NIL TV Community Star vote"
    assert link in sent["text"] and link in sent["html"]
    assert "Jane &lt;b&gt;Doe" in sent["html"] and "Confirm my vote" in sent["html"]


# -- Email checks -------------------------------------------------------------

@pytest.mark.parametrize("email, norm", [
    ("Jane.Doe+vote@GMail.com", "janedoe@gmail.com"),
    ("j.a.n.e@googlemail.com", "jane@gmail.com"),
    ("jane.doe+x@outlook.com", "jane.doe@outlook.com"),
    ("  fan@duke.edu ", "fan@duke.edu"),
])
def test_normalize_email(email, norm):
    assert vote_guard.normalize_email(email) == norm


def test_disposable_list_shipped_and_real_providers_are_not_on_it():
    domains = vote_guard.disposable_domains()
    assert len(domains) > 1000
    assert vote_guard.is_disposable("mailinator.com")
    for ok in ("gmail.com", "outlook.com", "yahoo.com", "icloud.com", "duke.edu", "niltv.com"):
        assert not vote_guard.is_disposable(ok)


class _Mx:
    def __init__(self, exchange):
        self.exchange = exchange


@pytest.mark.parametrize("mx, a, expected", [
    ([_Mx("mail.example.com.")], None, True),
    ([_Mx(".")], None, False),
    (dns.resolver.NXDOMAIN(), None, False),
    (dns.resolver.NoAnswer(), ["1.2.3.4"], True),
    (dns.resolver.NoAnswer(), dns.resolver.NoAnswer(), False),
    (dns.exception.Timeout(), None, True),
    (dns.resolver.NoNameservers(), None, True),
    (dns.resolver.NoAnswer(), dns.exception.Timeout(), True),
])
def test_mx_rejects_only_a_definite_no(monkeypatch, mx, a, expected):
    answers = {"MX": mx, "A": a}

    def lookup(resolver, domain, kind):
        assert resolver.lifetime == 2.0
        if isinstance(answers[kind], Exception):
            raise answers[kind]
        return answers[kind]

    monkeypatch.setattr(vote_guard, "_lookup", lookup)
    assert vote_guard._resolves_for_mail("example.com") is expected


def test_mx_results_are_cached(monkeypatch):
    monkeypatch.undo()
    calls = []
    monkeypatch.setattr(vote_guard, "_resolves_for_mail", lambda d: calls.append(d) or True)
    vote_guard._mx_cache.clear()
    assert vote_guard.has_mail_route("cache.example") and vote_guard.has_mail_route("cache.example")
    assert calls == ["cache.example"]
    vote_guard._mx_cache.clear()


# -- Sheet --------------------------------------------------------------------

class FakeSheet:
    """In-memory stand-in for the Sheets helpers the export job calls."""

    def __init__(self, monkeypatch, sheet_id="sheet-123"):
        self.tables = {}
        self.sid = sheet_id
        monkeypatch.setattr(get_settings(), "community_star_sheet_id", sheet_id)
        monkeypatch.setattr(export_job.sheets, "write_table", self.write_table)
        monkeypatch.setattr(export_job.sheets, "read_table", lambda sid, tab: self.tables.get((sid, tab), []))
        monkeypatch.setattr(export_job.sheets, "style_columns", lambda *a, **k: None)

    def write_table(self, sid, tab, header, rows):
        self.tables[(sid, tab)] = [list(header)] + [list(r) for r in rows]
        return len(rows)

    def tab(self, name):
        header, *rows = self.tables[(self.sid, name)]
        return [dict(zip(header, r)) for r in rows]

    def edit(self, row_id, column, value):
        table = self.tables[(self.sid, "Community Star")]
        c = table[0].index(column)
        for r in table[1:]:
            if r[0] == row_id:
                r[c] = value


def test_sheet_stage_locks_once_finalists_are_published(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    a = add_finalist(db)
    export_job.export_community_star(db)
    publish("finalists")
    sheet.edit(a.id, "Stage", "Disqualified")
    sheet.edit(a.id, "Notes", "Called the school")
    sheet.edit(a.id, "Collab accepted", True)
    export_job.export_community_star(db)
    db.refresh(a)
    assert a.stage == "finalist"
    assert a.notes == "Called the school" and a.collab_accepted is True
    assert sheet.tab("Community Star")[0]["Stage"] == "Finalist"


def test_sheet_stage_edit_still_works_before_publish(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    a = add_finalist(db, stage="shortlist")
    export_job.export_community_star(db)
    sheet.edit(a.id, "Stage", "Finalist")
    export_job.export_community_star(db)
    db.refresh(a)
    assert a.stage == "finalist"


def test_dashboard_stage_edit_still_works_after_publish(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    a = add_finalist(db)
    publish("finalists")
    export_job.export_community_star(db)
    client.post(f"{BASE}/applications/{a.id}/update", headers=AUTH, json={"stage": "top5"})
    export_job.export_community_star(db)
    db.refresh(a)
    assert a.stage == "top5" and sheet.tab("Community Star")[0]["Stage"] == "Top 5"


def test_votes_tab_after_publish_leaves_the_main_tab_alone(db, mail, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    a, = open_voting(db)
    export_job.export_community_star(db)
    assert sheet.tab("Votes")[0]["Confirmed"] == 0
    main_header = list(sheet.tables[("sheet-123", "Community Star")][0])
    confirmed_vote(a, "fan@example.com", mail)
    vote(a, "second@example.com")
    export_job.export_community_star(db)
    row = sheet.tab("Votes")[0]
    assert (row["ID"], row["Finalist"], row["Stage"]) == (a.id, "Jane Doe", "Finalist")
    assert (row["Confirmed"], row["Pending"], row["Void"]) == (1, 1, 0)
    assert sheet.tables[("sheet-123", "Community Star")][0] == main_header
    assert "Votes" not in main_header and "Confirmed" not in main_header
    assert not any("fan@example.com" in str(v) for v in row.values())


def test_no_votes_tab_before_publish(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    add_finalist(db)
    export_job.export_community_star(db)
    assert ("sheet-123", "Votes") not in sheet.tables


def test_votes_tab_failure_keeps_the_main_export(db, monkeypatch):
    sheet = FakeSheet(monkeypatch)
    add_finalist(db)
    publish("finalists")
    real = sheet.write_table

    def picky(sid, tab, header, rows):
        if tab == "Votes":
            raise export_job.sheets.SheetsError("quota")
        return real(sid, tab, header, rows)

    monkeypatch.setattr(export_job.sheets, "write_table", picky)
    assert export_job.export_community_star(db) == 1


# -- Photo --------------------------------------------------------------------

def _jpeg(width=1600, height=900, exif=True):
    img = Image.new("RGB", (width, height), (200, 30, 30))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010E] = "secret description"
        data[0x0112] = 1
        img.save(out, format="JPEG", exif=data)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture()
def s3(monkeypatch):
    calls = []

    class Fake:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: Fake())
    return calls


def _upload(app_id, data, name="photo.jpg", kind="image/jpeg"):
    return client.post(f"{BASE}/applications/{app_id}/photo", headers=AUTH, files={"file": (name, data, kind)})


def test_photo_is_square_webp_without_exif_on_the_cdn(db, s3):
    a = add_finalist(db)
    raw = _jpeg()
    assert Image.open(io.BytesIO(raw)).getexif()
    r = _upload(a.id, raw)
    assert r.status_code == 200, r.text
    call, = s3
    s = get_settings()
    assert call["Bucket"] == s.community_star_photo_bucket == "niltv-dev-video-hls-858321320457"
    assert re.fullmatch(rf"library/communitystar/finalists/{a.id}-[0-9a-f]{{12}}\.webp", call["Key"])
    assert call["ContentType"] == "image/webp" and "immutable" in call["CacheControl"]
    img = Image.open(io.BytesIO(call["Body"]))
    assert img.format == "WEBP" and img.size == (800, 800)
    assert not img.getexif() and b"secret description" not in call["Body"] and b"EXIF" not in call["Body"]
    url = f"https://d1nm1d2txb83wa.cloudfront.net/{call['Key']}"
    assert r.json()["photo_url"] == url and r.json()["application"]["photo_url"] == url
    db.refresh(a)
    assert a.photo_url == url and a.reviewed_by == "dashboard"


def test_photo_applies_exif_rotation():
    img = Image.new("RGB", (400, 800), (0, 0, 0))
    img.paste((255, 255, 255), (0, 0, 400, 400))     # top half white as stored
    out = io.BytesIO()
    data = Image.Exif()
    data[0x0112] = 6                                  # shown rotated 90 degrees clockwise
    img.save(out, format="JPEG", exif=data, quality=95)
    card = Image.open(io.BytesIO(card_photo.to_card_webp(out.getvalue()))).convert("L")
    assert card.getpixel((700, 400)) > 200 and card.getpixel((100, 400)) < 60


@pytest.mark.parametrize("data, needle", [
    (b"not an image", "JPEG, PNG or WebP"),
    (b"GIF89a" + b"0" * 50, "JPEG, PNG or WebP"),
    (b"\xff\xd8\xff\xe0broken", "JPEG, PNG or WebP"),
    (b"x" * (5 * 1024 * 1024 + 1), "5 MB"),
    (b"", "choose a photo"),
], ids=["text", "gif", "broken-jpeg", "too-big", "empty"])
def test_photo_refuses_bad_uploads(db, s3, data, needle):
    a = add_finalist(db)
    r = _upload(a.id, data)
    assert r.status_code == 400 and needle in r.json()["detail"]
    assert s3 == []
    db.refresh(a)
    assert a.photo_url is None


def test_photo_needs_a_row_and_reports_storage_failures(db, monkeypatch):
    assert _upload(999999, _jpeg()).status_code == 404
    a = add_finalist(db)

    def down(*args):
        raise RuntimeError("s3 denied secret-detail")

    monkeypatch.setattr(card_photo, "upload", down)
    r = _upload(a.id, _jpeg())
    assert r.status_code == 502 and "secret-detail" not in r.text


def test_photo_bucket_follows_the_environment():
    prod = get_settings().model_copy(update={"environment": "production", "community_star_photo_bucket": "",
                                             "community_star_photo_cdn": ""})
    prod.validate_environment()
    assert prod.community_star_photo_bucket == "niltv-prod-video-hls-858321320457"
    assert prod.community_star_photo_cdn == "https://dr60jt51m7xh2.cloudfront.net"


# -- Migration ----------------------------------------------------------------

def test_migration_runs_twice():
    path = Path(voting.__file__).resolve().parent.parent / "migrations" / "034_community_star_voting.sql"
    with engine.begin() as conn:
        conn.connection.cursor().execute(path.read_text(encoding="utf-8"))


def test_unique_vote_is_enforced_by_the_database(db):
    a = add_finalist(db)
    _queued(db, a)
    with pytest.raises(Exception, match="uq_community_star_vote_email"):
        _queued(db, a)
    db.rollback()


def test_feed_is_json_serialisable_when_empty(db):
    assert json.dumps(feed())
