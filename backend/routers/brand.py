import tempfile
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.brand_registry import get_brand_targets
from backend.database import get_db
from backend.models import BrandAccount, BrandPost, BrandSnapshot, NiltvNetworkPost, NiltvNetworkPostSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


class BrandSnapshotOut(BaseModel):
    id: int
    account: str
    pulled_at: datetime
    username: Optional[str]
    followers: Optional[int]
    post_count: Optional[int]
    bio: Optional[str]

    class Config:
        from_attributes = True


class BrandPostOut(BaseModel):
    id: int
    account: str
    ig_post_id: str
    posted_at: Optional[datetime]
    media_type: Optional[str]
    caption: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    permalink: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str] = None
    impressions: Optional[int]
    reach: Optional[int]
    saves: Optional[int]
    views: Optional[int]
    shares: Optional[int]
    pulled_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/profile", response_model=Optional[BrandSnapshotOut])
def brand_profile(
    account: str = Query("niltv"),
    db: Session = Depends(get_db),
):
    """Latest profile snapshot for one brand account."""
    return (
        db.query(BrandSnapshot)
        .filter(BrandSnapshot.account == account)
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )


@router.get("/snapshots", response_model=list[BrandSnapshotOut])
def brand_snapshots(
    account: str = Query("niltv"),
    db: Session = Depends(get_db),
):
    """All profile snapshots for follower-over-time charts."""
    return (
        db.query(BrandSnapshot)
        .filter(BrandSnapshot.account == account)
        .order_by(BrandSnapshot.pulled_at.asc())
        .all()
    )


@router.get("/posts", response_model=list[BrandPostOut])
def brand_posts(
    limit: int = Query(200, ge=1, le=1000),
    account: str = Query("niltv"),
    db: Session = Depends(get_db),
):
    """Posts sorted by posted_at DESC. Pass account=all for every account."""
    q = db.query(BrandPost)
    if account != "all":
        q = q.filter(BrandPost.account == account)
    return (
        q.order_by(BrandPost.posted_at.desc())
        .limit(limit)
        .all()
    )


class NiltvNetworkPostOut(BaseModel):
    id: int
    post_id: str
    account_username: Optional[str]
    account_name: Optional[str]
    description: Optional[str]
    duration_sec: Optional[int]
    publish_time: Optional[datetime]
    permalink: Optional[str]
    post_type: Optional[str]
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    collab_accounts: Optional[str] = None
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


@router.get("/network/posts", response_model=list[NiltvNetworkPostOut])
def niltv_network_posts(
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """NILTV collab/network posts sorted by publish_time DESC."""
    return (
        db.query(NiltvNetworkPost)
        .order_by(NiltvNetworkPost.publish_time.desc())
        .limit(limit)
        .all()
    )


@router.get("/network/summary")
def niltv_network_summary(db: Session = Depends(get_db)):
    """Aggregated stats across all NILTV network posts."""
    row = db.query(
        sqlfunc.count(NiltvNetworkPost.id).label("total_posts"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0).label("total_views"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0).label("total_likes"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0).label("total_comments"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0).label("total_shares"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0).label("total_saves"),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0).label("total_reach"),
        sqlfunc.count(sqlfunc.distinct(NiltvNetworkPost.account_username)).label("unique_accounts"),
    ).one()

    total_posts = int(row.total_posts)
    total_likes = int(row.total_likes)

    return {
        "total_posts": total_posts,
        "total_views": int(row.total_views),
        "total_likes": total_likes,
        "total_comments": int(row.total_comments),
        "total_shares": int(row.total_shares),
        "total_saves": int(row.total_saves),
        "total_reach": int(row.total_reach),
        "unique_accounts": int(row.unique_accounts),
        "avg_likes": round(total_likes / total_posts, 1) if total_posts else 0,
    }


