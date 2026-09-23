"""One truth per network post (migration 026 + import_niltv_network rules):

* views obey source rank — graph > export > public — so a snapshot upload fills
  holes but never overwrites Graph/export numbers, and an export replaces
  public counts;
* every writer lands on the canonical post_type vocabulary, and a specific
  label upgrades a generic one;
* channel tags come from the --account stamp AND from owner/co-author handles
  mapped through brand_accounts;
* the TrueBlue page and the ambassador posts endpoint read the shared table,
  so a post is never listed twice.
Runs in CI against the seeded Postgres.
"""

import csv
import io
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.jobs.import_niltv_network import (
    SOURCE_EXPORT,
    SOURCE_GRAPH,
    SOURCE_PUBLIC,
    detect_csv_source,
    normalize_post_type,
    upsert_posts,
)
from backend.main import app
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    BrandAccount,
    NiltvNetworkPost,
    NiltvNetworkPostSnapshot,
)

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
T0 = datetime(2026, 9, 10, 1, 45, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 10, 14, 35, tzinfo=timezone.utc)   # same UTC day, later
T2 = datetime(2026, 9, 11, 1, 45, tzinfo=timezone.utc)
REEL = "18000000000000201"
SC = "DOneTruth01"
PERMALINK = f"https://www.instagram.com/reel/{SC}/"


def _clean(db):
    rows = db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id.like("1800000000000020%")).all()
    if rows:
        db.query(NiltvNetworkPostSnapshot).filter(
            NiltvNetworkPostSnapshot.network_post_id.in_([r.id for r in rows])
        ).delete(synchronize_session=False)
        db.query(NiltvNetworkPost).filter(NiltvNetworkPost.id.in_([r.id for r in rows])).delete(
            synchronize_session=False)
    db.query(AmbassadorSnapshot).delete()
    db.query(Ambassador).filter(Ambassador.ig_username == "onetruth.athlete").delete(synchronize_session=False)
    db.query(BrandAccount).filter(BrandAccount.account.in_(["truebluetv", "dorecitytv"])).delete(
        synchronize_session=False)
    db.commit()


def _seed_registry(db):
    db.add_all([
        BrandAccount(account="truebluetv", username="trueblue_tv", ig_user_id="17841400000000001",
                     api="bd", campus="duke", network_pull=False, active=False),
        BrandAccount(account="dorecitytv", username="dorecitytv", ig_user_id="3", api="fb",
                     campus="vanderbilt", network_pull=True, active=True),
    ])
    db.commit()


def _row(post_id, **over):
    base = {
        "post_id": post_id, "account_username": "onetruth.athlete", "account_name": None,
        "description": "collab reel", "duration_sec": None, "publish_time": T0,
        "permalink": PERMALINK, "post_type": "REELS", "media_url": None, "thumbnail_url": None,
        "collab_accounts": "niltv", "views": None, "likes": None, "shares": None,
        "comments": None, "saves": None, "reach": None, "follows": None,
    }
    base.update(over)
    return base


def test_normalize_post_type_covers_every_feed():
    assert normalize_post_type("REELS", "VIDEO") == "REELS"
    assert normalize_post_type("FEED", "IMAGE") == "IMAGE"
    assert normalize_post_type("FEED", "CAROUSEL_ALBUM") == "CAROUSEL_ALBUM"
    assert normalize_post_type("FEED", "VIDEO") == "VIDEO"
    assert normalize_post_type("FEED") == "FEED"                 # legacy generic, upgraded later
    assert normalize_post_type("IG reel") == "REELS"
    assert normalize_post_type("IG Reels") == "REELS"
    assert normalize_post_type("IG carousel") == "CAROUSEL_ALBUM"
    assert normalize_post_type("IG image") == "IMAGE"
    assert normalize_post_type("IG video") == "VIDEO"
    assert normalize_post_type(None, "IMAGE") == "IMAGE"         # Business Discovery: media_type only
    assert normalize_post_type("Story") == "Story"               # unknown labels pass through
    assert normalize_post_type(None) is None


