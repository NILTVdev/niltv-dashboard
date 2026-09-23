"""Tests for the roster layer: sheet parsing/matching/import (migrations
023-024) and the new API surface (/summary, /snapshots, has_posts, roster
fields, filling a handle on a sheet-only row).

Runs in CI against the seeded Postgres.
"""

import io
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.jobs.ambassadors import attribute_posts, scan_welcome_posts
from backend.main import app
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    BrandAccount,
    BrandPost,
    NiltvNetworkPost,
    NiltvNetworkPostSnapshot,
)
from backend.jobs.ambassadors import campus_from_school, infer_campuses
from scripts.import_ambassador_sheet import import_rows, match_ambassador, parse_count, parse_sheet

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

SHEET = """NAME,SCHOOL,SPORT,YEAR (F26),Insta Followers,TikTok Followers,YouTube Subscribers,M/F,FOLLOWERS,,SCHOOLS
Jordan Sample,UNC chapel hill,Women's Soccer,Junior,"10,400","17,900",,F,Total:,junk,junk
Casey Example,SUNY Purchase,Men's Basketball,Freshman,3000,81 (Just created account),Didn't create yet,M,,,
Brand New Person,Somewhere State,Softball,Senior,"1,500",24.6k,N/A,F,,,
Brand New Person,Somewhere State,Softball,Senior,"1,600",24.6k,N/A,F,,,
"""


def _clean(db):
    db.query(NiltvNetworkPostSnapshot).delete()
    db.query(NiltvNetworkPost).delete()
    db.query(AmbassadorSnapshot).delete()
    db.query(Ambassador).delete()
    db.query(BrandPost).delete()
    db.query(BrandAccount).delete()
    db.commit()


# ── parse_count ─────────────────────────────────────────────────────────────

def test_parse_count_survey_mess():
    assert parse_count("39,900") == 39900
    assert parse_count("24.6k") == 24600
    assert parse_count("150 / 1700") == 1700
    assert parse_count("972- started a couple of months ago") == 972
    assert parse_count("371 on running account and 1,332 on main") == 1332
    assert parse_count("81 (Just created account)") == 81
    assert parse_count("0") == 0
    for empty in ("", "N/A", "Na", "none", "-", "will be starting one soon", None):
        assert parse_count(empty) is None, empty


# ── matching ────────────────────────────────────────────────────────────────

def _amb(username=None, display_name=None):
    a = Ambassador(ig_username=username, display_name=display_name)
    return a


def test_match_tiers():
    existing = [
        _amb("_jordansample"),
        _amb("7example"),
        _amb("pat_skater_44"),
        _amb(None, "Brand New Person"),
    ]
    row = lambda name: {"name": name, "name_key": "".join(c for c in name.lower() if c.isalpha())}

    a, tier = match_ambassador(row("Jordan Sample"), existing)
    assert a.ig_username == "_jordansample" and tier == "handle-contains"

    a, tier = match_ambassador(row("Casey Example"), existing)
    assert a.ig_username == "7example"  # "example" is contained in "caseyexample"

    a, tier = match_ambassador(row("Brand New Person"), existing)
    assert a.display_name == "Brand New Person" and tier == "exact-name"

    a, tier = match_ambassador(row("Totally Unknown"), existing)
    assert a is None and tier == "none"


def test_match_ambiguous_is_skipped():
    existing = [_amb("smithjones1"), _amb("smithjones2")]
    row = {"name": "Ann Smithjones", "name_key": "annsmithjones"}
    a, tier = match_ambassador(row, existing)
    assert a is None and tier == "ambiguous"


# ── import ──────────────────────────────────────────────────────────────────

