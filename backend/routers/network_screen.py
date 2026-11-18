"""
Network Screen router — /api/network-screen

Aggregated NIL TV channel performance metrics for the Channel Insights page.
Backed by Instagram (account='niltv') and YouTube (youtube_* tables, live once
run_youtube has written a snapshot). Each platform returns the same shape;
unavailable platforms return available=False so the frontend can render
"coming soon" states without code changes when new platforms are added.

The aggregate banner sums the live platforms: followers (Instagram followers
plus YouTube subscribers), views on posts published in the period, and posts
published in the period.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import BrandSnapshot, NiltvNetworkPost, YoutubeVideo
from backend.routers.youtube import last_in, snapshots_by_channel

router = APIRouter(dependencies=[Depends(require_api_key)])

NILTV_ACCOUNT = "niltv"

# Matches all posts on @niltv's channel: owned by niltv OR collab where niltv is tagged.
_NILTV_POST_FILTER = or_(
    NiltvNetworkPost.account_username == NILTV_ACCOUNT,
    NiltvNetworkPost.collab_accounts.contains(NILTV_ACCOUNT),
)


# ── Pydantic output models ────────────────────────────────────────────────────

class FormatStats(BaseModel):
    posts: int
    posts_with_views: int  # avg_views and engagement_rate cover only these posts
    total_views: int
    avg_views: float
    engagement_rate: Optional[float]  # None when views=0 for every post


class MonthStats(BaseModel):
    followers: Optional[int]
    new_followers_monthly: Optional[int]
    new_followers_weekly: Optional[int]
    posts_monthly: int
    posts_weekly: int
    avg_posts_per_week: float
    total_views_monthly: int
    total_views_weekly: int
    posts_with_views_monthly: int  # avg_views_per_post covers only these posts
    avg_views_per_post: Optional[float]
    format_breakdown: dict[str, FormatStats]
    engagement_rate_overall: Optional[float]
    collabs_published_monthly: Optional[int]  # None where the platform has no collabs (YouTube)
    # Collaborator-owned posts carry no shares/saves/reach (an IG platform limit),
    # so engagement rate on collabs is understated until a CSV backfill fills them.
    collab_data_warning: bool


class PlatformRatios(BaseModel):
    weekly_views_to_followers: Optional[float]
    views_per_post_to_followers: Optional[float]
    avg_views_per_reel: Optional[float]
    engagement_rate_reels: Optional[float]


class PlatformSummary(BaseModel):
    platform: str
    available: bool
    current_month: Optional[MonthStats] = None
    prior_month: Optional[MonthStats] = None
    ratios: Optional[PlatformRatios] = None


class Aggregate(BaseModel):
    total_followers: int
    total_views_monthly: int
    total_posts_monthly: int
    platforms_live: int
    platforms_total: int


class WeeklyStats(BaseModel):
    start: datetime
    end: datetime
    posts: int
    views: int
    new_followers: Optional[int]


class WeeklyComparison(BaseModel):
    current: WeeklyStats
    previous: WeeklyStats


class NetworkScreenSummary(BaseModel):
    platforms: list[PlatformSummary]
    aggregate: Aggregate
    weekly_comparison: WeeklyComparison


class TopPost(BaseModel):
    id: int
    post_id: str
    publish_time: Optional[datetime]
    post_type: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]
    shares: Optional[int]
    saves: Optional[int]
    reach: Optional[int]
    permalink: Optional[str]
    thumbnail_url: Optional[str]
    description: Optional[str]

    class Config:
        from_attributes = True


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return (start_inclusive, end_exclusive) UTC datetimes for a calendar month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Return the last seven UTC calendar days, including today."""
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return end - timedelta(days=7), end


def _prev_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    this_start, _ = _week_bounds(now)
    prev_start = this_start - timedelta(days=7)
    return prev_start, this_start


