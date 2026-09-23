"""
Zoomph Partner Mention API client.

Two-step process:
  1. POST to submit a report request → get a ReportId
  2. Wait 30s, then GET the report results by ReportId
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ZOOMPH_BASE = "https://api.zoomph.com"
PARTNERS = ["Duke Owned"]
FIELDS = [
    # Identity / post metadata (documented fields only)
    "Partner", "ServiceType", "Id", "ContentType", "Url",
    "PartnerExposureCreatorName", "PartnerExposureCreator",
    "Message", "PartnerExposureDate", "created",
    "PartnerMentionType",
    # Engagement
    "Engagement", "LikeCount", "CommentCount", "SaveCount",
    "ShareCount", "ReplyCount",
    # Reach / rates
    "Impressions", "Reach", "ProjectedImpressions", "FollowerCount",
    "EngagementRate", "FollowerInteractionRate",
    # Value
    "BrandExposureValue", "PostValue", "BrandExposureValueUS",
    # Sentiment / context
    "Sentiment", "Hashtags", "Mentions", "Language",
    # Video / streaming
    "VODViews", "ViewCount", "LiveViews", "AverageConcurrentViewers",
    "PeakLiveViewerCount", "HoursWatched",
    # Logo AI
    "LogoTotalSeconds", "LogoAverageSize", "LogoAverageClarity",
    "LogoImpressions", "LogoLocation",
]


@dataclass
class ZoomphPost:
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


def _parse_posted_at(value) -> Optional[datetime]:
    if value is None:
        return None

    # Handle numeric Unix timestamps (seconds or milliseconds)
    if isinstance(value, (int, float)):
        ts = value if value < 1e12 else value / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    if not isinstance(value, str) or not value.strip():
        return None

    raw = value.strip()

    # ISO 8601: "2026-02-15T12:00:00Z" or "2026-02-15T12:00:00+00:00"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass

    # .NET JSON date: "/Date(1708012800000)/"
    if raw.startswith("/Date(") and raw.endswith(")/"):
        try:
            ms = int(raw[6:-2].split("+")[0].split("-")[0])
            return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        except (ValueError, OverflowError):
            pass

    # US-style: "2/15/2026 3:45:00 PM" or "02/15/2026 15:45:00"
    for fmt in (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    logger.warning(f"Could not parse posted_at value: {raw!r}")
    return None


def _safe_float(value) -> Optional[float]:
    """Parse a numeric value that may arrive as a string with currency symbols."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _safe_int(value) -> Optional[int]:
    """Parse an integer that may arrive as a string with commas."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        try:
            return int(float(cleaned))
        except ValueError:
            return None
    return None


def _extract_author_from_url(url: Optional[str]) -> Optional[str]:
    """Extract the account handle from a social media post URL."""
    if not url:
        return None
    # Twitter: https://twitter.com/DukeFEN/statuses/123
    m = re.match(r"https?://(?:www\.)?(?:twitter|x)\.com/([^/]+)/", url)
    if m:
        return m.group(1)
    # Facebook: https://www.facebook.com/DukeSOFTBALL/posts/123
    m = re.match(r"https?://(?:www\.)?facebook\.com/([^/]+)/", url)
    if m:
        return m.group(1)
    # Instagram: https://www.instagram.com/dukesoftball/... (profile posts)
    # Note: /p/ and /reel/ URLs don't contain the author handle
    m = re.match(r"https?://(?:www\.)?instagram\.com/([^/]+)/(?!p/|reel/)", url)
    if m:
        return m.group(1)
    return None


# Twitter snowflake epoch: 2010-11-04T01:42:54.657Z
_TWITTER_EPOCH_MS = 1288834974657


def _posted_at_from_snowflake(url: Optional[str]) -> Optional[datetime]:
    """Derive posted_at from a Twitter/X snowflake status ID in the URL."""
    if not url:
        return None
    m = re.search(r"(?:twitter|x)\.com/[^/]+/statuses/(\d+)", url)
    if not m:
        return None
    try:
        snowflake_id = int(m.group(1))
        timestamp_ms = (snowflake_id >> 22) + _TWITTER_EPOCH_MS
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_row(row: dict) -> ZoomphPost:
    url = row.get("Url")

    # Resolve author — fallback chain:
    #   1. PartnerExposureCreatorName (documented)
    #   2. PartnerExposureCreator (documented, may be an ID or handle)
    #   3. AuthorDisplayName (undocumented, not requested but may appear)
    #   4. Parse from URL
    author = (
        row.get("PartnerExposureCreatorName")
        or row.get("PartnerExposureCreator")
        or row.get("AuthorDisplayName")
    )
    if not author:
        author = _extract_author_from_url(url)
        if author:
            logger.debug(f"Derived author={author!r} from URL for Id={row.get('Id')!r}")
        else:
            logger.debug(f"Missing author. Url={url!r}")

    # Resolve posted_at — fallback chain:
    #   1. PartnerExposureDate (documented)
    #   2. Created (undocumented, not requested but may appear)
    #   3. Twitter snowflake decode from URL
    posted_at = (
        _parse_posted_at(row.get("PartnerExposureDate"))
        or _parse_posted_at(row.get("Created"))
    )
    if not posted_at:
        posted_at = _posted_at_from_snowflake(url)
        if posted_at:
            logger.debug(f"Derived posted_at from snowflake for Id={row.get('Id')!r}")
        else:
            logger.debug(f"Missing date. Id={row.get('Id')!r}")

    return ZoomphPost(
        post_id=str(row.get("Id", "")),
        partner=row.get("Partner"),
        platform=row.get("ServiceType"),
        content_type=row.get("ContentType"),
        author=author,
        url=url,
        message=row.get("Message"),
        posted_at=posted_at,
        partner_mention_type=row.get("PartnerMentionType"),
        # Engagement
        engagement=_safe_int(row.get("Engagement")),
        like_count=_safe_int(row.get("LikeCount")),
        comment_count=_safe_int(row.get("CommentCount")),
        save_count=_safe_int(row.get("SaveCount")),
        share_count=_safe_int(row.get("ShareCount")),
        reply_count=_safe_int(row.get("ReplyCount")),
        # Reach / rates
        impressions=_safe_int(row.get("Impressions")),
        reach=_safe_int(row.get("Reach")),
        projected_impressions=_safe_int(row.get("ProjectedImpressions")),
        follower_count=_safe_int(row.get("FollowerCount")),
        engagement_rate=_safe_float(row.get("EngagementRate")),
        follower_interaction_rate=_safe_float(row.get("FollowerInteractionRate")),
        # Value
        brand_exposure_value=_safe_float(row.get("BrandExposureValue")),
        post_value=_safe_float(row.get("PostValue")),
        brand_exposure_value_us=_safe_float(row.get("BrandExposureValueUS")),
        # Sentiment / context
        sentiment=row.get("Sentiment"),
        hashtags=row.get("Hashtags"),
        mentions=row.get("Mentions"),
        language=row.get("Language"),
        # Video / streaming
        vod_views=_safe_int(row.get("VODViews")),
        view_count=_safe_int(row.get("ViewCount")),
        live_views=_safe_int(row.get("LiveViews")),
        avg_concurrent_viewers=_safe_int(row.get("AverageConcurrentViewers")),
        peak_live_viewer_count=_safe_int(row.get("PeakLiveViewerCount")),
        hours_watched=_safe_int(row.get("HoursWatched")),
        # Logo AI
        logo_total_seconds=_safe_float(row.get("LogoTotalSeconds")),
        logo_avg_size=_safe_float(row.get("LogoAverageSize")),
        logo_avg_clarity=_safe_float(row.get("LogoAverageClarity")),
        logo_impressions=_safe_int(row.get("LogoImpressions")),
        logo_location=row.get("LogoLocation"),
    )


def _poll_report(report_id: str, max_wait: int = 120, interval: int = 5) -> list[dict]:
    """Poll Zoomph report endpoint until results are ready or timeout."""
    fetch_params = [("access_token", settings.zoomph_api_key)]
    for f in FIELDS:
        fetch_params.append(("fields", f))

    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval

        resp = httpx.get(
            f"{ZOOMPH_BASE}/partnermention/report/{report_id}",
            params=fetch_params,
            timeout=120.0,
        )
        if resp.status_code == 429:
            wait = min(60, interval * 2 ** (elapsed // interval))
            logger.warning(f"Rate limited polling report {report_id}. Waiting {wait}s...")
            time.sleep(wait)
            elapsed += wait
            continue
        resp.raise_for_status()

        rows = resp.json().get("Report", [])
        if rows:
            logger.info(f"Report {report_id} ready after {elapsed}s ({len(rows)} rows)")
            return rows

        logger.debug(f"Report {report_id} not ready yet ({elapsed}s elapsed)")

    logger.warning(f"Report {report_id} not ready after {max_wait}s — returning empty")
    return []


def _fetch_zoomph_chunk(
    start_dt: datetime,
    end_dt: datetime,
    max_retries: int = 3,
) -> list[ZoomphPost]:
    """Fetch a single date-range chunk from Zoomph with retry on 429."""
    query = (
        f"created>{start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"AND created<{end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    logger.info(f"Submitting Zoomph report: {query}")

    # Step 1: Submit report (with retry on 429)
    for attempt in range(max_retries):
        resp = httpx.post(
            f"{ZOOMPH_BASE}/partnermention/report",
            params={"access_token": settings.zoomph_api_key},
            json={
                "Partners": PARTNERS,
                "FeedId": settings.zoomph_feed_id,
                "Query": query,
            },
            timeout=30.0,
        )
        if resp.status_code == 429:
            wait = 60 * (attempt + 1)  # 60s, 120s, 180s
            logger.warning(f"Rate limited on report submit (attempt {attempt + 1}/{max_retries}). Waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        raise httpx.HTTPStatusError(
            "Rate limited after all retries", request=resp.request, response=resp
        )

    report_id = resp.json()["ReportId"]
    logger.info(f"Report ID: {report_id}. Polling for results...")

    # Step 2: Poll until report is ready (replaces fixed 30s sleep)
    report_rows = _poll_report(report_id)
    if not report_rows:
        logger.info("Zoomph returned 0 posts for this chunk.")
        return []

    posts = []
    for row in report_rows:
        try:
            posts.append(_parse_row(row))
        except Exception as e:
            logger.warning(f"Failed to parse Zoomph row: {e} | {row}")

    logger.info(f"Parsed {len(posts)} Zoomph posts for chunk.")
    return posts


def _month_ranges(start_dt: datetime, end_dt: datetime) -> list[tuple[datetime, datetime]]:
    """Split a date range into monthly chunks."""
    from calendar import monthrange

    ranges = []
    current = start_dt
    while current < end_dt:
        _, days_in_month = monthrange(current.year, current.month)
        month_end = current.replace(
            day=days_in_month, hour=23, minute=59, second=59,
        )
        chunk_end = min(month_end, end_dt)
        ranges.append((current, chunk_end))
        # Move to first day of next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1, hour=0, minute=0, second=0)
        else:
            current = current.replace(month=current.month + 1, day=1, hour=0, minute=0, second=0)
    return ranges


def fetch_zoomph_posts(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[ZoomphPost]:
    """
    Fetch partner mention posts from Zoomph.

    `since` — only fetch posts created after this datetime.
              Defaults to 2025-01-01 on the very first pull.
    `until` — only fetch posts created before this datetime.
              Defaults to now.

    Large date ranges are automatically chunked into monthly windows
    to avoid OOM on the API response / server side.
    """
    start_dt = since or datetime(2025, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
    end_dt = until or datetime.now(tz=timezone.utc)

    # If the range spans more than 35 days, chunk into monthly windows
    if (end_dt - start_dt).days > 35:
        chunks = _month_ranges(start_dt, end_dt)
        logger.info(f"Large date range ({(end_dt - start_dt).days} days) — splitting into {len(chunks)} monthly chunks")
        all_posts: list[ZoomphPost] = []
        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            logger.info(f"Chunk {i}/{len(chunks)}: {chunk_start.date()} → {chunk_end.date()}")
            try:
                chunk_posts = _fetch_zoomph_chunk(chunk_start, chunk_end)
                all_posts.extend(chunk_posts)
                logger.info(f"Running total: {len(all_posts)} posts")
            except Exception as e:
                logger.error(f"Chunk {i} failed: {e}")
                # Continue with remaining chunks
            # Rate-limit courtesy delay between chunks
            if i < len(chunks):
                logger.info("Waiting 30s between chunks to avoid rate limits...")
                time.sleep(30)
        logger.info(f"Total: {len(all_posts)} Zoomph posts across {len(chunks)} chunks.")
        return all_posts

    return _fetch_zoomph_chunk(start_dt, end_dt)
