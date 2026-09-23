import logging
import tempfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc, text
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import NiltvNetworkPost, NiltvNetworkPostSnapshot, TrueBluePost, TrueBlueSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])

# brand_accounts.account key of the manual TrueBlueTV channel (see the
# upload-csv endpoint). Must match the registry row and the app's roster.
TRUEBLUE_CHANNEL = "truebluetv"
# Every TrueBlueTV grid post lives in the shared network table under this tag
# (migration 026 merged the old trueblue_network_posts table into it).
TRUEBLUE_FILTER = NiltvNetworkPost.collab_accounts.contains(TRUEBLUE_CHANNEL)


def _tb_posts(db: Session):
    return db.query(NiltvNetworkPost).filter(TRUEBLUE_FILTER)


class SnapshotOut(BaseModel):
    id: int
    pulled_at: datetime
    followers: Optional[int]
    following: Optional[int]
    post_count: Optional[int]
    bio: Optional[str]

    class Config:
        from_attributes = True


class PostOut(BaseModel):
    id: int
    shortcode: str
    posted_at: Optional[datetime]
    media_type: Optional[str]
    caption: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    permalink: Optional[str]
    media_url: Optional[str]
    is_video: Optional[bool]
    video_view_count: Optional[int]
    pulled_at: Optional[datetime]

    class Config:
        from_attributes = True


class NetworkPostOut(BaseModel):
    id: int
    post_id: str
    account_username: Optional[str]
    account_name: Optional[str]
    description: Optional[str]
    duration_sec: Optional[int]
    publish_time: Optional[datetime]
    permalink: Optional[str]
    post_type: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    shares: Optional[int]
    comments: Optional[int]
    saves: Optional[int]
    reach: Optional[int]
    projected_reach: Optional[int]
    follows: Optional[int]

    class Config:
        from_attributes = True


class NetworkPostSnapshotOut(BaseModel):
    id: int
    network_post_id: int
    captured_at: datetime
    views: Optional[int]
    likes: Optional[int]
    shares: Optional[int]
    comments: Optional[int]
    saves: Optional[int]
    reach: Optional[int]
    projected_reach: Optional[int]
    follows: Optional[int]

    class Config:
        from_attributes = True


@router.get("/profile", response_model=Optional[SnapshotOut])
def trueblue_profile(db: Session = Depends(get_db)):
    """Latest profile snapshot."""
    return (
        db.query(TrueBlueSnapshot)
        .order_by(TrueBlueSnapshot.pulled_at.desc())
        .first()
    )


@router.get("/snapshots", response_model=list[SnapshotOut])
def trueblue_snapshots(db: Session = Depends(get_db)):
    """All profile snapshots for follower-over-time chart."""
    return (
        db.query(TrueBlueSnapshot)
        .order_by(TrueBlueSnapshot.pulled_at.asc())
        .all()
    )


