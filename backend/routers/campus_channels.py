"""
Campus Channels router — /api/campus-channels

Per-channel performance for the NIL TV campus network. Every post lives in
niltv_network_posts (migration 026 merged the TrueBlue table in), so a channel's
posts are the rows whose `collab_accounts` list carries that channel's internal
account key — NOT rows whose `account_username` matches, which is the ORIGINAL
poster (an athlete's handle on a collab).

The primary table cuts windows on `publish_time`. Separate growth analytics use
per-post snapshots to measure views accrued between boundaries and report their
coverage when an older post lacks a usable starting snapshot.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import NiltvNetworkPost, NiltvNetworkPostSnapshot

router = APIRouter(dependencies=[Depends(require_api_key)])

# Internal account keys as written into niltv_network_posts.collab_accounts.
# Note: truebluetv has no underscore here (the IG handle @trueblue_tv does).
CAMPUS_CHANNELS: list[tuple[str, str]] = [
    ("truebluetv", "TrueBlue TV"),
    ("chapelhilltv", "Chapel Hill TV"),
    ("redpacktv", "Red Pack TV"),
    ("starkvilletv", "Starkville TV"),
    ("goldendometv", "Golden Dome TV"),
    ("dorecitytv", "Dore City TV"),
    ("collegestationtv", "College Station TV"),
    ("brazostv", "Brazos TV"),
]

# Business Discovery cannot read views/shares/saves/reach, so channels pulled
# that way depend on CSV uploads and can lag. Surfaced to the UI per channel.
BD_ONLY_CHANNELS = {"truebluetv"}

VIEW_SOURCES = ("graph", "export", "bd", "public")


# ── Output models ─────────────────────────────────────────────────────────────

class WindowStats(BaseModel):
    posts: int
    # None (not 0) when the window holds no view data at all, so the UI can tell
    # "nothing ingested" apart from "genuinely zero views".
    views: Optional[int]
    posts_with_views: int


class ViewGrowth(BaseModel):
    start: datetime
    end: datetime
    views_gained: Optional[int]
    posts_measured: int
    posts_missing_baseline: int
    regressed_posts: int
    coverage_pct: float


class ChannelSummary(BaseModel):
    channel: str
    label: str
    last_month: WindowStats
    current_month: WindowStats
    last_30_days: WindowStats
    all_time: WindowStats
    views_by_source: dict[str, int]
    latest_post_at: Optional[datetime]
    bd_only: bool
    monthly_growth: list[ViewGrowth]
    last_30_days_growth: ViewGrowth
    last_7_days_growth: ViewGrowth


class WindowRange(BaseModel):
    start: datetime
    end: datetime


class CampusChannelsSummary(BaseModel):
    generated_at: datetime
    windows: dict[str, WindowRange]
    channels: list[ChannelSummary]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """(start_inclusive, end_exclusive) UTC datetimes for a calendar month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _channel_match(channel: str):
    """Exact membership in the comma-separated collab_accounts list.

    A bare LIKE '%redpacktv%' would also match a longer key that contains it,
    so wrap both sides in commas and compare whole elements.
    """
    cleaned = func.replace(func.coalesce(NiltvNetworkPost.collab_accounts, ""), " ", "")
    return ("," + cleaned + ",").like(f"%,{channel},%")


def _window(rows: list[tuple[Optional[int], Optional[datetime]]],
            start: Optional[datetime],
            end: Optional[datetime]) -> WindowStats:
    """Aggregate pre-fetched (views, publish_time) rows over a time window."""
    posts = 0
    total = 0
    with_views = 0
    for views, published in rows:
        if start is not None:
            if published is None:
                continue
            # Postgres hands back aware datetimes; treat any naive value as UTC
            # rather than raising on the comparison.
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published < start or published >= end:
                continue
        posts += 1
        if views is not None:
            total += views
            with_views += 1
    return WindowStats(
        posts=posts,
        views=total if with_views else None,
        posts_with_views=with_views,
    )


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _latest_capture(
    captures: list[tuple[datetime, int]],
    boundary: datetime,
) -> Optional[int]:
    value = None
    for captured_at, views in captures:
        if captured_at > boundary:
            break
        value = views
    return value