def _follower_delta(db: Session, start: datetime, end: datetime) -> Optional[int]:
    latest = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at < end,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    baseline = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at < start,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    if not latest or not baseline:
        return None
    return int(latest.followers) - int(baseline.followers)


def _weekly_stats(db: Session, start: datetime, end: datetime) -> WeeklyStats:
    row = (
        db.query(
            func.count(NiltvNetworkPost.id),
            func.coalesce(func.sum(NiltvNetworkPost.views), 0),
        )
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.publish_time >= start,
            NiltvNetworkPost.publish_time < end,
        )
        .one()
    )
    return WeeklyStats(
        start=start,
        end=end,
        posts=int(row[0]),
        views=int(row[1]),
        new_followers=_follower_delta(db, start, end),
    )


def _weekly_comparison(db: Session, now: datetime) -> WeeklyComparison:
    current_start, current_end = _week_bounds(now)
    previous_start, previous_end = _prev_week_bounds(now)
    return WeeklyComparison(
        current=_weekly_stats(db, current_start, current_end),
        previous=_weekly_stats(db, previous_start, previous_end),
    )


def _engagement(likes, comments, shares, saves, views) -> Optional[float]:
    """Return engagement rate as a percentage, or None when views=0."""
    total = (likes or 0) + (comments or 0) + (shares or 0) + (saves or 0)
    if not views:
        return None
    return round(total / views * 100, 2)


def _rate_for(posts: list[NiltvNetworkPost]) -> Optional[float]:
    """Engagement rate over `posts`. Pass only posts with a views count, so the
    numerator never holds engagement from posts missing from the denominator."""
    return _engagement(
        sum(p.likes or 0 for p in posts),
        sum(p.comments or 0 for p in posts),
        sum(p.shares or 0 for p in posts),
        sum(p.saves or 0 for p in posts),
        sum(p.views or 0 for p in posts),
    )