def test_sheet_import_end_to_end():
    db = SessionLocal()
    try:
        _clean(db)
        db.add(Ambassador(ig_username="_jordansample", status="confirmed"))
        db.add(Ambassador(ig_username="7example", status="confirmed"))
        db.commit()

        rows, dupes = parse_sheet(io.StringIO(SHEET))
        assert dupes == 1  # Brand New Person listed twice, last wins
        assert len(rows) == 3

        report = import_rows(db, rows, cohort="F26")
        assert len(report["matched"]) == 2
        assert report["created"] == ["Brand New Person"]
        assert report["snapshots"] == 3

        jordan = db.query(Ambassador).filter(Ambassador.ig_username == "_jordansample").one()
        assert jordan.display_name == "Jordan Sample"
        assert jordan.school == "UNC chapel hill"
        assert jordan.cohort == "F26"
        snap = db.query(AmbassadorSnapshot).filter(
            AmbassadorSnapshot.ambassador_id == jordan.id, AmbassadorSnapshot.source == "reported"
        ).one()
        assert snap.followers == 10400 and snap.tiktok_followers == 17900

        new = db.query(Ambassador).filter(Ambassador.display_name == "Brand New Person").one()
        assert new.ig_username is None
        assert new.status == "confirmed" and new.source == "sheet_import"
        new_snap = db.query(AmbassadorSnapshot).filter(AmbassadorSnapshot.ambassador_id == new.id).one()
        assert new_snap.followers == 1600  # last duplicate row won
        assert new_snap.tiktok_followers == 24600

        # Re-import: idempotent — no new rows, no duplicate snapshots
        report2 = import_rows(db, rows, cohort="F26")
        assert report2["created"] == [] and report2["snapshots"] == 0
        assert db.query(Ambassador).count() == 3

        # Cohort update: person dropped from the sheet gets soft-retired
        report3 = import_rows(db, [r for r in rows if r["name"] != "Brand New Person"],
                              cohort="F26", deactivate_missing=True)
        assert report3["deactivated"] == ["Brand New Person"]
        db.refresh(new)
        assert new.active is False and new.status == "confirmed"  # history intact
    finally:
        db.close()


def test_weak_matches_are_held_for_review_and_second_claims_are_conflicts():
    db = SessionLocal()
    try:
        _clean(db)
        db.add(Ambassador(ig_username="grace_sample_ig", status="confirmed"))
        db.commit()
        sheet = SHEET.split("\n")[0] + "\n" + "\n".join([
            'Grace Alpha,Example University,Rowing,Junior,100,,,F,,,',
            'Grace Beta,Sample State University,Softball,Senior,200,,,F,,,',
            'Casey Example,SUNY Purchase,Men\'s Basketball,Freshman,300,,,M,,,',
        ]) + "\n"
        rows, _ = parse_sheet(io.StringIO(sheet))

        report = import_rows(db, rows, cohort="F26")
        # both Graces are first-name matches (score 50): held, not written, not created
        assert [(n, u) for n, u, _ in report["review"]] == [("Grace Alpha", "grace_sample_ig"),
                                                             ("Grace Beta", "grace_sample_ig")]
        assert report["created"] == ["Casey Example"] and report["matched"] == []
        grace = db.query(Ambassador).filter(Ambassador.ig_username == "grace_sample_ig").one()
        assert grace.display_name is None and grace.school is None

        # lowering the bar applies the first, and the second lands as a conflict
        report = import_rows(db, rows, cohort="F26", min_score=50)
        matched = [n for n, _, _ in report["matched"]]
        assert "Grace Alpha" in matched and "Casey Example" in matched   # Casey: created above, now exact
        assert [n for n, _, _ in report["conflict"]] == ["Grace Beta"]
        db.refresh(grace)
        assert grace.school == "Example University"
    finally:
        db.close()


def test_campus_falls_back_to_school_for_our_nodes_only():
    db = SessionLocal()
    try:
        _clean(db)
        db.add_all([
            BrandAccount(account="brazostv", username="brazostv", ig_user_id="1", campus="baylor"),
            BrandAccount(account="chapelhilltv", username="chapelhilltv", ig_user_id="2", campus="unc"),
        ])
        db.add_all([
            Ambassador(ig_username="a_baylor", status="confirmed", school="Baylor University"),
            Ambassador(ig_username="a_unc", status="confirmed", school="University of North Carolina at Chapel Hill"),
            Ambassador(ig_username="a_duke", status="confirmed", school="Duke University"),        # no duke channel seeded
            Ambassador(ig_username="a_louisville", status="confirmed", school="University of Louisville"),
            Ambassador(ig_username="a_manual", status="confirmed", school="Baylor", campus="vanderbilt",
                       campus_source="manual"),
        ])
        db.commit()
        assert infer_campuses(db) == 2
        got = {a.ig_username: a.campus for a in db.query(Ambassador).all()}
        assert got == {"a_baylor": "baylor", "a_unc": "unc", "a_duke": None, "a_louisville": None,
                       "a_manual": "vanderbilt"}
        assert campus_from_school("Texas A&M University", {"texas-am"}) == "texas-am"
        assert campus_from_school("Texas A&M University", set()) is None
        assert campus_from_school(None, {"baylor"}) is None
    finally:
        db.close()