def _growth(
    posts: list[NiltvNetworkPost],
    captures_by_post: dict[int, list[tuple[datetime, int]]],
    start: datetime,
    end: datetime,
    now: datetime,
) -> ViewGrowth:
    measured = 0
    missing_baseline = 0
    regressed = 0
    total_growth = 0

    for post in posts:
        published = _as_utc(post.publish_time)
        if published is None or published >= end:
            continue

        captures = captures_by_post.get(post.id, [])
        end_views = (
            post.views
            if end >= now and post.views is not None
            else _latest_capture(captures, end)
        )
        if end_views is None:
            continue

        start_views = _latest_capture(captures, start)
        if start_views is None:
            if published >= start:
                start_views = 0
            else:
                missing_baseline += 1
                continue

        delta = int(end_views) - int(start_views)
        if delta < 0:
            regressed += 1
            delta = 0
        total_growth += delta
        measured += 1

    eligible = measured + missing_baseline
    return ViewGrowth(
        start=start,
        end=end,
        views_gained=total_growth if measured else None,
        posts_measured=measured,
        posts_missing_baseline=missing_baseline,
        regressed_posts=regressed,
        coverage_pct=round(measured / eligible * 100, 1) if eligible else 0.0,
    )


def _monthly_ranges(now: datetime, count: int = 6) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    year, month = now.year, now.month
    for offset in range(count - 1, -1, -1):
        y, m = year, month
        for _ in range(offset):
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        start, calendar_end = _month_bounds(y, m)
        ranges.append((start, min(calendar_end, now)))
    return ranges


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=CampusChannelsSummary)
def campus_channels_summary(db: Session = Depends(get_db)) -> CampusChannelsSummary:
    """Per-channel view/post totals across four publish-date windows."""
    now = datetime.now(timezone.utc)

    current_start, current_end = _month_bounds(now.year, now.month)
    prev_year, prev_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    last_start, last_end = _month_bounds(prev_year, prev_month)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rolling_end = today_start + timedelta(days=1)
    rolling_start = rolling_end - timedelta(days=30)
    growth_30_start = now - timedelta(days=30)
    growth_7_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    monthly_ranges = _monthly_ranges(now)

    channels: list[ChannelSummary] = []
    for channel, label in CAMPUS_CHANNELS:
        posts = (
            db.query(NiltvNetworkPost)
            .filter(_channel_match(channel))
            .all()
        )
        rows = [(post.views, post.publish_time) for post in posts]

        post_ids = [post.id for post in posts]
        snapshot_rows = (
            db.query(
                NiltvNetworkPostSnapshot.network_post_id,
                NiltvNetworkPostSnapshot.captured_at,
                NiltvNetworkPostSnapshot.views,
            )
            .filter(
                NiltvNetworkPostSnapshot.network_post_id.in_(post_ids),
                NiltvNetworkPostSnapshot.views.isnot(None),
            )
            .order_by(
                NiltvNetworkPostSnapshot.network_post_id,
                NiltvNetworkPostSnapshot.captured_at,
            )
            .all()
            if post_ids else []
        )
        captures_by_post: dict[int, list[tuple[datetime, int]]] = {}
        for post_id, captured_at, views in snapshot_rows:
            captured = _as_utc(captured_at)
            if captured is not None:
                captures_by_post.setdefault(int(post_id), []).append((captured, int(views)))

        source_rows = (
            db.query(
                func.coalesce(NiltvNetworkPost.views_source, "unknown"),
                func.count(NiltvNetworkPost.id),
            )
            .filter(_channel_match(channel), NiltvNetworkPost.views.isnot(None))
            .group_by(func.coalesce(NiltvNetworkPost.views_source, "unknown"))
            .all()
        )

        latest = (
            db.query(func.max(NiltvNetworkPost.publish_time))
            .filter(_channel_match(channel))
            .scalar()
        )

        channels.append(ChannelSummary(
            channel=channel,
            label=label,
            last_month=_window(rows, last_start, last_end),
            current_month=_window(rows, current_start, current_end),
            last_30_days=_window(rows, rolling_start, rolling_end),
            all_time=_window(rows, None, None),
            views_by_source={str(src): int(count) for src, count in source_rows},
            latest_post_at=latest,
            bd_only=channel in BD_ONLY_CHANNELS,
            monthly_growth=[
                _growth(posts, captures_by_post, start, end, now)
                for start, end in monthly_ranges
            ],
            last_30_days_growth=_growth(posts, captures_by_post, growth_30_start, now, now),
            last_7_days_growth=_growth(posts, captures_by_post, growth_7_start, now, now),
        ))

    return CampusChannelsSummary(
        generated_at=now,
        windows={
            "last_month": WindowRange(start=last_start, end=last_end),
            "current_month": WindowRange(start=current_start, end=current_end),
            "last_30_days": WindowRange(start=rolling_start, end=rolling_end),
        },
        channels=channels,
    )