@router.get("/posts", response_model=list[PostOut])
def trueblue_posts(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Posts sorted by posted_at DESC."""
    return (
        db.query(TrueBluePost)
        .order_by(TrueBluePost.posted_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/summary")
def trueblue_summary(db: Session = Depends(get_db)):
    """Aggregated stats across all trueblue_tv account posts."""
    row = db.query(
        sqlfunc.count(TrueBluePost.id).label("total_posts"),
        sqlfunc.coalesce(sqlfunc.sum(TrueBluePost.like_count), 0).label("total_likes"),
        sqlfunc.coalesce(sqlfunc.sum(TrueBluePost.comment_count), 0).label("total_comments"),
        sqlfunc.coalesce(sqlfunc.sum(TrueBluePost.video_view_count), 0).label("total_video_views"),
    ).one()

    total_posts = int(row.total_posts)
    total_likes = int(row.total_likes)
    total_comments = int(row.total_comments)

    return {
        "total_posts": total_posts,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_video_views": int(row.total_video_views),
        "avg_likes": round(total_likes / total_posts, 1) if total_posts else 0,
        "avg_comments": round(total_comments / total_posts, 1) if total_posts else 0,
    }


@router.get("/network/posts", response_model=list[NetworkPostOut])
def trueblue_network_posts(
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """TrueBlueTV grid posts (owned + athlete collabs), newest first — the
    shared network table filtered on the truebluetv channel tag."""
    return (
        _tb_posts(db)
        .order_by(NiltvNetworkPost.publish_time.desc())
        .limit(limit)
        .all()
    )


@router.get("/network/summary")
def trueblue_network_summary(db: Session = Depends(get_db)):
    """Aggregated stats across ALL TrueBlueTV network posts."""
    row = db.query(
        sqlfunc.count(NiltvNetworkPost.id).label("total_posts"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0).label("total_views"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0).label("total_likes"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0).label("total_comments"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0).label("total_shares"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0).label("total_saves"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.follows), 0).label("total_follows"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0).label("total_reach"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.projected_reach), 0).label("total_projected_reach"),
        sqlfunc.count(sqlfunc.distinct(NiltvNetworkPost.account_username)).label("unique_accounts"),
    ).filter(TRUEBLUE_FILTER).one()

    total_posts = int(row.total_posts)
    total_likes = int(row.total_likes)
    total_reach = int(row.total_reach)
    total_projected = int(row.total_projected_reach)

    return {
        "total_posts": total_posts,
        "total_views": int(row.total_views),
        "total_likes": total_likes,
        "total_comments": int(row.total_comments),
        "total_shares": int(row.total_shares),
        "total_saves": int(row.total_saves),
        "total_follows": int(row.total_follows),
        "total_reach": total_reach,
        "total_projected_reach": total_reach + total_projected,
        "unique_accounts": int(row.unique_accounts),
        "avg_likes": round(total_likes / total_posts, 1) if total_posts else 0,
    }


@router.get("/network/top-accounts")
def trueblue_network_top_accounts(db: Session = Depends(get_db)):
    """Top accounts by total views in the TrueBlueTV network."""
    rows = (
        db.query(
            NiltvNetworkPost.account_username,
            NiltvNetworkPost.account_name,
            sqlfunc.count(NiltvNetworkPost.id).label("post_count"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0).label("total_views"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0).label("total_likes"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0).label("total_comments"),
        )
        .filter(TRUEBLUE_FILTER)
        .group_by(NiltvNetworkPost.account_username, NiltvNetworkPost.account_name)
        .order_by(sqlfunc.sum(NiltvNetworkPost.views).desc())
        .limit(20)
        .all()
    )
    return [
        {
            "account_username": r.account_username,
            "account_name": r.account_name,
            "post_count": int(r.post_count),
            "total_views": int(r.total_views),
            "total_likes": int(r.total_likes),
            "total_comments": int(r.total_comments),
        }
        for r in rows
    ]


@router.get("/network/posts/{post_id}/history", response_model=list[NetworkPostSnapshotOut])
def network_post_history(post_id: int, db: Session = Depends(get_db)):
    """All metric snapshots for a single network post (row id), ordered by time."""
    return (
        db.query(NiltvNetworkPostSnapshot)
        .filter(NiltvNetworkPostSnapshot.network_post_id == post_id)
        .order_by(NiltvNetworkPostSnapshot.captured_at.asc())
        .all()
    )


@router.get("/network/metrics-over-time")
def network_metrics_over_time(db: Session = Depends(get_db)):
    """Aggregate TrueBlueTV network metrics by snapshot date for trend charts.

    Uses a carry-forward approach: for each snapshot date, get the latest
    known value for every post (not just posts that changed on that date).
    projected_reach is pre-computed and stored on each snapshot.
    """
    sql = text("""
        WITH posts AS (
            SELECT id FROM niltv_network_posts
            WHERE ',' || COALESCE(collab_accounts, '') || ',' LIKE :tag
        ),
        snapshot_dates AS (
            SELECT DISTINCT date_trunc('day', s.captured_at)::date AS dt
            FROM niltv_network_post_snapshots s
            JOIN posts p ON p.id = s.network_post_id
        )
        SELECT
            sd.dt                           AS date,
            SUM(ls.views)                   AS total_views,
            SUM(ls.likes)                   AS total_likes,
            SUM(ls.comments)                AS total_comments,
            SUM(ls.shares)                  AS total_shares,
            SUM(ls.saves)                   AS total_saves,
            SUM(ls.reach)                   AS total_reach,
            SUM(ls.projected_reach)         AS total_projected_reach
        FROM snapshot_dates sd
        CROSS JOIN posts p
        LEFT JOIN LATERAL (
            SELECT s.views, s.likes, s.comments, s.shares, s.saves, s.reach, s.projected_reach
            FROM niltv_network_post_snapshots s
            WHERE s.network_post_id = p.id
              AND s.captured_at < sd.dt + INTERVAL '1 day'
            ORDER BY s.captured_at DESC
            LIMIT 1
        ) ls ON true
        WHERE ls.views IS NOT NULL
        GROUP BY sd.dt
        ORDER BY sd.dt
    """)
    rows = db.execute(sql, {"tag": f"%,{TRUEBLUE_CHANNEL},%"}).fetchall()
    return [
        {
            "date": r.date.isoformat() if r.date else None,
            "total_views": int(r.total_views or 0),
            "total_likes": int(r.total_likes or 0),
            "total_comments": int(r.total_comments or 0),
            "total_shares": int(r.total_shares or 0),
            "total_saves": int(r.total_saves or 0),
            "total_reach": int(r.total_reach or 0),
            "total_projected_reach": int(r.total_reach or 0) + int(r.total_projected_reach or 0),
        }
        for r in rows
    ]


@router.post("/network/upload-csv")
async def upload_network_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Accept a Meta Business Suite export of the @trueblue_tv grid and import
    it into the shared network table tagged collab_accounts=truebluetv — the
    ONLY source for shares/saves/reach/follows and for views on images and
    carousels. Export values outrank public play counts
    (import_niltv_network.VIEWS_RANK), so an upload always corrects them."""
    from backend.jobs.import_niltv_network import import_csv

    if not file.filename or not file.filename.endswith(".csv"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File must be a .csv")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # source is detected per row: a grid snapshot CSV dropped here by mistake
        # still ranks as public and cannot overwrite export/Graph views.
        inserted, updated = import_csv(db, tmp_path, account=TRUEBLUE_CHANNEL)
        logger.info(
            f"CSV upload: {inserted} inserted, {updated} updated (niltv_network_posts as "
            f"{TRUEBLUE_CHANNEL}) from {file.filename}"
        )
        return {
            "inserted": inserted,
            "updated": updated,
            "network_inserted": inserted,   # kept for the Admin page's existing response shape
            "network_updated": updated,
            "filename": file.filename,
        }
    except Exception as e:
        logger.error(f"CSV upload failed: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        import os
        os.unlink(tmp_path)
