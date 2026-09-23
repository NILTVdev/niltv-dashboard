"""Ambassador registry + attributed-content endpoints.

Read endpoints back the tracking page; the POST endpoints are the admin
surface (add / confirm / remove / edit — the welcome parser handles
discovery, these handle corrections). Mutations are POST because the CORS
config only allows GET/POST.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.jobs.ambassadors import attribute_posts, normalize_username
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    Athlete,
    NiltvNetworkPost,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

VALID_STATUSES = ("candidate", "confirmed", "removed")

# Roster attributes settable via the admin endpoints and the sheet import.
ROSTER_FIELDS = ("display_name", "school", "sport", "year", "gender", "cohort")


class AmbassadorOut(BaseModel):
    id: int
    ig_username: Optional[str]  # NULL for sheet-only rows until the handle is known
    display_name: Optional[str]
    previous_usernames: Optional[str]
    campus: Optional[str]
    campus_source: str
    school: Optional[str]
    sport: Optional[str]
    year: Optional[str]
    gender: Optional[str]
    cohort: Optional[str]
    profile_pic_url: Optional[str]
    website: Optional[str]
    status: str
    source: Optional[str]
    welcome_post_id: Optional[str]
    announced_at: Optional[datetime]
    athlete_id: Optional[int]
    ig_accessible: Optional[bool]
    active: bool
    notes: Optional[str]
    # Precomputed cache
    followers: Optional[int] = None
    bio: Optional[str] = None
    collab_posts: Optional[int] = None
    collab_views: Optional[int] = None
    collab_engagement: Optional[int] = None
    last_pulled: Optional[datetime] = None

    class Config:
        from_attributes = True


def _to_out(a: Ambassador) -> AmbassadorOut:
    return AmbassadorOut(
        id=a.id,
        ig_username=a.ig_username,
        display_name=a.display_name,
        previous_usernames=a.previous_usernames,
        campus=a.campus,
        campus_source=a.campus_source,
        school=a.school,
        sport=a.sport,
        year=a.year,
        gender=a.gender,
        cohort=a.cohort,
        profile_pic_url=a.profile_pic_url,
        website=a.website,
        status=a.status,
        source=a.source,
        welcome_post_id=a.welcome_post_id,
        announced_at=a.announced_at,
        athlete_id=a.athlete_id,
        ig_accessible=a.ig_accessible,
        active=a.active,
        notes=a.notes,
        followers=a.cached_followers,
        bio=a.cached_bio,
        collab_posts=a.cached_collab_posts,
        collab_views=a.cached_collab_views,
        collab_engagement=a.cached_collab_engagement,
        last_pulled=a.cached_last_pulled,
    )


class AmbassadorPostOut(BaseModel):
    source: str  # always 'niltv_network' (kept for API compatibility)
    post_id: str
    account_username: Optional[str]
    description: Optional[str]
    publish_time: Optional[datetime]
    permalink: Optional[str]
    post_type: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    collab_accounts: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]
    shares: Optional[int]
    saves: Optional[int]
    reach: Optional[int]
    projected_reach: Optional[int]
    follows: Optional[int]


class AmbassadorSnapshotOut(BaseModel):
    pulled_at: Optional[datetime]
    followers: Optional[int]
    post_count: Optional[int]
    tiktok_followers: Optional[int]
    youtube_subscribers: Optional[int]
    source: str

    class Config:
        from_attributes = True


class AmbassadorCreate(BaseModel):
    ig_username: str
    display_name: Optional[str] = None
    campus: Optional[str] = None
    school: Optional[str] = None
    sport: Optional[str] = None
    year: Optional[str] = None
    gender: Optional[str] = None
    cohort: Optional[str] = None
    athlete_id: Optional[int] = None
    notes: Optional[str] = None


class AmbassadorUpdate(BaseModel):
    ig_username: Optional[str] = None
    display_name: Optional[str] = None
    campus: Optional[str] = None  # explicit null clears campus (back to inference)
    school: Optional[str] = None
    sport: Optional[str] = None
    year: Optional[str] = None
    gender: Optional[str] = None
    cohort: Optional[str] = None
    status: Optional[str] = None
    athlete_id: Optional[int] = None  # explicit null unlinks
    active: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/", response_model=list[AmbassadorOut])
def list_ambassadors(
    status: str = Query("active", description="candidate | confirmed | removed | active (= not removed) | all"),
    campus: Optional[str] = Query(None),
    cohort: Optional[str] = Query(None),
    has_posts: Optional[bool] = Query(None, description="true = only ambassadors with attributed collab posts"),
    db: Session = Depends(get_db),
):
    q = db.query(Ambassador)
    if status == "active":
        q = q.filter(Ambassador.status != "removed")
    elif status != "all":
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES + ('active', 'all')}")
        q = q.filter(Ambassador.status == status)
    if campus:
        q = q.filter(Ambassador.campus == campus)
    if cohort:
        q = q.filter(Ambassador.cohort == cohort)
    if has_posts is True:
        q = q.filter(Ambassador.cached_collab_posts > 0)
    elif has_posts is False:
        q = q.filter((Ambassador.cached_collab_posts.is_(None)) | (Ambassador.cached_collab_posts == 0))
    rows = q.order_by((Ambassador.status != "confirmed").asc(), Ambassador.ig_username).all()
    return [_to_out(a) for a in rows]


@router.get("/summary")
def ambassadors_summary(db: Session = Depends(get_db)):
    """Registry-wide totals for the tracking page header."""
    rows = db.query(Ambassador).filter(Ambassador.status != "removed").all()
    campuses: dict[str, int] = {}
    for a in rows:
        if a.campus:
            campuses[a.campus] = campuses.get(a.campus, 0) + 1
    return {
        "total": len(rows),
        "confirmed": sum(1 for a in rows if a.status == "confirmed"),
        "candidates": sum(1 for a in rows if a.status == "candidate"),
        "with_posts": sum(1 for a in rows if (a.cached_collab_posts or 0) > 0),
        "with_handle": sum(1 for a in rows if a.ig_username),
        "collab_posts": sum(a.cached_collab_posts or 0 for a in rows),
        "collab_views": sum(a.cached_collab_views or 0 for a in rows),
        "collab_engagement": sum(a.cached_collab_engagement or 0 for a in rows),
        "ig_followers": sum(a.cached_followers or 0 for a in rows),
        "campuses": campuses,
    }


@router.get("/{ambassador_id}", response_model=AmbassadorOut)
def get_ambassador(ambassador_id: int, db: Session = Depends(get_db)):
    a = db.query(Ambassador).filter(Ambassador.id == ambassador_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Ambassador not found")
    return _to_out(a)


@router.get("/{ambassador_id}/posts", response_model=list[AmbassadorPostOut])
def list_ambassador_posts(
    ambassador_id: int,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    """Collab posts attributed to this ambassador, newest first — one row per
    post from the shared network table (TrueBlueTV rows included since
    migration 026, so nothing is listed twice)."""
    a = db.query(Ambassador).filter(Ambassador.id == ambassador_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Ambassador not found")

    out: list[AmbassadorPostOut] = []
    for row in (
        db.query(NiltvNetworkPost)
        .filter(NiltvNetworkPost.ambassador_id == ambassador_id)
        .order_by(NiltvNetworkPost.publish_time.desc().nullslast())
        .limit(limit)
        .all()
    ):
        out.append(AmbassadorPostOut(
            source="niltv_network",
            post_id=row.post_id,
            account_username=row.account_username,
            description=row.description,
            publish_time=row.publish_time,
            permalink=row.permalink,
            post_type=row.post_type,
            media_url=row.media_url,
            thumbnail_url=row.thumbnail_url,
            collab_accounts=row.collab_accounts,
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            saves=row.saves,
            reach=row.reach,
            projected_reach=row.projected_reach,
            follows=row.follows,
        ))
    out.sort(key=lambda p: (p.publish_time or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return out[:limit]


@router.get("/{ambassador_id}/snapshots", response_model=list[AmbassadorSnapshotOut])
def list_ambassador_snapshots(
    ambassador_id: int,
    days: int = Query(365, le=3650),
    db: Session = Depends(get_db),
):
    """Profile trendline, oldest first. source distinguishes nightly
    Business Discovery pulls from self-reported sheet imports — charts
    should render 'reported' points differently (they only move on
    re-import; TikTok/YouTube have no pull pipeline)."""
    a = db.query(Ambassador).filter(Ambassador.id == ambassador_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Ambassador not found")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = (
        db.query(AmbassadorSnapshot)
        .filter(
            AmbassadorSnapshot.ambassador_id == ambassador_id,
            AmbassadorSnapshot.pulled_at >= cutoff,
        )
        .order_by(AmbassadorSnapshot.pulled_at.asc())
        .all()
    )
    return rows


def _validate_athlete(db: Session, athlete_id: Optional[int]) -> None:
    if athlete_id is not None:
        if not db.query(Athlete.id).filter(Athlete.id == athlete_id).first():
            raise HTTPException(status_code=400, detail=f"athlete_id {athlete_id} does not exist")


@router.post("/", response_model=AmbassadorOut)
def add_ambassador(payload: AmbassadorCreate, db: Session = Depends(get_db)):
    """Admin add. Re-adding an existing (e.g. removed) username revives it as
    confirmed rather than erroring — removal is reversible by design."""
    username = normalize_username(payload.ig_username)
    if not username:
        raise HTTPException(status_code=400, detail="ig_username is required")
    _validate_athlete(db, payload.athlete_id)

    now = datetime.now(tz=timezone.utc)
    a = db.query(Ambassador).filter(Ambassador.ig_username == username).first()
    if a is None:
        a = Ambassador(ig_username=username, status="confirmed", source="admin")
        db.add(a)
    else:
        a.status = "confirmed"
        a.updated_at = now
    for key in ROSTER_FIELDS:
        value = getattr(payload, key)
        if value is not None:
            setattr(a, key, value)
    if payload.campus is not None:
        a.campus = payload.campus
        a.campus_source = "manual"
    if payload.athlete_id is not None:
        a.athlete_id = payload.athlete_id
    if payload.notes is not None:
        a.notes = payload.notes
    db.commit()

    # Their collab posts may already be in the network tables — attribute now
    # so the tracking page is populated immediately, not tomorrow at 05:30.
    attribute_posts(db)
    db.refresh(a)
    return _to_out(a)


@router.post("/{ambassador_id}/update", response_model=AmbassadorOut)
def update_ambassador(ambassador_id: int, payload: AmbassadorUpdate, db: Session = Depends(get_db)):
    a = db.query(Ambassador).filter(Ambassador.id == ambassador_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Ambassador not found")

    fields = payload.model_dump(exclude_unset=True)
    now = datetime.now(tz=timezone.utc)
    reattribute = False

    if "status" in fields:
        if fields["status"] not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {VALID_STATUSES}")
        if fields["status"] == "confirmed" and a.status != "confirmed":
            reattribute = True
        a.status = fields["status"]

    if "ig_username" in fields:
        new_username = normalize_username(fields["ig_username"])
        if not new_username:
            raise HTTPException(status_code=400, detail="ig_username cannot be empty")
        if new_username != a.ig_username:
            conflict = db.query(Ambassador).filter(Ambassador.ig_username == new_username).first()
            if conflict:
                raise HTTPException(status_code=409, detail=f"@{new_username} is already ambassador id {conflict.id}")
            if a.ig_username:  # sheet-only rows have no prior handle to trail
                trail = {u for u in (a.previous_usernames or "").split(",") if u}
                trail.add(a.ig_username)
                a.previous_usernames = ",".join(sorted(trail))
            a.ig_username = new_username
            reattribute = True

    if "campus" in fields:
        if fields["campus"]:
            a.campus = fields["campus"]
            a.campus_source = "manual"
        else:
            # Explicit null/empty clears the campus and re-opens inference.
            a.campus = None
            a.campus_source = "inferred"

    if "athlete_id" in fields:
        _validate_athlete(db, fields["athlete_id"])
        a.athlete_id = fields["athlete_id"]

    for key in ROSTER_FIELDS + ("active", "notes"):
        if key in fields:
            setattr(a, key, fields[key])

    a.updated_at = now
    db.commit()

    if reattribute:
        attribute_posts(db)
    db.refresh(a)
    return _to_out(a)