def _compute_month_stats(
    db: Session,
    year: int,
    month: int,
    now: datetime,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
) -> MonthStats:
    month_start, month_end = _month_bounds(year, month)
    if period_start is not None and period_end is not None:
        month_start, month_end = period_start, period_end
    stats_now = min(now, month_end - __import__("datetime").timedelta(microseconds=1))
    week_start, week_end = _week_bounds(stats_now)
    # The ISO week around a completed period's final day spills into the next
    # month; clamp so a finished column never counts days past its own end.
    week_end = min(week_end, month_end)

    # Use niltv_network_posts (full history) filtered to niltv's own posts.
    # brand_posts only has recent ~25 posts per nightly run; network_posts has everything.
    # post_type uses media_product_type so Reels are correctly labeled "REELS" (not "VIDEO").
    import datetime as dt

    # ── Posts in window ───────────────────────────────────────────────────────
    posts_month = (
        db.query(NiltvNetworkPost)
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.publish_time >= month_start,
            NiltvNetworkPost.publish_time < month_end,
        )
        .all()
    )
    posts_monthly = len(posts_month)

    posts_weekly = (
        db.query(func.count(NiltvNetworkPost.id))
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.publish_time >= week_start,
            NiltvNetworkPost.publish_time < week_end,
        )
        .scalar() or 0
    )

    # Rolling 4-week avg
    four_weeks_ago = stats_now - dt.timedelta(days=28)
    rolling_count = (
        db.query(func.count(NiltvNetworkPost.id))
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.publish_time >= four_weeks_ago,
            NiltvNetworkPost.publish_time < stats_now,
        )
        .scalar() or 0
    )
    avg_posts_per_week = round(rolling_count / 4, 1)

    # ── Views ─────────────────────────────────────────────────────────────────
    total_views_monthly = sum(p.views or 0 for p in posts_month)
    total_views_weekly = (
        db.query(func.coalesce(func.sum(NiltvNetworkPost.views), 0))
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.publish_time >= week_start,
            NiltvNetworkPost.publish_time < week_end,
        )
        .scalar() or 0
    )

    # Images, carousels and reels whose owner hides the count have views=None.
    # That means unknown, not zero, so averages and rates leave those posts out.
    # A post with a real count of 0 still counts.
    posts_with_views = [p for p in posts_month if p.views is not None]
    avg_views_per_post = (
        round(total_views_monthly / len(posts_with_views), 1) if posts_with_views else None
    )

    # ── Format breakdown ──────────────────────────────────────────────────────
    format_breakdown: dict[str, FormatStats] = {}
    from itertools import groupby
    sorted_posts = sorted(posts_month, key=lambda p: p.post_type or "")
    for fmt, group in groupby(sorted_posts, key=lambda p: p.post_type or "OTHER"):
        gp = list(group)
        known = [p for p in gp if p.views is not None]
        fv = sum(p.views for p in known)
        format_breakdown[fmt] = FormatStats(
            posts=len(gp),
            posts_with_views=len(known),
            total_views=fv,
            avg_views=round(fv / len(known), 1) if known else 0.0,
            engagement_rate=_rate_for(known),
        )

    # ── Overall engagement ────────────────────────────────────────────────────
    engagement_rate_overall = _rate_for(posts_with_views)

    # ── Followers ─────────────────────────────────────────────────────────────
    # Failed pulls write sentinel snapshot rows with followers=NULL (see
    # run_brand_ig). Those must never be picked as a baseline: `followers or 0`
    # would turn the NULL into 0 and report the entire follower count as new.
    # Every lookup therefore skips NULL-followers rows and lands on the last
    # real count instead.
    latest_snap = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at < month_end,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    followers = latest_snap.followers if latest_snap else None

    # Monthly follower delta: latest snap this month minus latest snap prior month
    prior_month_end = month_start
    prior_month_snap = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at < prior_month_end,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    new_followers_monthly = (
        (latest_snap.followers or 0) - (prior_month_snap.followers or 0)
        if latest_snap and prior_month_snap
        else None
    )

    # Weekly follower delta
    prev_week_start, prev_week_end = _prev_week_bounds(stats_now)
    snap_this_week = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at >= week_start,
            BrandSnapshot.pulled_at < week_end,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    snap_last_week = (
        db.query(BrandSnapshot)
        .filter(
            BrandSnapshot.account == NILTV_ACCOUNT,
            BrandSnapshot.followers.isnot(None),
            BrandSnapshot.pulled_at >= prev_week_start,
            BrandSnapshot.pulled_at < prev_week_end,
        )
        .order_by(BrandSnapshot.pulled_at.desc())
        .first()
    )
    new_followers_weekly = (
        (snap_this_week.followers or 0) - (snap_last_week.followers or 0)
        if snap_this_week and snap_last_week
        else None
    )

    # Collabs = posts on the niltv channel NOT owned by niltv (athlete-originated collabs)
    collabs_monthly = (
        db.query(func.count(NiltvNetworkPost.id))
        .filter(
            NiltvNetworkPost.account_username != NILTV_ACCOUNT,
            NiltvNetworkPost.collab_accounts.contains(NILTV_ACCOUNT),
            NiltvNetworkPost.publish_time >= month_start,
            NiltvNetworkPost.publish_time < month_end,
        )
        .scalar() or 0
    )

    return MonthStats(
        followers=followers,
        new_followers_monthly=new_followers_monthly,
        new_followers_weekly=new_followers_weekly,
        posts_monthly=posts_monthly,
        posts_weekly=posts_weekly,
        avg_posts_per_week=avg_posts_per_week,
        total_views_monthly=total_views_monthly,
        total_views_weekly=int(total_views_weekly),
        posts_with_views_monthly=len(posts_with_views),
        avg_views_per_post=avg_views_per_post,
        format_breakdown=format_breakdown,
        engagement_rate_overall=engagement_rate_overall,
        collabs_published_monthly=int(collabs_monthly),
        collab_data_warning=True,  # shares/saves/reach missing on collaborator-owned posts
    )


