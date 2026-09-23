"""The shared-table CSV importer's --account stamping: a manual channel's
Business Suite export lands in niltv_network_posts tagged to that channel, and
a post already known via another channel's edge unions rather than duplicates.
Runs in CI against the seeded Postgres.
"""

import csv
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from backend.database import SessionLocal
from backend.jobs.import_niltv_network import import_csv
from backend.models import NiltvNetworkPost, NiltvNetworkPostSnapshot

CAPTURED = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
NEW_ID = "18000000000000001"
SHARED_ID = "18000000000000002"

COLUMNS = [
    "Post ID", "Account ID", "Account username", "Account name", "Description",
    "Duration (sec)", "Publish time", "Permalink", "Post type", "Data comment",
    "Date", "Views", "Likes", "Shares", "Comments", "Saves", "Reach", "Follows",
]


def _write_csv(rows: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                      encoding="utf-8-sig", newline="")
    with tmp:
        w = csv.DictWriter(tmp, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    return tmp.name


def _seed():
    db = SessionLocal()
    try:
        ids = [NEW_ID, SHARED_ID]
        existing = db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id.in_(ids)).all()
        if existing:
            db.query(NiltvNetworkPostSnapshot).filter(
                NiltvNetworkPostSnapshot.network_post_id.in_([r.id for r in existing])
            ).delete(synchronize_session=False)
            db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id.in_(ids)).delete(
                synchronize_session=False)
        # Athlete-authored post that the @niltv collab edge already pulled.
        db.add(NiltvNetworkPost(post_id=SHARED_ID, account_username="sampleteam",
                                collab_accounts="niltv", post_type="REELS",
                                views=100, likes=5))
        db.commit()
    finally:
        db.close()


def _rows():
    return [
        {"Post ID": NEW_ID, "Account username": "sampleathlete", "Post type": "IG reel",
         "Publish time": "02/22/2026 17:15",
         "Permalink": "https://www.instagram.com/reel/CAAAAAAAAAA/",
         "Views": "2030", "Likes": "70", "Shares": "13", "Comments": "5", "Saves": "0"},
        {"Post ID": SHARED_ID, "Account username": "sampleteam", "Post type": "IG reel",
         "Publish time": "01/21/2026 06:01",
         "Permalink": "https://www.instagram.com/p/CBBBBBBBBBB/",
         "Views": "120", "Likes": "6", "Shares": "2", "Comments": "1", "Saves": "3"},
    ]


def test_account_stamps_new_rows_and_unions_existing():
    _seed()
    path = _write_csv(_rows())
    db = SessionLocal()
    try:
        inserted, updated = import_csv(db, path, captured_at=CAPTURED, account="truebluetv")
        assert (inserted, updated) == (1, 1)

        new = db.query(NiltvNetworkPost).filter_by(post_id=NEW_ID).one()
        assert new.collab_accounts == "truebluetv"
        assert new.account_username == "sampleathlete"
        assert new.views == 2030

        shared = db.query(NiltvNetworkPost).filter_by(post_id=SHARED_ID).one()
        assert shared.collab_accounts == "niltv,truebluetv"   # unioned, not replaced
        assert shared.shares == 2 and shared.saves == 3        # CSV-only metrics backfilled
    finally:
        db.close()
        Path(path).unlink(missing_ok=True)


def test_without_account_leaves_attribution_alone():
    _seed()
    path = _write_csv(_rows())
    db = SessionLocal()
    try:
        import_csv(db, path, captured_at=CAPTURED)
        assert db.query(NiltvNetworkPost).filter_by(post_id=NEW_ID).one().collab_accounts is None
        assert db.query(NiltvNetworkPost).filter_by(post_id=SHARED_ID).one().collab_accounts == "niltv"
    finally:
        db.close()
        Path(path).unlink(missing_ok=True)


PK_ID = "3977000000000000001"   # public media key from a grid snapshot; not a Graph id


def test_permalink_match_rekeys_a_snapshot_row_when_the_graph_id_arrives():
    _seed()
    db = SessionLocal()
    try:
        # A snapshot row landed first under the public media key for NEW_ID's permalink.
        db.add(NiltvNetworkPost(post_id=PK_ID, account_username="sampleathlete", collab_accounts="truebluetv",
                                permalink="https://www.instagram.com/reel/CAAAAAAAAAA/", post_type="IG reel",
                                views=1900, likes=60))
        db.commit()
        path = _write_csv(_rows())                       # brings NEW_ID (Graph id), same permalink
        inserted, updated = import_csv(db, path, captured_at=CAPTURED, account="truebluetv")
        assert (inserted, updated) == (0, 2)             # both rows already known: one by key, one by permalink
        rows = db.query(NiltvNetworkPost).filter(
            NiltvNetworkPost.permalink.like("%/CAAAAAAAAAA/%")).all()
        assert len(rows) == 1                            # merged, not duplicated
        assert rows[0].post_id == NEW_ID                 # re-keyed to the Graph id
        assert rows[0].views == 2030 and rows[0].collab_accounts == "truebluetv"
        assert db.query(NiltvNetworkPost).filter_by(post_id=PK_ID).count() == 0
    finally:
        for pid in (PK_ID,):
            db.query(NiltvNetworkPost).filter_by(post_id=pid).delete(synchronize_session=False)
        db.commit()
        db.close()
        Path(path).unlink(missing_ok=True)