def test_detect_csv_source():
    assert detect_csv_source("public grid snapshot; co-authors: niltv") == SOURCE_PUBLIC
    assert detect_csv_source("") == SOURCE_EXPORT
    assert detect_csv_source(None) == SOURCE_EXPORT


def test_views_rank_public_never_overwrites_graph_but_export_replaces_public():
    db = SessionLocal()
    try:
        _clean(db)
        # Night 1: Graph pull writes the reel.
        upsert_posts(db, [_row(REEL, views=2_500_000, likes=100)], captured_at=T0, source=SOURCE_GRAPH)
        p = db.query(NiltvNetworkPost).filter_by(post_id=REEL).one()
        assert (p.views, p.views_source) == (2_500_000, "graph")

        # Same day: the public play count must NOT land on views,
        # but its public likes/comments do.
        upsert_posts(db, [_row(REEL, views=1_600_000, likes=101, comments=9, collab_accounts="truebluetv")],
                     captured_at=T1, source=SOURCE_PUBLIC)
        db.refresh(p)
        assert (p.views, p.views_source) == (2_500_000, "graph")
        assert p.likes == 101 and p.comments == 9
        assert p.collab_accounts == "niltv,truebluetv"          # tags union
        assert db.query(NiltvNetworkPostSnapshot).filter_by(network_post_id=p.id).count() == 1  # one per UTC day

        # Export (Business Suite) may not overwrite Graph views either, but it
        # fills the export-only metrics.
        upsert_posts(db, [_row(REEL, views=2_400_000, shares=40, saves=12, reach=900_000)],
                     captured_at=T2, source=SOURCE_EXPORT)
        db.refresh(p)
        assert (p.views, p.views_source) == (2_500_000, "graph")
        assert (p.shares, p.saves, p.reach) == (40, 12, 900_000)

        # A snapshot-only post: the public count fills the hole, then the export replaces it.
        only = REEL[:-1] + "2"
        upsert_posts(db, [_row(only, permalink=None, views=300, collab_accounts="truebluetv")],
                     captured_at=T0, source=SOURCE_PUBLIC)
        q = db.query(NiltvNetworkPost).filter_by(post_id=only).one()
        assert (q.views, q.views_source) == (300, "public")
        upsert_posts(db, [_row(only, permalink=None, views=900)], captured_at=T2, source=SOURCE_EXPORT)
        db.refresh(q)
        assert (q.views, q.views_source) == (900, "export")
        # ...and a public count cannot pull it back down afterwards.
        upsert_posts(db, [_row(only, permalink=None, views=310)], captured_at=T2, source=SOURCE_PUBLIC)
        db.refresh(q)
        assert (q.views, q.views_source) == (900, "export")
        # A Graph value replaces the export value.
        upsert_posts(db, [_row(only, permalink=None, views=950)], captured_at=T2, source=SOURCE_GRAPH)
        db.refresh(q)
        assert (q.views, q.views_source) == (950, "graph")
    finally:
        _clean(db)
        db.close()


def test_post_type_is_normalised_and_only_upgrades():
    db = SessionLocal()
    try:
        _clean(db)
        pid = REEL[:-1] + "3"
        # Legacy Graph FEED label first (no media_type known).
        upsert_posts(db, [_row(pid, permalink=None, post_type="FEED")], captured_at=T0, source=SOURCE_GRAPH)
        p = db.query(NiltvNetworkPost).filter_by(post_id=pid).one()
        assert p.post_type == "FEED"
        # A Business Suite row says carousel: upgrade.
        upsert_posts(db, [_row(pid, permalink=None, post_type="IG carousel")], captured_at=T1, source=SOURCE_EXPORT)
        db.refresh(p)
        assert p.post_type == "CAROUSEL_ALBUM"
        # A later row with a different specific label does not flip it.
        upsert_posts(db, [_row(pid, permalink=None, post_type="IG image")], captured_at=T2, source=SOURCE_PUBLIC)
        db.refresh(p)
        assert p.post_type == "CAROUSEL_ALBUM"
        # Graph rows carry media_type so FEED splits on insert.
        pid2 = REEL[:-1] + "4"
        upsert_posts(db, [dict(_row(pid2, permalink=None, post_type="FEED"), _media_type="IMAGE")],
                     captured_at=T0, source=SOURCE_GRAPH)
        assert db.query(NiltvNetworkPost).filter_by(post_id=pid2).one().post_type == "IMAGE"
    finally:
        _clean(db)
        db.close()