def _compute_ratios(current: MonthStats, reel_key: str = "REELS") -> PlatformRatios:
    followers = current.followers or 0

    weekly_views_to_followers = (
        round(current.total_views_weekly / followers, 2)
        if followers and current.total_views_weekly
        else None
    )
    avg_views = current.avg_views_per_post
    views_per_post_to_followers = (
        round(avg_views / followers, 2)
        if followers and avg_views
        else None
    )

    # Instagram: REELS (niltv_network_posts.post_type uses media_product_type).
    # YouTube: SHORTS, the closest equivalent.
    reel_stats = current.format_breakdown.get(reel_key)
    avg_views_per_reel = (
        reel_stats.avg_views if reel_stats and reel_stats.avg_views else None
    )
    engagement_rate_reels = (
        reel_stats.engagement_rate if reel_stats else None
    )

    return PlatformRatios(
        weekly_views_to_followers=weekly_views_to_followers,
        views_per_post_to_followers=views_per_post_to_followers,
        avg_views_per_reel=avg_views_per_reel,
        engagement_rate_reels=engagement_rate_reels,
    )


# ── YouTube ───────────────────────────────────────────────────────────────────

def _window(year: int, month: int, period_start: Optional[datetime],
            period_end: Optional[datetime]) -> tuple[datetime, datetime]:
    if period_start is not None and period_end is not None:
        return period_start, period_end
    return _month_bounds(year, month)


def _baseline_floor(start: datetime, end: datetime) -> datetime:
    """Earliest snapshot that may serve as a period's starting point. A
    calendar-month period needs one from the month before; any other period
    needs one from the equally long stretch just before it."""
    if start == start.replace(day=1, hour=0, minute=0, second=0, microsecond=0):
        prev_end = start - timedelta(days=1)
        return datetime(prev_end.year, prev_end.month, 1, tzinfo=timezone.utc)
    return start - (end - start)


def _sum_latest(snaps: dict[str, list], start, end) -> Optional[int]:
    """Subscribers summed over channels: each channel's last snapshot in [start, end)."""
    vals = [s.subscribers for rows in snaps.values()
            for s in [last_in(rows, start, end)] if s is not None and s.subscribers is not None]
    return sum(vals) if vals else None


def _sum_change(snaps: dict[str, list], cur: tuple, base: tuple) -> Optional[int]:
    """Subscriber change summed over the channels that have a snapshot in both
    windows. None when no channel does: a missing end is unknown, not 0."""
    deltas = []
    for rows in snaps.values():
        a, b = last_in(rows, *cur), last_in(rows, *base)
        if a is not None and b is not None and a.subscribers is not None and b.subscribers is not None:
            deltas.append(int(a.subscribers) - int(b.subscribers))
    return sum(deltas) if deltas else None


def _youtube_engagement(videos: list) -> Optional[float]:
    # YouTube has no public shares or saves: likes + comments over views.
    return _engagement(
        sum(v.likes or 0 for v in videos), sum(v.comments or 0 for v in videos), 0, 0,
        sum(v.views or 0 for v in videos))


def _youtube_format(v) -> str:
    if v.is_short is None:
        return "OTHER"
    return "SHORTS" if v.is_short else "LONG_FORM"


def _youtube_week(db: Session, snaps: dict[str, list], now: datetime,
                  weeks_back: int = 0) -> tuple[int, int, Optional[int]]:
    """(videos published, their views, subscriber change) for the rolling
    seven-day window `weeks_back` weeks before the latest one."""
    end = _week_bounds(now)[1] - timedelta(days=7 * weeks_back)
    start = end - timedelta(days=7)
    videos = (db.query(YoutubeVideo)
              .filter(YoutubeVideo.published_at >= start, YoutubeVideo.published_at < end).all())
    change = _sum_change(snaps, (start.date(), end.date()),
                         ((start - timedelta(days=7)).date(), start.date()))
    return len(videos), sum(v.views or 0 for v in videos), change


