"""Functional tests for ambassador discovery, attribution, and the API.

Runs in CI against the seeded Postgres (migrations 020-022 already applied).
Covers:
  - welcome-caption parsing (regex, mention extraction, owned-handle exclusion)
  - single mention -> confirmed, several -> candidates, removed never resurrected
  - attribution stamping + campus inference + precomputed rollups
  - the /api/ambassadors endpoints (auth, admin add/update, posts merge)
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.jobs.ambassadors import (
    WELCOME_RE,
    attribute_posts,
    extract_mentions,
    infer_campuses,
    normalize_username,
    scan_welcome_posts,
)
from backend.jobs.precompute import precompute_ambassador_cache
from backend.main import app
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    BrandAccount,
    BrandPost,
    NiltvNetworkPost,
    NiltvNetworkPostSnapshot,
)

client = TestClient(app)
AUTH = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _clean(db):
    """Reset every table these tests seed (FK-safe order)."""
    db.query(NiltvNetworkPostSnapshot).delete()
    db.query(NiltvNetworkPost).delete()
    db.query(AmbassadorSnapshot).delete()
    db.query(Ambassador).delete()
    db.query(BrandPost).delete()
    db.query(BrandAccount).delete()
    db.commit()


def _seed_owned(db):
    """Register our own channels so their handles are never candidates."""
    db.add_all([
        BrandAccount(account="niltv", username="niltv", ig_user_id="1"),
        BrandAccount(account="truebluetv", username="trueblue_tv", ig_user_id="2", campus="duke"),
    ])
    db.commit()


def _welcome_post(db, caption, ig_post_id="wp1", account="niltv"):
    db.add(BrandPost(account=account, ig_post_id=ig_post_id, caption=caption, posted_at=NOW))
    db.commit()


# ── Pure parsing ────────────────────────────────────────────────────────────

def test_normalize_username():
    assert normalize_username("@Jane.Doe.") == "jane.doe"
    assert normalize_username("  @BOB_22 ") == "bob_22"
    assert normalize_username(None) == ""


def test_extract_mentions_dedupes_in_order():
    caption = "Welcome @Jane! So proud — @jane and @bob.smith. joined"
    assert extract_mentions(caption) == ["jane", "bob.smith"]


def test_welcome_regex_matches_real_announcements():
    for caption in (
        "Welcome our newest NILTV ambassador @jane_doe 🎉",
        "Our new ambassador @jd — welcome to the family!",
        "Please welcome ambassador @x",
        "AMBASSADOR ALERT 🚨 welcome @jane",
    ):
        assert WELCOME_RE.search(caption), caption


def test_welcome_regex_ignores_unrelated_captions():
    for caption in (
        "Welcome to Cameron Indoor Stadium",
        "Brand ambassador applications are open",
        "welcome back @superfan",
        "",
    ):
        assert not WELCOME_RE.search(caption), caption


# ── Welcome scan ────────────────────────────────────────────────────────────

def test_single_mention_confirms():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        _welcome_post(db, "Welcome our new ambassador @Jane.Doe 🎉 @niltv")
        scan_welcome_posts(db)

        rows = db.query(Ambassador).all()
        assert len(rows) == 1
        a = rows[0]
        assert a.ig_username == "jane.doe"  # normalized; owned @niltv excluded
        assert a.status == "confirmed"
        assert a.source == "welcome_post"
        assert a.welcome_post_id == "wp1"
        assert a.announced_at is not None

        # Idempotent: rescanning changes nothing
        scan_welcome_posts(db)
        assert db.query(Ambassador).count() == 1
    finally:
        db.close()


def test_multi_mention_creates_candidates():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        _welcome_post(db, "Welcome our new ambassadors @jane and @bob!")
        scan_welcome_posts(db)

        statuses = {a.ig_username: a.status for a in db.query(Ambassador).all()}
        assert statuses == {"jane": "candidate", "bob": "candidate"}
    finally:
        db.close()


def test_removed_never_resurrected_and_candidate_promoted():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        db.add(Ambassador(ig_username="gone", status="removed"))
        db.add(Ambassador(ig_username="jane", status="candidate"))
        db.commit()
        _welcome_post(db, "Welcome our new ambassador @gone", ig_post_id="wp_gone")
        _welcome_post(db, "Welcome our new ambassador @jane", ig_post_id="wp_jane")
        scan_welcome_posts(db)

        by_name = {a.ig_username: a for a in db.query(Ambassador).all()}
        assert by_name["gone"].status == "removed"          # admin removal is final
        assert by_name["jane"].status == "confirmed"        # clean post settles a candidate
        assert by_name["jane"].welcome_post_id == "wp_jane"
    finally:
        db.close()


# ── Attribution, campus inference, rollups ──────────────────────────────────

def _seed_network_post(db, post_id, author, collab="niltv", views=100, likes=10, comments=2):
    db.add(NiltvNetworkPost(
        post_id=post_id, account_username=author, collab_accounts=collab,
        publish_time=NOW, views=views, likes=likes, comments=comments,
        media_url="https://cdn.example/v.mp4", thumbnail_url="https://cdn.example/t.jpg",
    ))
    db.commit()


def test_attribution_campus_and_rollups():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        db.add(Ambassador(ig_username="jane.doe", status="confirmed"))
        db.commit()
        _seed_network_post(db, "p1", "Jane.Doe", collab="truebluetv")   # case-insensitive match
        _seed_network_post(db, "p2", "jane.doe", collab="niltv,truebluetv", views=50, likes=5)
        _seed_network_post(db, "p3", "someone_else")
        db.commit()

        assert attribute_posts(db) == 2  # p1, p2 — not p3
        a = db.query(Ambassador).filter(Ambassador.ig_username == "jane.doe").one()
        stamped = db.query(NiltvNetworkPost).filter(NiltvNetworkPost.ambassador_id == a.id).count()
        assert stamped == 2

        # Campus: both posts carried by truebluetv (campus=duke) -> duke
        assert infer_campuses(db) == 1
        db.refresh(a)
        assert a.campus == "duke"
        assert a.campus_source == "inferred"

        # Rollups from niltv_network_posts only (trueblue views excluded)
        precompute_ambassador_cache(db)
        db.refresh(a)
        assert a.cached_collab_posts == 2
        assert a.cached_collab_views == 150
        assert a.cached_collab_engagement == 10 + 2 + 5 + 2  # likes + comments across p1, p2

        # Attribution is idempotent
        assert attribute_posts(db) == 0
    finally:
        db.close()


def test_manual_campus_never_overwritten():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        db.add(Ambassador(ig_username="jane", status="confirmed", campus="unc", campus_source="manual"))
        db.commit()
        _seed_network_post(db, "p1", "jane", collab="truebluetv")
        attribute_posts(db)
        infer_campuses(db)
        a = db.query(Ambassador).filter(Ambassador.ig_username == "jane").one()
        assert a.campus == "unc"
        assert a.campus_source == "manual"
    finally:
        db.close()


# ── API ─────────────────────────────────────────────────────────────────────

def test_endpoints_require_key():
    assert client.get("/api/ambassadors/").status_code in (401, 422)
    assert client.get("/api/ambassadors/", headers={"X-API-Key": "wrong"}).status_code == 401


def test_admin_add_attributes_immediately():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_owned(db)
        _seed_network_post(db, "p1", "jane", collab="truebluetv")
    finally:
        db.close()

    r = client.post("/api/ambassadors/", json={"ig_username": "@Jane", "campus": "duke"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ig_username"] == "jane"
    assert body["status"] == "confirmed"
    assert body["campus"] == "duke"
    assert body["campus_source"] == "manual"

    posts = client.get(f"/api/ambassadors/{body['id']}/posts", headers=AUTH).json()
    assert [p["post_id"] for p in posts] == ["p1"]
    assert posts[0]["source"] == "niltv_network"
    assert posts[0]["media_url"] is not None


def test_list_filters_and_update_flow():
    db = SessionLocal()
    try:
        _clean(db)
        db.add_all([
            Ambassador(ig_username="a_confirmed", status="confirmed"),
            Ambassador(ig_username="b_candidate", status="candidate"),
            Ambassador(ig_username="c_removed", status="removed"),
        ])
        db.commit()
    finally:
        db.close()

    names = [a["ig_username"] for a in client.get("/api/ambassadors/", headers=AUTH).json()]
    assert names == ["a_confirmed", "b_candidate"]  # active excludes removed, confirmed first
    only_candidates = client.get("/api/ambassadors/", params={"status": "candidate"}, headers=AUTH).json()
    assert [a["ig_username"] for a in only_candidates] == ["b_candidate"]
    assert client.get("/api/ambassadors/", params={"status": "bogus"}, headers=AUTH).status_code == 400

    amb_id = only_candidates[0]["id"]
    r = client.post(f"/api/ambassadors/{amb_id}/update",
                    json={"status": "confirmed", "campus": "duke"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
    assert r.json()["campus_source"] == "manual"

    # Clearing campus re-opens inference
    r = client.post(f"/api/ambassadors/{amb_id}/update", json={"campus": None}, headers=AUTH)
    assert r.json()["campus"] is None
    assert r.json()["campus_source"] == "inferred"

    # Rename keeps a trail; renaming onto an existing handle conflicts
    r = client.post(f"/api/ambassadors/{amb_id}/update", json={"ig_username": "@B_New"}, headers=AUTH)
    assert r.json()["ig_username"] == "b_new"
    assert "b_candidate" in r.json()["previous_usernames"]
    conflict = client.post(f"/api/ambassadors/{amb_id}/update",
                           json={"ig_username": "a_confirmed"}, headers=AUTH)
    assert conflict.status_code == 409

    assert client.post(f"/api/ambassadors/{amb_id}/update",
                       json={"status": "bogus"}, headers=AUTH).status_code == 400
    assert client.post(f"/api/ambassadors/{amb_id}/update",
                       json={"athlete_id": 999999}, headers=AUTH).status_code == 400
