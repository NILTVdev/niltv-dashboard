import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, cast, Date, func as sqlfunc
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.config import get_settings
from backend.database import get_db
from backend.models import AthletePost, ZoomphPost, ZoomphPostSnapshot

logger = logging.getLogger(__name__)


def _apply_date_filter(query, start_date: Optional[date], end_date: Optional[date]):
    """Apply optional date range filter on ZoomphPost.posted_at."""
    if start_date:
        query = query.filter(ZoomphPost.posted_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(ZoomphPost.posted_at < datetime.combine(end_date, datetime.min.time()))
    return query

router = APIRouter(dependencies=[Depends(require_api_key)])


class ZoomphOut(BaseModel):
    id: int
    pulled_at: datetime
    post_id: str
    partner: Optional[str]
    platform: Optional[str]
    content_type: Optional[str]
    author: Optional[str]
    url: Optional[str]
    message: Optional[str]
    posted_at: Optional[datetime]
    partner_mention_type: Optional[str]
    # Engagement
    engagement: Optional[int]
    like_count: Optional[int]
    comment_count: Optional[int]
    save_count: Optional[int]
    share_count: Optional[int]
    reply_count: Optional[int]
    # Reach / rates
    impressions: Optional[int]
    reach: Optional[int]
    projected_impressions: Optional[int]
    follower_count: Optional[int]
    engagement_rate: Optional[float]
    follower_interaction_rate: Optional[float]
    # Value
    brand_exposure_value: Optional[float]
    valuation: Optional[float] = None  # server-side CPM/CPE/CPV; None without a rate card
    post_value: Optional[float]
    brand_exposure_value_us: Optional[float]
    # Sentiment / context
    sentiment: Optional[str]
    hashtags: Optional[str]
    mentions: Optional[str]
    language: Optional[str]
    # Video / streaming
    vod_views: Optional[int]
    view_count: Optional[int]
    live_views: Optional[int]
    avg_concurrent_viewers: Optional[int]
    peak_live_viewer_count: Optional[int]
    hours_watched: Optional[int]
    # Logo AI
    logo_total_seconds: Optional[float]
    logo_avg_size: Optional[float]
    logo_avg_clarity: Optional[float]
    logo_impressions: Optional[int]
    logo_location: Optional[str]

    class Config:
        from_attributes = True


# Numeric/Decimal columns that need explicit float() conversion for JSON
_NUMERIC_FIELDS = [
    "brand_exposure_value", "post_value", "brand_exposure_value_us",
    "engagement_rate", "follower_interaction_rate",
    "logo_total_seconds", "logo_avg_size", "logo_avg_clarity",
]


@router.get("/", response_model=list[ZoomphOut])
def list_zoomph_posts(
    limit: int = 100,
    platform: Optional[str] = None,
    author: Optional[str] = None,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ZoomphPost)
    if platform:
        query = query.filter(ZoomphPost.platform == platform)
    if author:
        query = query.filter(ZoomphPost.author == author)
    query = _apply_date_filter(query, start_date, end_date)
    # Sort by posted_at desc; nulls go last via NULLS LAST
    rows = query.order_by(ZoomphPost.posted_at.desc().nullslast()).limit(limit).all()

    # Cross-reference: for posts with null posted_at, look up date from athlete_posts
    null_date_urls = [r.url for r in rows if r.posted_at is None and r.url]
    permalink_dates: dict[str, datetime] = {}
    if null_date_urls:
        matches = (
            db.query(AthletePost.permalink, AthletePost.posted_at)
            .filter(AthletePost.permalink.in_(null_date_urls), AthletePost.posted_at.isnot(None))
            .all()
        )
        permalink_dates = {m.permalink: m.posted_at for m in matches}

    for row in rows:
        if row.posted_at is None and row.url:
            row.posted_at = permalink_dates.get(row.url)  # stays None if no match
        for field in _NUMERIC_FIELDS:
            val = getattr(row, field, None)
            if val is not None:
                setattr(row, field, float(val))
        row.valuation = calc_value(
            _platform_key(row.platform, row.content_type),
            int(row.impressions or 0), int(row.engagement or 0),
            int(row.vod_views or 0), int(row.live_views or 0),
        )

    return rows


@router.get("/authors")
def zoomph_authors(db: Session = Depends(get_db)):
    """Return distinct non-null author handles."""
    rows = (
        db.query(ZoomphPost.author)
        .filter(ZoomphPost.author.isnot(None))
        .distinct()
        .all()
    )
    return sorted([r[0] for r in rows])


def _rate_card() -> dict:
    """Valuation rate card from VALUATION_RATES (JSON). Empty -> no computed
    valuation; callers fall back to the source-provided exposure value."""
    raw = get_settings().valuation_rates
    if not raw:
        return {}
    try:
        card = json.loads(raw)
    except ValueError:
        logger.warning("VALUATION_RATES is not valid JSON; valuation disabled")
        return {}
    return card if isinstance(card, dict) else {}


def _platform_key(platform: Optional[str], content_type: Optional[str]) -> str:
    p = platform or ""
    if p == "Instagram" and content_type and "story" in content_type.lower():
        return "Instagram Story"
    return p


def calc_value(
    key: str, impressions: int, engagement: int,
    vod_views: int, live_views: int,
) -> Optional[float]:
    """CPM/CPE/CPV valuation for one platform bucket, or None without a rate card."""
    card = _rate_card()
    rates = card.get(key)
    if not isinstance(rates, dict):
        return None
    value = (
        (impressions / 1000) * float(rates.get("cpm", 0))
        + engagement * float(rates.get("cpe", 0))
        + vod_views * float(rates.get("cpv", 0))
    )
    if key == "YouTube" and live_views > 0:
        value += live_views * float(card.get("youtube_live_cpv", 0))
    return value


def _calc_platform_bev(
    key: str, impressions: int, engagement: int,
    vod_views: int, live_views: int, bev_sum: float,
) -> float:
    """Computed valuation for aggregated platform totals; source BEV when no rate card."""
    value = calc_value(key, impressions, engagement, vod_views, live_views)
    return bev_sum if value is None else value


@router.get("/summary")
def zoomph_summary(
    author: Optional[str] = None,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Aggregate engagement/impressions stats grouped by platform using SQL."""
    # CASE expression to split Instagram Stories from regular Instagram posts
    effective_platform = case(
        (
            (ZoomphPost.platform == "Instagram")
            & ZoomphPost.content_type.isnot(None)
            & ZoomphPost.content_type.ilike("%story%"),
            "Instagram Story",
        ),
        else_=sqlfunc.coalesce(ZoomphPost.platform, "Unknown"),
    ).label("eff_platform")

    base = db.query(
        effective_platform,
        sqlfunc.count().label("post_count"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.engagement), 0).label("total_engagement"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.impressions), 0).label("total_impressions"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.like_count), 0).label("total_likes"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.vod_views), 0).label("total_vod_views"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.live_views), 0).label("total_live_views"),
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.brand_exposure_value), 0).label("bev_sum"),
    )
    if author:
        base = base.filter(ZoomphPost.author == author)
    base = _apply_date_filter(base, start_date, end_date)
    rows = base.group_by(effective_platform).all()

    results = []
    for r in rows:
        results.append({
            "platform": r.eff_platform,
            "post_count": r.post_count,
            "total_engagement": int(r.total_engagement),
            "total_impressions": int(r.total_impressions),
            "total_likes": int(r.total_likes),
            "total_bev": _calc_platform_bev(
                r.eff_platform, int(r.total_impressions), int(r.total_engagement),
                int(r.total_vod_views), int(r.total_live_views), float(r.bev_sum),
            ),
        })
    return results


@router.get("/impressions-by-day")
def zoomph_impressions_by_day(
    author: Optional[str] = None,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Aggregate total impressions per day (by posted_at date). No row limit."""
    day_col = cast(ZoomphPost.posted_at, Date).label("day")
    query = db.query(
        day_col,
        sqlfunc.coalesce(sqlfunc.sum(ZoomphPost.impressions), 0).label("impressions"),
    ).filter(ZoomphPost.posted_at.isnot(None))
    if author:
        query = query.filter(ZoomphPost.author == author)
    query = _apply_date_filter(query, start_date, end_date)
    rows = query.group_by(day_col).order_by(day_col).all()
    return [{"date": r.day.isoformat(), "impressions": int(r.impressions)} for r in rows]


class ZoomphSnapshotOut(BaseModel):
    id: int
    captured_at: datetime
    engagement: Optional[int]
    like_count: Optional[int]
    comment_count: Optional[int]
    save_count: Optional[int]
    share_count: Optional[int]
    reply_count: Optional[int]
    impressions: Optional[int]
    reach: Optional[int]
    projected_impressions: Optional[int]
    follower_count: Optional[int]
    engagement_rate: Optional[float]
    follower_interaction_rate: Optional[float]
    brand_exposure_value: Optional[float]
    post_value: Optional[float]
    brand_exposure_value_us: Optional[float]
    vod_views: Optional[int]
    view_count: Optional[int]
    live_views: Optional[int]
    hours_watched: Optional[int]

    class Config:
        from_attributes = True


_SNAPSHOT_NUMERIC_FIELDS = [
    "engagement_rate", "follower_interaction_rate",
    "brand_exposure_value", "post_value", "brand_exposure_value_us",
]


@router.get("/{post_id}/history", response_model=list[ZoomphSnapshotOut])
def zoomph_post_history(
    post_id: str,
    db: Session = Depends(get_db),
):
    """Return the engagement snapshot history for a specific Zoomph post."""
    post = db.query(ZoomphPost).filter(ZoomphPost.post_id == post_id).first()
    if not post:
        return []

    snapshots = (
        db.query(ZoomphPostSnapshot)
        .filter(ZoomphPostSnapshot.zoomph_post_id == post.id)
        .order_by(ZoomphPostSnapshot.captured_at.asc())
        .all()
    )

    for snap in snapshots:
        for field in _SNAPSHOT_NUMERIC_FIELDS:
            val = getattr(snap, field, None)
            if val is not None:
                setattr(snap, field, float(val))

    return snapshots