def _compute_youtube_stats(
    db: Session,
    snaps: dict[str, list],
    year: int,
    month: int,
    now: datetime,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
) -> MonthStats:
    """The Instagram MonthStats shape filled from YouTube data. Subscriber
    numbers come from the daily channel snapshots; post and view numbers from
    the videos published in the period (their current view counts, the same
    rule Instagram uses)."""
    start, end = _window(year, month, period_start, period_end)
    stats_now = min(now, end - timedelta(microseconds=1))
    week_posts, week_views, week_subs = _youtube_week(db, snaps, now)
    d = lambda t: t.date()  # noqa: E731 - snapshots are keyed by UTC day

    def published(a: datetime, b: datetime) -> list:
        return (db.query(YoutubeVideo)
                .filter(YoutubeVideo.published_at >= a, YoutubeVideo.published_at < b).all())

    videos = published(start, end)
    rolling = published(stats_now - timedelta(days=28), stats_now)
    with_views = [v for v in videos if v.views is not None]
    total_views = sum(v.views for v in with_views)

    breakdown: dict[str, FormatStats] = {}
    for key in sorted({_youtube_format(v) for v in videos}):
        group = [v for v in videos if _youtube_format(v) == key]
        known = [v for v in group if v.views is not None]
        fv = sum(v.views for v in known)
        breakdown[key] = FormatStats(
            posts=len(group),
            posts_with_views=len(known),
            total_views=fv,
            avg_views=round(fv / len(known), 1) if known else 0.0,
            engagement_rate=_youtube_engagement(known),
        )

    floor = _baseline_floor(start, end)
    return MonthStats(
        followers=_sum_latest(snaps, None, d(end)),
        new_followers_monthly=_sum_change(snaps, (d(start), d(end)), (d(floor), d(start))),
        new_followers_weekly=week_subs,
        posts_monthly=len(videos),
        posts_weekly=week_posts,
        avg_posts_per_week=round(len(rolling) / 4, 1),
        total_views_monthly=total_views,
        total_views_weekly=week_views,
        posts_with_views_monthly=len(with_views),
        avg_views_per_post=round(total_views / len(with_views), 1) if with_views else None,
        format_breakdown=breakdown,
        engagement_rate_overall=_youtube_engagement(with_views),
        collabs_published_monthly=None,
        collab_data_warning=False,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=NetworkScreenSummary)