def test_handleless_rows_are_safe_for_ingest():
    db = SessionLocal()
    try:
        _clean(db)
        db.add(Ambassador(display_name="No Handle Yet", status="confirmed"))
        db.add(BrandAccount(account="niltv", username="niltv", ig_user_id="1"))
        db.add(NiltvNetworkPost(post_id="p1", account_username="someone", collab_accounts="niltv", publish_time=NOW))
        db.add(BrandPost(account="niltv", ig_post_id="wp1", posted_at=NOW,
                         caption="Welcome our new ambassador @jane"))
        db.commit()
        # Neither pass blows up or misattributes with a NULL-handle row present
        assert attribute_posts(db) == 0
        scan_welcome_posts(db)
        assert db.query(Ambassador).count() == 2
    finally:
        db.close()


# ── API ─────────────────────────────────────────────────────────────────────

def test_summary_snapshots_and_handle_fill():
    db = SessionLocal()
    try:
        _clean(db)
        a = Ambassador(display_name="Sheet Only", status="confirmed", school="Duke",
                       sport="Softball", cohort="F26", cached_collab_posts=0)
        b = Ambassador(ig_username="poster", status="confirmed", cached_collab_posts=3,
                       cached_collab_views=100, cached_followers=50, campus="duke")
        db.add_all([a, b])
        db.commit()
        db.add(AmbassadorSnapshot(ambassador_id=a.id, pulled_at=NOW, source="reported",
                                  followers=1500, tiktok_followers=24600))
        db.add(NiltvNetworkPost(post_id="p1", account_username="sheet_only_handle", publish_time=NOW))
        db.commit()
        a_id, b_id = a.id, b.id
    finally:
        db.close()

    summary = client.get("/api/ambassadors/summary", headers=AUTH).json()
    assert summary["total"] == 2 and summary["with_handle"] == 1
    assert summary["with_posts"] == 1 and summary["collab_views"] == 100
    assert summary["campuses"] == {"duke": 1}

    # has_posts filter
    names = [x["ig_username"] for x in client.get("/api/ambassadors/", params={"has_posts": True}, headers=AUTH).json()]
    assert names == ["poster"]

    # roster fields + null handle serialize
    detail = client.get(f"/api/ambassadors/{a_id}", headers=AUTH).json()
    assert detail["ig_username"] is None and detail["school"] == "Duke" and detail["cohort"] == "F26"

    # snapshots trendline with source tag
    snaps = client.get(f"/api/ambassadors/{a_id}/snapshots", headers=AUTH).json()
    assert len(snaps) == 1
    assert snaps[0]["source"] == "reported" and snaps[0]["tiktok_followers"] == 24600

    # filling the handle on a sheet-only row attributes immediately
    r = client.post(f"/api/ambassadors/{a_id}/update",
                    json={"ig_username": "Sheet_Only_Handle"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ig_username"] == "sheet_only_handle"
    assert r.json()["previous_usernames"] is None  # no prior handle to trail
    posts = client.get(f"/api/ambassadors/{a_id}/posts", headers=AUTH).json()
    assert [p["post_id"] for p in posts] == ["p1"]

    # roster fields via update endpoint
    r = client.post(f"/api/ambassadors/{b_id}/update", json={"sport": "Basketball", "year": "Senior"}, headers=AUTH)
    assert r.json()["sport"] == "Basketball" and r.json()["year"] == "Senior"
