"""
YouTube router: /api/youtube

  GET /summary    per channel: latest subscribers / views / videos, 7-day,
                  28-day and calendar-month changes, and the daily snapshot
                  series for charts
  GET /videos     uploads, paged, sorted and filtered (Shorts / long-form, title)
  GET /status     is the API key set, when was the last pull, is Analytics connected
  GET /analytics  watch time and retention from the YouTube Analytics API,
                  or {"connected": false} until the channel owner approves access

Read-only. Data comes from backend.jobs.run_youtube (public counts) and
backend.jobs.run_youtube_analytics (owner consent).

Changes are differences between two daily snapshots, so they need a snapshot
at both ends. A change with no snapshot at the far end is null, never 0: a
7-day change needs a snapshot 7 to 10 days before the latest one, and a month
change needs a snapshot in each of the two months.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.config import get_settings
from backend.database import get_db
from backend.models import (
    YoutubeChannel, YoutubeChannelSnapshot, YoutubeDailyAnalytics, YoutubeVideo,
    YoutubeVideoAnalytics,
)

router = APIRouter(dependencies=[Depends(require_api_key)])

# A 7-day change may start up to this many days earlier when a nightly pull
# was missed. Further back, the number would describe a longer period.
GRACE_DAYS = 3
SERIES_DAYS = 365
ANALYTICS_WINDOW = 28
TOP_VIDEOS_BY_WATCH = 20


# ── Snapshot math (shared with the network screen) ───────────────────────────

def month_start(d: date) -> date:
    return d.replace(day=1)


def prev_month_start(d: date) -> date:
    first = d.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


def next_month_start(d: date) -> date:
    first = d.replace(day=1)
    return (first + timedelta(days=32)).replace(day=1)


def last_in(snaps: list, start: Optional[date], end: date):
    """Latest snapshot with start <= day < end (start None = no lower bound).
    `snaps` must be sorted by day ascending."""
    found = None
    for s in snaps:
        if s.day >= end:
            break
        if start is None or s.day >= start:
            found = s
    return found


def _diff(a, b, field: str) -> Optional[int]:
    if a is None or b is None:
        return None
    va, vb = getattr(a, field), getattr(b, field)
    if va is None or vb is None:
        return None
    return int(va) - int(vb)


def change_over_days(snaps: list, days: int, field: str) -> Optional[int]:
    """Latest snapshot minus the one `days` days before it (or up to
    GRACE_DAYS earlier). None when there is no such snapshot."""
    if not snaps:
        return None
    latest = snaps[-1]
    target = latest.day - timedelta(days=days)
    base = last_in(snaps, target - timedelta(days=GRACE_DAYS), target + timedelta(days=1))
    return _diff(latest, base, field)


def change_in_month(snaps: list, month: date, field: str) -> Optional[int]:
    """Last snapshot inside `month` minus the last snapshot of the month
    before. None unless both months have a snapshot."""
    start = month_start(month)
    current = last_in(snaps, start, next_month_start(start))
    base = last_in(snaps, prev_month_start(start), start)
    return _diff(current, base, field)


def snapshots_by_channel(db: Session, since: Optional[date] = None) -> dict[str, list]:
    q = db.query(YoutubeChannelSnapshot)
    if since is not None:
        q = q.filter(YoutubeChannelSnapshot.day >= since)
    out: dict[str, list] = {}
    for s in q.order_by(YoutubeChannelSnapshot.channel_id, YoutubeChannelSnapshot.day).all():
        out.setdefault(s.channel_id, []).append(s)
    return out


# ── Output models ────────────────────────────────────────────────────────────

class SnapshotPoint(BaseModel):
    day: date
    subscribers: Optional[int]
    total_views: Optional[int]
    video_count: Optional[int]


class ChannelChanges(BaseModel):
    subscribers_7d: Optional[int]
    subscribers_28d: Optional[int]
    subscribers_month: Optional[int]
    subscribers_prior_month: Optional[int]
    views_7d: Optional[int]
    views_28d: Optional[int]
    views_month: Optional[int]
    views_prior_month: Optional[int]


class ChannelSummary(BaseModel):
    channel_id: str
    title: Optional[str]
    handle: Optional[str]
    thumbnail_url: Optional[str]
    url: str
    latest_day: date
    pulled_at: datetime
    subscribers: Optional[int]
    total_views: Optional[int]
    video_count: Optional[int]
    changes: ChannelChanges
    series: list[SnapshotPoint]


class YoutubeSummary(BaseModel):
    channels: list[ChannelSummary]
    last_pulled: Optional[datetime]


class VideoRow(BaseModel):
    video_id: str
    channel_id: str
    title: Optional[str]
    published_at: Optional[datetime]
    duration_sec: Optional[int]
    is_short: Optional[bool]
    thumbnail_url: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]
    views_per_day: Optional[float]
    url: str


class VideoPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[VideoRow]


class YoutubeStatus(BaseModel):
    configured: bool
    channel_ids: list[str]
    channels_tracked: int
    videos_tracked: int
    last_pull: Optional[datetime]
    analytics_connected: bool
    last_analytics_pull: Optional[datetime]


class AnalyticsDay(BaseModel):
    day: date
    views: Optional[int]
    watch_hours: Optional[float]
    average_view_duration_sec: Optional[int]
    average_view_percentage: Optional[float]
    subscribers_gained: Optional[int]
    subscribers_lost: Optional[int]


class AnalyticsTotals(BaseModel):
    days: int
    start: Optional[date]
    end: Optional[date]
    views: int
    watch_hours: float
    # View-weighted means of the daily values.
    average_view_duration_sec: Optional[int]
    average_view_percentage: Optional[float]
    subscribers_net: Optional[int]


class AnalyticsVideo(BaseModel):
    video_id: str
    title: Optional[str]
    thumbnail_url: Optional[str]
    is_short: Optional[bool]
    url: str
    views: Optional[int]
    watch_hours: Optional[float]
    average_view_duration_sec: Optional[int]
    average_view_percentage: Optional[float]


class YoutubeAnalytics(BaseModel):
    connected: bool
    channel_id: Optional[str] = None
    last_pulled: Optional[datetime] = None
    daily: list[AnalyticsDay] = []
    totals_28d: Optional[AnalyticsTotals] = None
    top_videos_period_end: Optional[date] = None
    top_videos: list[AnalyticsVideo] = []


def _hours(minutes) -> Optional[float]:
    return round(int(minutes) / 60, 1) if minutes is not None else None


def _video_url(video_id: str, short: Optional[bool]) -> str:
    return f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{video_id}"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=YoutubeSummary)
def youtube_summary(db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    snaps = snapshots_by_channel(db)
    channels = {c.channel_id: c for c in db.query(YoutubeChannel).all()}
    out: list[ChannelSummary] = []
    for channel_id, rows in snaps.items():
        latest = rows[-1]
        ch = channels.get(channel_id)
        handle = ch.handle if ch else None
        out.append(ChannelSummary(
            channel_id=channel_id,
            title=ch.title if ch else None,
            handle=handle,
            thumbnail_url=ch.thumbnail_url if ch else None,
            url=f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{channel_id}",
            latest_day=latest.day,
            pulled_at=latest.pulled_at,
            subscribers=latest.subscribers,
            total_views=latest.total_views,
            video_count=latest.video_count,
            changes=ChannelChanges(
                subscribers_7d=change_over_days(rows, 7, "subscribers"),
                subscribers_28d=change_over_days(rows, 28, "subscribers"),
                subscribers_month=change_in_month(rows, today, "subscribers"),
                subscribers_prior_month=change_in_month(rows, prev_month_start(today), "subscribers"),
                views_7d=change_over_days(rows, 7, "total_views"),
                views_28d=change_over_days(rows, 28, "total_views"),
                views_month=change_in_month(rows, today, "total_views"),
                views_prior_month=change_in_month(rows, prev_month_start(today), "total_views"),
            ),
            series=[SnapshotPoint(day=s.day, subscribers=s.subscribers, total_views=s.total_views,
                                  video_count=s.video_count)
                    for s in rows if s.day > today - timedelta(days=SERIES_DAYS)],
        ))
    out.sort(key=lambda c: -(c.subscribers or 0))
    last = max((c.pulled_at for c in out), default=None)
    return YoutubeSummary(channels=out, last_pulled=last)


@router.get("/videos", response_model=VideoPage)
def youtube_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    sort: Literal["views", "published", "views_per_day", "likes", "comments"] = Query("views"),
    order: Literal["desc", "asc"] = Query("desc"),
    kind: Literal["all", "shorts", "long"] = Query("all", alias="format"),
    q: Optional[str] = Query(None, max_length=200),
    channel_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # Days since publish, never under one, so a video from this morning is
    # not divided by a fraction of a day.
    age_days = func.greatest(
        func.extract("epoch", func.now() - YoutubeVideo.published_at) / 86400.0, 1.0)
    per_day = YoutubeVideo.views / age_days

    query = db.query(YoutubeVideo, per_day.label("views_per_day"))
    if channel_id:
        query = query.filter(YoutubeVideo.channel_id == channel_id)
    if kind == "shorts":
        query = query.filter(YoutubeVideo.is_short.is_(True))
    elif kind == "long":
        query = query.filter(or_(YoutubeVideo.is_short.is_(False), YoutubeVideo.is_short.is_(None)))
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(YoutubeVideo.title.ilike(pattern, escape="\\"))

    total = query.count()
    column = {
        "views": YoutubeVideo.views,
        "published": YoutubeVideo.published_at,
        "views_per_day": per_day,
        "likes": YoutubeVideo.likes,
        "comments": YoutubeVideo.comments,
    }[sort]
    ordered = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    rows = (query.order_by(ordered, YoutubeVideo.video_id)
            .offset((page - 1) * page_size).limit(page_size).all())
    return VideoPage(
        total=total, page=page, page_size=page_size,
        items=[VideoRow(
            video_id=v.video_id, channel_id=v.channel_id, title=v.title,
            published_at=v.published_at, duration_sec=v.duration_sec, is_short=v.is_short,
            thumbnail_url=v.thumbnail_url, views=v.views, likes=v.likes, comments=v.comments,
            views_per_day=round(float(vpd), 1) if vpd is not None else None,
            url=_video_url(v.video_id, v.is_short),
        ) for v, vpd in rows],
    )


@router.get("/status", response_model=YoutubeStatus)
def youtube_status(db: Session = Depends(get_db)):
    s = get_settings()
    return YoutubeStatus(
        configured=s.youtube_configured,
        channel_ids=s.youtube_channel_id_list(),
        channels_tracked=db.query(func.count(func.distinct(YoutubeChannelSnapshot.channel_id))).scalar() or 0,
        videos_tracked=db.query(func.count(YoutubeVideo.video_id)).scalar() or 0,
        last_pull=db.query(func.max(YoutubeChannelSnapshot.pulled_at)).scalar(),
        analytics_connected=s.youtube_analytics_configured,
        last_analytics_pull=db.query(func.max(YoutubeDailyAnalytics.pulled_at)).scalar(),
    )


def _weighted(rows: list, field: str) -> Optional[float]:
    pairs = [(getattr(r, field), r.views) for r in rows
             if getattr(r, field) is not None and r.views]
    weight = sum(v for _, v in pairs)
    if not weight:
        return None
    return sum(float(x) * v for x, v in pairs) / weight


@router.get("/analytics", response_model=YoutubeAnalytics)
def youtube_analytics(db: Session = Depends(get_db)):
    if not get_settings().youtube_analytics_configured:
        return YoutubeAnalytics(connected=False)

    latest = (db.query(YoutubeDailyAnalytics)
              .order_by(YoutubeDailyAnalytics.pulled_at.desc()).first())
    if latest is None:
        return YoutubeAnalytics(connected=True)
    channel_id = latest.channel_id

    daily = (db.query(YoutubeDailyAnalytics)
             .filter(YoutubeDailyAnalytics.channel_id == channel_id)
             .order_by(YoutubeDailyAnalytics.day.desc())
             .limit(90).all())[::-1]
    end = daily[-1].day
    window = [d for d in daily if d.day > end - timedelta(days=ANALYTICS_WINDOW)]
    gained = [d.subscribers_gained for d in window if d.subscribers_gained is not None]
    lost = [d.subscribers_lost for d in window if d.subscribers_lost is not None]
    avg_dur = _weighted(window, "average_view_duration_sec")
    avg_pct = _weighted(window, "average_view_percentage")
    totals = AnalyticsTotals(
        days=len(window),
        start=window[0].day if window else None,
        end=end,
        views=sum(d.views or 0 for d in window),
        watch_hours=round(sum(d.estimated_minutes_watched or 0 for d in window) / 60, 1),
        average_view_duration_sec=round(avg_dur) if avg_dur is not None else None,
        average_view_percentage=round(avg_pct, 1) if avg_pct is not None else None,
        subscribers_net=(sum(gained) - sum(lost)) if gained and lost else None,
    )

    period_end = (db.query(func.max(YoutubeVideoAnalytics.period_end))
                  .filter(YoutubeVideoAnalytics.window_days == ANALYTICS_WINDOW).scalar())
    top: list[AnalyticsVideo] = []
    if period_end is not None:
        rows = (db.query(YoutubeVideoAnalytics, YoutubeVideo)
                .outerjoin(YoutubeVideo, YoutubeVideo.video_id == YoutubeVideoAnalytics.video_id)
                .filter(YoutubeVideoAnalytics.period_end == period_end,
                        YoutubeVideoAnalytics.window_days == ANALYTICS_WINDOW)
                .order_by(YoutubeVideoAnalytics.estimated_minutes_watched.desc().nulls_last(),
                          YoutubeVideoAnalytics.video_id)
                .limit(TOP_VIDEOS_BY_WATCH).all())
        top = [AnalyticsVideo(
            video_id=a.video_id,
            title=v.title if v else None,
            thumbnail_url=v.thumbnail_url if v else None,
            is_short=v.is_short if v else None,
            url=_video_url(a.video_id, v.is_short if v else None),
            views=a.views,
            watch_hours=_hours(a.estimated_minutes_watched),
            average_view_duration_sec=a.average_view_duration_sec,
            average_view_percentage=float(a.average_view_percentage) if a.average_view_percentage is not None else None,
        ) for a, v in rows]

    return YoutubeAnalytics(
        connected=True,
        channel_id=channel_id,
        last_pulled=latest.pulled_at,
        daily=[AnalyticsDay(
            day=d.day, views=d.views, watch_hours=_hours(d.estimated_minutes_watched),
            average_view_duration_sec=d.average_view_duration_sec,
            average_view_percentage=float(d.average_view_percentage) if d.average_view_percentage is not None else None,
            subscribers_gained=d.subscribers_gained, subscribers_lost=d.subscribers_lost,
        ) for d in daily],
        totals_28d=totals,
        top_videos_period_end=period_end,
        top_videos=top,
    )