def _csv_bytes(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Post ID", "Account ID", "Account username", "Account name", "Description", "Duration (sec)",
                "Publish time", "Permalink", "Post type", "Data comment", "Date", "Views", "Likes", "Shares",
                "Comments", "Saves", "Reach", "Follows"])
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def test_owner_and_coauthor_handles_become_channel_tags_and_one_table_serves_every_screen():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_registry(db)
        pid = REEL[:-1] + "5"
        # Snapshot CSV of the TrueBlueTV grid: owner is the athlete, co-authors
        # include @trueblue_tv (registry username) and @dorecitytv (registry key).
        body = _csv_bytes([[pid, "", "onetruth.athlete", "", "collab reel", "", "09/10/2026 12:00",
                            f"https://www.instagram.com/reel/{SC}5/", "IG reel",
                            "public grid snapshot; co-authors: trueblue_tv,dorecitytv",
                            "Lifetime", "1200", "80", "", "3", "", "", ""]])
        r = client.post("/api/brand/network/upload-csv?account=truebluetv", headers=AUTH,
                        files={"file": ("grid.csv", body, "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["inserted"] == 1 and r.json()["source"] == "auto"

        p = db.query(NiltvNetworkPost).filter_by(post_id=pid).one()
        assert p.collab_accounts == "dorecitytv,truebluetv"      # stamp + co-author mapping
        assert p.post_type == "REELS"
        assert (p.views, p.views_source) == (1200, "public")   # detected from the Data comment

        # The TrueBlue page reads the same row (no second table).
        rows = client.get("/api/trueblue/network/posts?limit=1000", headers=AUTH).json()
        mine = [x for x in rows if x["post_id"] == pid]
        assert len(mine) == 1 and mine[0]["id"] == p.id and mine[0]["views"] == 1200
        hist = client.get(f"/api/trueblue/network/posts/{p.id}/history", headers=AUTH).json()
        assert len(hist) == 1 and hist[0]["views"] == 1200

        # The Admin page's TrueBlue export upload corrects the public counts.
        body = _csv_bytes([[pid, "", "onetruth.athlete", "", "collab reel", "", "09/10/2026 12:00",
                            f"https://www.instagram.com/reel/{SC}5/", "IG reel", "",
                            "Lifetime", "3600", "85", "7", "3", "2", "3000", "1"]])
        r = client.post("/api/trueblue/network/upload-csv", headers=AUTH,
                        files={"file": ("export.csv", body, "text/csv")})
        assert r.status_code == 200, r.text
        db.refresh(p)
        assert (p.views, p.views_source, p.shares, p.reach) == (3600, "export", 7, 3000)

        # Ambassador posts: exactly one entry for the post.
        db.add(Ambassador(ig_username="onetruth.athlete", status="confirmed"))
        db.commit()
        a = db.query(Ambassador).filter_by(ig_username="onetruth.athlete").one()
        p.ambassador_id = a.id
        db.commit()
        posts = client.get(f"/api/ambassadors/{a.id}/posts", headers=AUTH).json()
        assert [x["post_id"] for x in posts] == [pid]
        assert posts[0]["post_type"] == "REELS" and posts[0]["views"] == 3600
    finally:
        _clean(db)
        db.close()
