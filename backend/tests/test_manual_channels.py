"""Manual channels (brand_accounts.api='bd'): the Graph jobs skip them, the
Business Discovery job snapshots the profile and files the owned posts under the
channel tag, and the shared-table CSV upload accepts an account to stamp.
Runs in CI against the seeded Postgres.
"""

import csv
import io
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.brand_registry import get_brand_targets
from backend.database import SessionLocal
from backend.jobs import run_manual_channels as job
from backend.main import app
from backend.models import BrandAccount, BrandSnapshot, NiltvNetworkPost, NiltvNetworkPostSnapshot
from backend.sources.instagram import IGPost, IGProfile

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
OWNED_ID = "18000000000000101"
SC = "DcTest0001"


def _clean(db):
    for pid in (OWNED_ID, "3900000000000000001"):
        rows = db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id == pid).all()
        if rows:
            db.query(NiltvNetworkPostSnapshot).filter(
                NiltvNetworkPostSnapshot.network_post_id.in_([r.id for r in rows])
            ).delete(synchronize_session=False)
            db.query(NiltvNetworkPost).filter(NiltvNetworkPost.post_id == pid).delete(synchronize_session=False)
    db.query(BrandSnapshot).filter(BrandSnapshot.account == "truebluetv").delete(synchronize_session=False)
    db.query(BrandAccount).filter(BrandAccount.account.in_(["truebluetv", "bdlive"])).delete(
        synchronize_session=False)
    db.commit()


def _seed_manual_row(db, active=False):
    db.add(BrandAccount(account="truebluetv", username="trueblue_tv", ig_user_id="17841400000000001",
                        api="bd", campus="duke", network_pull=False, active=active))
    db.commit()


def test_bd_rows_never_become_graph_targets():
    db = SessionLocal()
    try:
        _clean(db)
        # Even an ACTIVE api='bd' row must stay out of run_brand_ig / run_niltv_network.
        db.add(BrandAccount(account="bdlive", username="bdlive", ig_user_id="1", api="bd", active=True))
        db.commit()
        assert "bdlive" not in {t["account"] for t in get_brand_targets(db)}
    finally:
        _clean(db)
        db.close()


def test_manual_channel_pull_snapshots_profile_and_files_owned_posts(monkeypatch):
    db = SessionLocal()
    try:
        _clean(db)
        _seed_manual_row(db)

        def fake_profile(handle, max_retries=3, include_media=True):
            assert handle == "trueblue_tv" and include_media
            return IGProfile(
                username="trueblue_tv", ig_user_id="17841400000000001", followers=1000,
                post_count=100, bio="Test channel bio", name="True Blue TV",
                posts=[IGPost(ig_post_id=OWNED_ID, posted_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
                              media_type="VIDEO", like_count=180, comment_count=1,
                              permalink=f"https://www.instagram.com/reel/{SC}/", caption="Duke reel",
                              media_url="https://cdn/x.mp4")],
            )
        monkeypatch.setattr(job, "fetch_ig_profile", fake_profile)
        monkeypatch.setattr(job.time, "sleep", lambda s: None)

        inserted = job._pull_manual_channels(db)
        assert inserted == 1

        snap = (db.query(BrandSnapshot).filter_by(account="truebluetv")
                .order_by(BrandSnapshot.pulled_at.desc()).first())
        assert snap.followers == 1000 and snap.post_count == 100 and snap.username == "trueblue_tv"

        post = db.query(NiltvNetworkPost).filter_by(post_id=OWNED_ID).one()
        assert post.collab_accounts == "truebluetv"
        assert post.account_username == "trueblue_tv" and post.account_name == "True Blue TV"
        assert post.post_type == "REELS" and post.likes == 180 and post.views is None   # canonical vocabulary

        # Registry health reads the snapshot: the manual channel is "ok", not "no-data".
        rows = {r["account"]: r for r in client.get("/api/brand/accounts", headers=AUTH).json()}
        assert rows["truebluetv"]["health"] == "ok" and rows["truebluetv"]["api"] == "bd"
    finally:
        _clean(db)
        db.close()


def _csv_bytes(post_id: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Post ID", "Account ID", "Account username", "Account name", "Description", "Duration (sec)",
                "Publish time", "Permalink", "Post type", "Data comment", "Date", "Views", "Likes", "Shares",
                "Comments", "Saves", "Reach", "Follows"])
    w.writerow([post_id, "", "trueblue_tv", "", "Duke reel", "", "09/07/2026 12:00",
                f"https://www.instagram.com/reel/{SC}/", "IG reel", "", "Lifetime", "2500", "190", "", "2", "", "", ""])
    return buf.getvalue().encode("utf-8-sig")


def test_upload_with_account_tags_and_merges_by_permalink():
    db = SessionLocal()
    try:
        _clean(db)
        _seed_manual_row(db)
        db.add(NiltvNetworkPost(post_id=OWNED_ID, account_username="trueblue_tv", collab_accounts="truebluetv",
                                permalink=f"https://www.instagram.com/reel/{SC}/", post_type="IG reel", likes=180))
        db.commit()

        # Snapshot row: same permalink, provisional public media key -> merges, no new row.
        r = client.post("/api/brand/network/upload-csv?account=truebluetv", headers=AUTH,
                        files={"file": ("grid.csv", _csv_bytes("3900000000000000001"), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["inserted"] == 0 and r.json()["account"] == "truebluetv"
        rows = db.query(NiltvNetworkPost).filter(NiltvNetworkPost.permalink.like(f"%/{SC}/%")).all()
        assert len(rows) == 1 and rows[0].post_id == OWNED_ID     # Graph id kept
        db.refresh(rows[0])
        assert rows[0].views == 2500 and rows[0].likes == 190       # metrics refreshed

        # Unknown account is refused before anything is written.
        r = client.post("/api/brand/network/upload-csv?account=nope", headers=AUTH,
                        files={"file": ("grid.csv", _csv_bytes(OWNED_ID), "text/csv")})
        assert r.status_code == 400
    finally:
        _clean(db)
        db.close()
