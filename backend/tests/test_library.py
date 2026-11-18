"""Content library: the app's sync contract, search, filters, the view join
and role access. Uses the fake snapshot in fixtures/library_sync_sample.json."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import accounts
from backend.database import SessionLocal
from backend.main import app
from backend.models import DashboardUser, LibraryItem, LibrarySyncRun, NiltvNetworkPost

client = TestClient(app)
KEY = {"X-API-Key": "test"}
SYNC = "/api/library/sync"
LIST = "/api/library/"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "library_sync_sample.json").read_text(encoding="utf-8"))
POST_IDS = [f"178000000000000{n:02d}" for n in range(1, 13)]
TEST_EMAILS = ("library-general@example.com", "library-demo@example.com", "library-admin@example.com")


def _clean(db):
    db.query(LibraryItem).delete()
    db.query(LibrarySyncRun).delete()
    db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id.in_(POST_IDS)).delete(synchronize_session=False)
    db.query(DashboardUser).filter(DashboardUser.email.in_(TEST_EMAILS)).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    _clean(session)
    session.close()


def snapshot(**changes) -> dict:
    body = copy.deepcopy(FIXTURE)
    body.update(changes)
    return body


def sync(body) -> dict:
    r = client.post(SYNC, headers=KEY, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def ids(params: dict | None = None) -> list[str]:
    r = client.get(LIST, headers=KEY, params={"limit": 200, **(params or {})})
    assert r.status_code == 200, r.text
    return [i["content_id"] for i in r.json()["items"]]


def ig(n: int) -> str:
    return f"ig-178000000000000{n:02d}"


@pytest.fixture()
def seeded(db):
    """The fixture snapshot plus Instagram rows for a few of its clips."""
    sync(FIXTURE)
    db.add_all([
        NiltvNetworkPost(post_id=POST_IDS[0], views=12000, likes=800, comments=40, shares=10, saves=5,
                         permalink="https://www.instagram.com/reel/FAKE0001/"),
        # Pulled, but no counts yet: matched, every number unknown.
        NiltvNetworkPost(post_id=POST_IDS[1]),
        # A real zero stays a zero.
        NiltvNetworkPost(post_id=POST_IDS[2], views=0, likes=0, comments=0, shares=0, saves=0),
        NiltvNetworkPost(post_id=POST_IDS[7], views=5000, likes=900, comments=60, shares=30, saves=20),
    ])
    db.commit()
    return db


# ── Sync ──────────────────────────────────────────────────────────────────────

def test_sync_upserts_and_is_idempotent(db):
    n = len(FIXTURE["items"])
    assert sync(FIXTURE) == {"received": n, "upserted": n, "removed": 0}
    first_seen = db.execute(text("SELECT first_seen_at FROM library_items WHERE content_id = :c"),
                            {"c": ig(1)}).scalar()

    body = snapshot()
    body["items"][0]["title"] = "Renamed by staff"
    assert sync(body) == {"received": n, "upserted": n, "removed": 0}
    assert db.query(LibraryItem).count() == n
    row = db.execute(text("SELECT title, first_seen_at, last_synced_at FROM library_items WHERE content_id = :c"),
                     {"c": ig(1)}).one()
    assert row.title == "Renamed by staff"
    assert row.first_seen_at == first_seen
    runs = db.query(LibrarySyncRun).order_by(LibrarySyncRun.id).all()
    assert [(r.ok, r.received, r.upserted, r.removed, r.stage) for r in runs] == [(True, n, n, 0, "dev")] * 2


def test_sync_keeps_nulls_and_empty_lists(db):
    sync(FIXTURE)
    bare = client.get("/api/library/upload-sample-05", headers=KEY).json()
    assert bare["channel_id"] is None and bare["posted_at"] is None and bare["qc_state"] is None
    assert bare["keywords"] == [] and bare["athletes"] == [] and bare["unresolved_handles"] == ["unknown_fan_account"]
    assert bare["performance"] == {"matched": False, "views": None, "likes": None, "comments": None,
                                   "shares": None, "saves": None, "reach": None, "interactions": None,
                                   "permalink": None}


def test_full_snapshot_marks_missing_rows_removed_for_its_stage_only(db):
    sync(FIXTURE)
    prod_item = copy.deepcopy(FIXTURE["items"][0]) | {"content_id": "prod-only-clip", "ig_post_id": None}
    sync(snapshot(stage="prod", full=False, items=[prod_item]))

    body = snapshot()
    body["items"] = [i for i in body["items"] if i["content_id"] not in (ig(1), ig(2))]
    assert sync(body)["removed"] == 2
    removed = {r.content_id for r in db.query(LibraryItem).filter(LibraryItem.removed.is_(True))}
    assert removed == {ig(1), ig(2)}  # the prod row is not part of the dev snapshot

    assert ig(1) not in ids()
    assert ig(1) in ids({"include_removed": "true"})
    assert sync(body)["removed"] == 0  # already removed

    # A partial sync never removes anything.
    assert sync(snapshot(full=False, items=[FIXTURE["items"][3]]))["removed"] == 0

    # Sent again, a removed clip comes back.
    sync(FIXTURE)
    assert ig(1) in ids()
    assert db.query(LibraryItem).filter(LibraryItem.removed.is_(True)).count() == 0


def test_repeated_content_id_in_one_snapshot_keeps_the_last(db):
    a = copy.deepcopy(FIXTURE["items"][0])
    b = a | {"title": "Second copy wins"}
    assert sync(snapshot(items=[a, b])) == {"received": 2, "upserted": 1, "removed": 0}
    assert client.get(f"/api/library/{ig(1)}", headers=KEY).json()["title"] == "Second copy wins"


def test_sync_refuses_more_than_5000_items(db):
    item = {"content_id": "x", "title": "x", "status": "published"}
    items = [item | {"content_id": f"bulk-{n}"} for n in range(5001)]
    r = client.post(SYNC, headers=KEY, json=snapshot(items=items))
    assert r.status_code == 413
    assert db.query(LibraryItem).count() == 0
    run = db.query(LibrarySyncRun).one()
    assert run.ok is False and run.received == 5001 and run.stage == "dev"


@pytest.mark.parametrize("mutate", [
    lambda b: b.pop("stage"),
    lambda b: b.update(stage="staging"),
    lambda b: b.update(items="not a list"),
    lambda b: b.update(generated_at="yesterday"),
    lambda b: b["items"][0].pop("content_id"),
    lambda b: b["items"][0].update(title=None),
    lambda b: b["items"][0].update(athletes=["not an object"]),
    lambda b: b["items"][0].update(posted_at="soon"),
])
def test_sync_refuses_an_invalid_body(db, mutate):
    body = snapshot()
    mutate(body)
    r = client.post(SYNC, headers=KEY, json=body)
    assert r.status_code == 400, r.text
    assert db.query(LibraryItem).count() == 0
    assert db.query(LibrarySyncRun).one().ok is False


def test_sync_refuses_non_json(db):
    r = client.post(SYNC, headers={**KEY, "Content-Type": "application/json"}, content=b"{not json")
    assert r.status_code == 400
    assert client.post(SYNC, headers=KEY, json=[1, 2]).status_code == 400


def test_sync_strips_nul_characters_instead_of_failing(db):
    body = snapshot()
    item = body["items"][0]
    item["caption"] = "bad \u0000 nul"
    item["keywords"] = ["hoops\u0000"]
    item["athletes"] = [{"id": "ath-nul", "name": "Nul\u0000 Sample", "handle": "nul_\u0000sample"}]
    assert sync(body)["upserted"] == len(FIXTURE["items"])
    got = client.get(f"/api/library/{ig(1)}", headers=KEY).json()
    assert got["caption"] == "bad  nul"
    assert got["keywords"] == ["hoops"]
    assert got["athletes"][0] == {"id": "ath-nul", "name": "Nul Sample", "handle": "nul_sample",
                                  "directory_key": None}


def test_sync_ignores_unknown_fields_and_reads_null_lists_as_empty(db):
    body = snapshot(extra_top_level="ignored")
    body["items"][0]["future_field"] = {"anything": 1}
    body["items"][0]["keywords"] = None
    assert sync(body)["upserted"] == len(FIXTURE["items"])
    assert client.get(f"/api/library/{ig(1)}", headers=KEY).json()["keywords"] == []


# ── Search ────────────────────────────────────────────────────────────────────

def test_title_hit_ranks_above_caption_hit(seeded):
    found = ids({"q": "basketball"})
    assert ig(3) in found and ig(2) in found
    assert found.index(ig(3)) < found.index(ig(2))  # title (A) vs caption (C)
    assert found[0] == ig(3)


def test_partial_words_match_by_prefix(seeded):
    assert set(ids({"q": "basketb"})) >= {ig(1), ig(2), ig(3)}
    assert set(ids({"q": "jsampl"})) == {ig(1), ig(3)}  # athlete handle
    assert set(ids({"q": "Volleyb capt"})) == {"yt-sample-video-04"}


def test_websearch_exclusion_and_phrases_are_not_widened_by_prefix(seeded):
    everything = set(ids())
    basketball = set(ids({"q": "basketball"}))
    assert basketball and basketball < everything
    excluded = set(ids({"q": "-basketball"}))
    assert excluded == everything - basketball
    assert set(ids({"q": "games -basketball"})).isdisjoint(basketball)
    # A quoted phrase is matched as a phrase, not as an AND of word prefixes.
    assert ids({"q": '"basketb"'}) == []


def test_prefix_tsquery_skips_websearch_syntax():
    from backend.routers.library import prefix_tsquery
    assert prefix_tsquery("Duke basketb") == "duke:* & basketb:*"
    assert prefix_tsquery("x-ray drills") == "x:* & ray:* & drills:*"
    assert prefix_tsquery("-basketball") is None
    assert prefix_tsquery("duke -lacrosse") is None
    assert prefix_tsquery('"camp day"') is None
    assert prefix_tsquery("duke or unc") is None
    assert prefix_tsquery("orange") == "orange:*"
    assert prefix_tsquery("!!!") is None


def test_search_covers_stems_athletes_tags_and_unresolved_handles(seeded):
    assert ig(1) in ids({"q": "games"})                      # stemmed "game"
    assert set(ids({"q": "Casey Placeholder"})) == {ig(2), ig(9)}
    assert set(ids({"q": "Example Drinks"})) == {"yt-sample-video-04", ig(8)}
    assert ids({"q": "unknown_fan_account"}) == ["upload-sample-05"]
    assert ids({"q": "zzzz nothing matches"}) == []


# ── Filters ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("params,expected", [
    ({"sport": "Basketball"}, {ig(1), ig(3)}),
    ({"school": "Sample Tech"}, {"yt-sample-video-04", ig(8), ig(12)}),
    ({"channel": "ch-campus-sample"}, {"yt-sample-video-04"}),
    ({"content_type": "interview"}, {"yt-sample-video-04"}),          # single field only
    ({"content_type": "behind-the-scenes"}, {ig(2)}),                 # list only
    ({"category": "Features"}, {ig(8), ig(11)}),
    ({"sponsor": "Example Drinks Co"}, {"yt-sample-video-04", ig(8)}),
    ({"athlete": "@JSample_Hoops"}, {ig(1), ig(3)}),
    ({"athlete": "ath-test-002"}, {ig(2), ig(9)}),
    ({"qc_state": "needs-review"}, {"yt-sample-video-04", ig(10)}),
    ({"needs_tagging": "true"}, {"yt-sample-video-04", "upload-sample-05", ig(7), ig(10)}),
    ({"posted_from": "2026-10-15", "posted_to": "2026-10-20"}, {ig(1), ig(2), ig(3)}),
    ({"has_video": "false"}, {"yt-sample-video-04", "upload-sample-05", ig(12)}),
    ({"sport": "Basketball", "q": "camp"}, {ig(3)}),
])
def test_filters(seeded, params, expected):
    assert set(ids(params)) == expected


def test_has_video_true_and_paging(seeded):
    assert len(ids({"has_video": "true"})) == len(FIXTURE["items"]) - 3
    r = client.get(LIST, headers=KEY, params={"limit": 5, "offset": 10}).json()
    assert r["total"] == len(FIXTURE["items"]) and len(r["items"]) == 2


def test_sorts(seeded):
    newest = ids({"sort": "newest"})
    assert newest[0] == ig(11) and newest[-1] == "upload-sample-05"  # no date goes last
    assert ids({"sort": "views"})[:3] == [ig(1), ig(8), ig(3)]
    assert ids({"sort": "engaged"})[:3] == [ig(8), ig(1), ig(3)]
    assert ids() == newest  # default without q


# ── View join ─────────────────────────────────────────────────────────────────

def test_performance_is_null_when_unknown_and_zero_when_zero(seeded):
    perf = {i["content_id"]: i["performance"] for i in
            client.get(LIST, headers=KEY, params={"limit": 200}).json()["items"]}
    assert perf[ig(1)] == {"matched": True, "views": 12000, "likes": 800, "comments": 40, "shares": 10,
                                "saves": 5, "reach": None, "interactions": 855,
                                "permalink": "https://www.instagram.com/reel/FAKE0001/"}
    assert perf[ig(2)]["matched"] is True and perf[ig(2)]["views"] is None and perf[ig(2)]["interactions"] is None
    assert perf[ig(3)]["views"] == 0 and perf[ig(3)]["interactions"] == 0
    assert perf[ig(9)]["matched"] is False and perf[ig(9)]["views"] is None   # IG id, not pulled yet
    assert perf["yt-sample-video-04"]["matched"] is False                     # not from Instagram


def test_detail_and_404(seeded):
    r = client.get(f"/api/library/{ig(1)}", headers=KEY)
    assert r.status_code == 200
    body = r.json()
    # No directory person has that handle, so no Athletes page link.
    assert body["athletes"] == [{"id": "ath-test-001", "name": "Jordan Sample", "handle": "jsample_hoops",
                                 "directory_key": None}]
    assert body["performance"]["views"] == 12000
    assert client.get("/api/library/no-such-clip", headers=KEY).status_code == 404


# ── Facets and status ─────────────────────────────────────────────────────────

def _facet(params, name):
    r = client.get("/api/library/facets", headers=KEY, params=params)
    assert r.status_code == 200, r.text
    return {f["value"]: f["count"] for f in r.json()[name]}


def test_facets_count_under_the_other_filters(seeded):
    assert _facet({}, "sport") == {"Basketball": 2, "Football": 2, "Soccer": 1, "Volleyball": 1,
                                   "Lacrosse": 1, "Track and Field": 1, "Swimming": 1}
    # A facet's own selection does not hide its other values ...
    assert _facet({"sport": "Basketball"}, "sport")["Soccer"] == 1
    # ... but it narrows the other facets.
    assert _facet({"sport": "Basketball"}, "school") == {"Fake State University": 2}
    assert _facet({}, "content_type")["interview"] == 1
    assert _facet({}, "category")["Game Day"] == 4
    channels = client.get("/api/library/facets", headers=KEY).json()["channel"]
    assert {"value": "ch-campus-sample", "label": "Sample Campus TV", "count": 1} in channels
    assert _facet({"q": "basketb"}, "school") == {"Fake State University": 2, "Example College": 1}


def test_status_before_and_after_sync(db):
    s = client.get("/api/library/status", headers=KEY).json()
    assert s["last_run"] is None and s["items"] == 0 and s["needs_tagging"] == 0

    sync(FIXTURE)
    s = client.get("/api/library/status", headers=KEY).json()
    assert s["last_run"]["ok"] is True and s["last_ok_run"]["id"] == s["last_run"]["id"]
    assert s["items"] == len(FIXTURE["items"]) and s["removed"] == 0
    assert s["needs_tagging"] == 4
    assert {q["qc_state"]: q["count"] for q in s["by_qc_state"]} == {
        "ready": 8, "needs-review": 2, "needs-tagging": 1, None: 1}

    client.post(SYNC, headers=KEY, json={"stage": "dev"})
    s = client.get("/api/library/status", headers=KEY).json()
    assert s["last_run"]["ok"] is False and s["last_ok_run"]["ok"] is True


# ── Access ────────────────────────────────────────────────────────────────────

def _user(db, email, role):
    u = DashboardUser(email=email, name="Library Test", role=role,
                      password_hash=accounts.hash_password("library test password"), active=True)
    db.add(u)
    db.commit()
    return {**KEY, "X-Dashboard-User": str(u.id), "X-Dashboard-Session-Version": str(u.session_version or 1)}


def test_role_access(db):
    general = _user(db, TEST_EMAILS[0], "general")
    demo = _user(db, TEST_EMAILS[1], "demo")
    admin = _user(db, TEST_EMAILS[2], "admin")

    for path in (LIST, "/api/library/facets", "/api/library/status"):
        assert client.get(path, headers=general).status_code == 200
        assert client.get(path, headers=demo).status_code == 403
    assert client.get("/api/library/anything", headers=demo).status_code == 403

    assert client.post(SYNC, headers=general, json=FIXTURE).status_code == 403
    assert client.post(SYNC, headers=demo, json=FIXTURE).status_code == 403
    assert db.query(LibraryItem).count() == 0
    assert client.post(SYNC, headers=admin, json=FIXTURE).status_code == 200
    assert client.post(SYNC, headers=KEY, json=FIXTURE).status_code == 200   # service caller (ingest)
    assert client.post(SYNC, json=FIXTURE).status_code == 401
    assert client.get(LIST).status_code == 401