def network_screen_summary(
    mode: Literal["month", "mtd", "rolling30", "prevmonth"] = Query("month"),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    weekly = _weekly_comparison(db, now)
    cur_year, cur_month = now.year, now.month

    # Prior month
    if cur_month == 1:
        prev_year, prev_month = cur_year - 1, 12
    else:
        prev_year, prev_month = cur_year, cur_month - 1

    if mode == "month":
        cur_args = (cur_year, cur_month, now)
        prior_args = (prev_year, prev_month, now)
    elif mode == "prevmonth":
        # The last COMPLETE month as the primary column (e.g. August on Sep 1),
        # compared against the month before it.
        if prev_month == 1:
            prev2_year, prev2_month = prev_year - 1, 12
        else:
            prev2_year, prev2_month = prev_year, prev_month - 1
        cur_args = (prev_year, prev_month, now)
        prior_args = (prev2_year, prev2_month, now)
    elif mode == "mtd":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_start = today_start.replace(day=1)
        elapsed = today_start - current_start
        prior_start = (
            datetime(prev_year, prev_month, 1, tzinfo=timezone.utc)
        )
        current_end = today_start + __import__("datetime").timedelta(days=1)
        prior_calendar_end = _month_bounds(prev_year, prev_month)[1]
        prior_end = min(
            prior_start + elapsed + __import__("datetime").timedelta(days=1),
            prior_calendar_end,
        )
        cur_args = (cur_year, cur_month, now, current_start, current_end)
        prior_args = (prev_year, prev_month, now, prior_start, prior_end)
    else:
        import datetime as dt
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        current_end = today_start + dt.timedelta(days=1)
        current_start = today_start - dt.timedelta(days=29)
        prior_end = current_start
        prior_start = prior_end - dt.timedelta(days=30)
        cur_args = (cur_year, cur_month, now, current_start, current_end)
        prior_args = (prev_year, prev_month, now, prior_start, prior_end)
    current = _compute_month_stats(db, *cur_args)
    prior = _compute_month_stats(db, *prior_args)
    # Week metrics are always rolling seven-day windows, independent of the
    # selected month/30-day comparison mode.
    current.posts_weekly = weekly.current.posts
    current.total_views_weekly = weekly.current.views
    current.new_followers_weekly = weekly.current.new_followers
    prior.posts_weekly = weekly.previous.posts
    prior.total_views_weekly = weekly.previous.views
    prior.new_followers_weekly = weekly.previous.new_followers
    ratios = _compute_ratios(current)

    instagram = PlatformSummary(
        platform="instagram",
        available=True,
        current_month=current,
        prior_month=prior,
        ratios=ratios,
    )

    # YouTube goes live with its first channel snapshot (run_youtube).
    yt_snaps = snapshots_by_channel(db)
    if yt_snaps:
        yt_current = _compute_youtube_stats(db, yt_snaps, *cur_args)
        yt_prior = _compute_youtube_stats(db, yt_snaps, *prior_args)
        # Same rule as Instagram: the prior column's week is the previous seven days.
        (yt_prior.posts_weekly, yt_prior.total_views_weekly,
         yt_prior.new_followers_weekly) = _youtube_week(db, yt_snaps, now, weeks_back=1)
        youtube = PlatformSummary(
            platform="youtube",
            available=True,
            current_month=yt_current,
            prior_month=yt_prior,
            ratios=_compute_ratios(yt_current, reel_key="SHORTS"),
        )
    else:
        youtube = PlatformSummary(platform="youtube", available=False)

    # Stubs — fill in as each platform is connected
    platforms = [
        instagram,
        PlatformSummary(platform="facebook", available=False),
        youtube,
        PlatformSummary(platform="tiktok", available=False),
        PlatformSummary(platform="snapchat", available=False),
        PlatformSummary(platform="linkedin", available=False),
    ]
    # A platform counts toward the banner only when it has data for the
    # period. Instagram keeps its original rule (always counted). Other
    # platforms need a follower number for the period: a YouTube channel with
    # no snapshot by the period's end is unknown, not zero, so it stays out of
    # both the sums and platforms_live.
    live = [
        p.current_month for p in platforms
        if p.available and p.current_month
        and (p.platform == "instagram" or p.current_month.followers is not None)
    ]

    # Sums across live platforms: Instagram followers + YouTube subscribers,
    # views on posts published in the period, posts published in the period.
    aggregate = Aggregate(
        total_followers=sum(m.followers or 0 for m in live),
        total_views_monthly=sum(m.total_views_monthly for m in live),
        total_posts_monthly=sum(m.posts_monthly for m in live),
        platforms_live=len(live),
        platforms_total=len(platforms),
    )

    return NetworkScreenSummary(
        platforms=platforms,
        aggregate=aggregate,
        weekly_comparison=weekly,
    )


@router.get("/top-posts", response_model=list[TopPost])
def network_screen_top_posts(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Top niltv-owned posts by view count."""
    return (
        db.query(NiltvNetworkPost)
        .filter(
            _NILTV_POST_FILTER,
            NiltvNetworkPost.views.isnot(None),
        )
        .order_by(NiltvNetworkPost.views.desc())
        .limit(limit)
        .all()
    )