@router.post("/network/upload-csv")
async def upload_niltv_network_csv(
    file: UploadFile = File(...),
    account: Optional[str] = Query(
        None,
        description="brand_accounts.account to stamp on every row's collab_accounts. "
                    "Used by manual channels (e.g. truebluetv) whose grid arrives as a CSV "
                    "(grid snapshot or Business Suite export) instead of through the Graph API.",
    ),
    source: Optional[str] = Query(
        None,
        description="Provenance of the rows: 'export' (Business Suite) or 'public' "
                    "(grid snapshot, public play counts). Default: detected per row from the "
                    "Data comment. Views obey import_niltv_network.VIEWS_RANK, so a public "
                    "count can never overwrite Graph or export views.",
    ),
    db: Session = Depends(get_db),
):
    """Accept a Meta Business Suite-layout CSV and import NILTV network posts.

    Without `account`: backfill path that fills shares/saves/reach on
    collaborator-owned posts, which the Graph API cannot expose. With `account`:
    the rows are attributed to that channel too (unknown post ids are matched by
    permalink, so a snapshot row and a later export row merge into one).
    Zoomph is a Duke/TrueBlue feed and never lands here."""
    from backend.jobs.import_niltv_network import SOURCE_EXPORT, SOURCE_PUBLIC, import_csv

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    if source and source not in (SOURCE_EXPORT, SOURCE_PUBLIC):
        raise HTTPException(status_code=400, detail=f"source must be '{SOURCE_EXPORT}' or '{SOURCE_PUBLIC}'")
    if account and db.query(BrandAccount).filter(BrandAccount.account == account).first() is None:
        raise HTTPException(status_code=400, detail=f"'{account}' is not a brand_accounts row")

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        inserted, updated = import_csv(db, tmp_path, account=account, source=source)
        logger.info(f"NILTV CSV upload: {inserted} inserted, {updated} updated from {file.filename}"
                    f" (account={account or '-'}, source={source or 'auto'})")
        return {"inserted": inserted, "updated": updated, "filename": file.filename,
                "account": account, "source": source or "auto"}
    except Exception as e:
        logger.error(f"NILTV CSV upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        import os
        os.unlink(tmp_path)


# ── Registry admin ──────────────────────────────────────────────────────────
# Visibility + safe edits for the brand_accounts registry (campus channels).
# Tokens are NEVER included in responses. Mutations are POST (CORS allows
# GET/POST only); token onboarding stays in scripts/add_brand_account.py.

class BrandAccountOut(BaseModel):
    account: str
    username: Optional[str] = None
    ig_user_id: Optional[str] = None
    api: str = "fb"
    post_limit: Optional[int] = None
    campus: Optional[str] = None
    network_pull: bool = False
    active: bool = True
    source: str = "db"                 # 'db' | 'env' (env rows: onboard with --import-env to edit)
    own_token: bool = False
    token_expires_at: Optional[datetime] = None
    token_refreshed_at: Optional[datetime] = None
    notes: Optional[str] = None
    # Pull health, derived from brand_snapshots (a failed nightly pull stores
    # an empty-username snapshot — see run_brand_ig._pull_account).
    health: str = "no-data"            # 'ok' | 'failing' | 'no-data'
    last_pull_attempt: Optional[datetime] = None
    last_pull_ok: Optional[datetime] = None
    # Ready for ambassador campus inference: campus set, or not a network
    # channel (inference maps collab_accounts -> brand_accounts.campus).
    campus_ready: bool = False


class BrandAccountUpdate(BaseModel):
    campus: Optional[str] = None       # explicit null/empty clears
    active: Optional[bool] = None
    network_pull: Optional[bool] = None
    post_limit: Optional[int] = None
    notes: Optional[str] = None


def _account_health(db: Session) -> dict[str, tuple[Optional[datetime], Optional[datetime]]]:
    """{account: (last_attempt, last_ok)} from brand_snapshots."""
    attempts = (
        db.query(BrandSnapshot)
        .distinct(BrandSnapshot.account)
        .order_by(BrandSnapshot.account, BrandSnapshot.pulled_at.desc())
        .all()
    )
    oks = (
        db.query(BrandSnapshot)
        .filter(BrandSnapshot.username.isnot(None), BrandSnapshot.username != "")
        .distinct(BrandSnapshot.account)
        .order_by(BrandSnapshot.account, BrandSnapshot.pulled_at.desc())
        .all()
    )
    ok_map = {s.account: s.pulled_at for s in oks}
    return {s.account: (s.pulled_at, ok_map.get(s.account)) for s in attempts}


def _registry_out(db: Session) -> list[BrandAccountOut]:
    db_rows = {r.account: r for r in db.query(BrandAccount).all()}
    env_targets = {t["account"]: t for t in get_brand_targets(db) if t["db_id"] is None}
    health_map = _account_health(db)

    out: list[BrandAccountOut] = []
    for account in sorted(set(db_rows) | set(env_targets)):
        attempt, ok = health_map.get(account, (None, None))
        if attempt is None:
            health = "no-data"
        elif ok is not None and ok >= attempt:
            health = "ok"
        else:
            health = "failing"

        row = db_rows.get(account)
        if row is not None:
            entry = BrandAccountOut(
                account=account,
                username=row.username,
                ig_user_id=row.ig_user_id,
                api=row.api or "fb",
                post_limit=row.post_limit,
                campus=row.campus,
                network_pull=bool(row.network_pull),
                active=bool(row.active),
                source="db",
                own_token=bool(row.access_token),
                # Stamps describe the row's OWN token. A row riding on the
                # shared BRAND_IG_ACCESS_TOKEN grant reports none: the shared
                # token is refreshed (or never expires) independently, and a
                # leftover onboarding stamp would read as a false expiry.
                token_expires_at=row.token_expires_at if row.access_token else None,
                token_refreshed_at=row.token_refreshed_at if row.access_token else None,
                notes=row.notes,
            )
        else:
            t = env_targets[account]
            entry = BrandAccountOut(
                account=account,
                ig_user_id=t["ig_user_id"],
                api=t.get("api", "fb"),
                post_limit=t.get("limit"),
                network_pull=bool(t.get("network_pull")),
                source="env",
                own_token=bool(t.get("own_token")),
            )
        entry.health = health
        entry.last_pull_attempt = attempt
        entry.last_pull_ok = ok
        entry.campus_ready = bool(entry.campus) or not entry.network_pull
        out.append(entry)

    out.sort(key=lambda e: (not e.active, e.account))
    return out


@router.get("/accounts", response_model=list[BrandAccountOut])
def list_brand_accounts(db: Session = Depends(get_db)):
    """The full merged registry (DB rows + .env fallback) with nightly pull
    health and ambassador campus-inference readiness per channel."""
    return _registry_out(db)


@router.post("/accounts/{account}/update", response_model=BrandAccountOut)
def update_brand_account(account: str, payload: BrandAccountUpdate, db: Session = Depends(get_db)):
    row = db.query(BrandAccount).filter(BrandAccount.account == account).first()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No brand_accounts row named '{account}' (env-defined accounts: "
                   "run scripts/add_brand_account.py --import-env first)",
        )
    fields = payload.model_dump(exclude_unset=True)
    if "campus" in fields:
        row.campus = (fields["campus"] or "").strip().lower() or None
    for key in ("active", "network_pull", "post_limit", "notes"):
        if key in fields:
            setattr(row, key, fields[key])
    row.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    return next(e for e in _registry_out(db) if e.account == account)


@router.post("/accounts/{account}/verify")
def verify_brand_account(account: str, db: Session = Depends(get_db)):
    """Live check: fetch the account's profile with its stored token, exactly
    as the nightly job would. Diagnoses failing channels without server access."""
    from backend.sources.brand_ig import fetch_brand_profile

    target = next((t for t in get_brand_targets(db) if t["account"] == account), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"'{account}' is not an active registry target")
    profile = fetch_brand_profile(
        ig_user_id=target["ig_user_id"],
        access_token=target["access_token"],
        limit=1,
        api=target.get("api", "fb"),
    )
    return {
        "account": account,
        "ok": not profile.error,
        "username": profile.username or None,
        "followers": profile.followers,
        "post_count": profile.post_count,
        "error": profile.error,
    }


@router.get("/summary")
def brand_summary(
    account: str = Query("niltv"),
    db: Session = Depends(get_db),
):
    """Aggregated stats across one brand account's posts (account=all for every account)."""
    q = db.query(
        sqlfunc.count(BrandPost.id).label("total_posts"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.like_count), 0).label("total_likes"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.comment_count), 0).label("total_comments"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.impressions), 0).label("total_impressions"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.reach), 0).label("total_reach"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.saves), 0).label("total_saves"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.views), 0).label("total_views"),
        sqlfunc.coalesce(sqlfunc.sum(BrandPost.shares), 0).label("total_shares"),
    )
    if account != "all":
        q = q.filter(BrandPost.account == account)
    row = q.one()

    total_posts = int(row.total_posts)
    total_likes = int(row.total_likes)
    total_comments = int(row.total_comments)
    total_impressions = int(row.total_impressions)

    return {
        "total_posts": total_posts,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_impressions": total_impressions,
        "total_reach": int(row.total_reach),
        "total_saves": int(row.total_saves),
        "total_views": int(row.total_views),
        "avg_likes": round(total_likes / total_posts, 1) if total_posts else 0,
        "avg_comments": round(total_comments / total_posts, 1) if total_posts else 0,
        "avg_impressions": round(total_impressions / total_posts, 1) if total_posts else 0,
    }
