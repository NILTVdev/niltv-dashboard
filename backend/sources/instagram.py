"""
Instagram Business Discovery API client.

Uses the Facebook Graph API v24.0 Business Discovery endpoint to pull
follower counts and recent posts for each athlete's IG account.

Simple sequential fetcher: 1 request every 30 seconds (~2 athletes/min).
No concurrency — just a single worker with a sleep between requests.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

IG_API_BASE = "https://graph.facebook.com/v24.0"

# ~2 requests per minute = 120/hour, well under the 200/hour limit.
REQUEST_INTERVAL = (28.0, 32.0)  # seconds between requests


@dataclass
class IGPost:
    ig_post_id: str
    posted_at: Optional[datetime]
    media_type: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    permalink: Optional[str]
    caption: Optional[str]
    media_url: Optional[str]


@dataclass
class IGProfile:
    username: str
    ig_user_id: Optional[str]
    followers: Optional[int]
    post_count: Optional[int]
    bio: Optional[str]
    posts: list[IGPost] = field(default_factory=list)
    error: Optional[str] = None
    is_accessible: bool = True  # False if personal account / not discoverable
    name: Optional[str] = None                 # display name on the profile
    profile_picture_url: Optional[str] = None  # IG CDN URL — expires, refresh nightly
    website: Optional[str] = None


def _build_fields_query(target_username: str, include_media: bool = True) -> str:
    # include_media=False requests profile fields only — used for ambassador
    # enrichment, where we deliberately never copy the account's post history.
    media_part = (
        "media.limit(25){id,timestamp,like_count,comments_count,"
        "media_type,permalink,caption,media_url,thumbnail_url}"
        if include_media else ""
    )
    return (
        f"business_discovery.username({target_username}){{"
        "username,id,name,biography,followers_count,media_count,"
        "profile_picture_url,website"
        f"{',' + media_part if media_part else ''}"
        "}"
    )


def _parse_post(p: dict) -> IGPost:
    posted_at = None
    if p.get("timestamp"):
        try:
            posted_at = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            pass
    return IGPost(
        ig_post_id=p["id"],
        posted_at=posted_at,
        media_type=p.get("media_type"),
        like_count=p.get("like_count"),
        comment_count=p.get("comments_count"),
        permalink=p.get("permalink"),
        caption=p.get("caption"),
        media_url=p.get("media_url") or p.get("thumbnail_url"),
    )


# Error messages that indicate a personal (non-Business/Creator) account.
_INACCESSIBLE_ERRORS = (
    "Invalid user id",
    "not exist",
    "Cannot query a User with username",
)


def _parse_response(clean_handle: str, resp: httpx.Response) -> IGProfile:
    """Parse an HTTP response into an IGProfile."""
    data = resp.json()

    if resp.status_code >= 400:
        error_msg = data.get("error", {}).get("message", resp.text)
        # Detect personal accounts that can't be accessed via Business Discovery
        is_accessible = not any(hint in error_msg for hint in _INACCESSIBLE_ERRORS)
        return IGProfile(
            username=clean_handle, ig_user_id=None, followers=None,
            post_count=None, bio=None, error=error_msg,
            is_accessible=is_accessible,
        )

    bd = data.get("business_discovery")
    if not bd:
        return IGProfile(
            username=clean_handle, ig_user_id=None, followers=None,
            post_count=None, bio=None,
            error=f"No business_discovery in response: {data}",
        )

    posts = []
    for p in bd.get("media", {}).get("data", []):
        try:
            posts.append(_parse_post(p))
        except Exception as e:
            logger.warning(f"Failed to parse post {p.get('id')}: {e}")

    return IGProfile(
        username=bd.get("username", clean_handle),
        ig_user_id=bd.get("id"),
        followers=bd.get("followers_count"),
        post_count=bd.get("media_count"),
        bio=bd.get("biography"),
        posts=posts,
        name=bd.get("name"),
        profile_picture_url=bd.get("profile_picture_url"),
        website=bd.get("website"),
    )


def fetch_ig_profile(
    target_username: str,
    max_retries: int = 3,
    include_media: bool = True,
) -> IGProfile:
    """Fetch a single IG profile via Business Discovery API.

    Sleeps ~30s between calls to stay under rate limits.
    include_media=False fetches profile fields only (ambassador enrichment).
    """
    clean_handle = target_username.lstrip("@").strip()
    if not clean_handle:
        return IGProfile(
            username="", ig_user_id=None, followers=None,
            post_count=None, bio=None, error="missing_handle",
        )

    params = {
        "fields": _build_fields_query(clean_handle, include_media=include_media),
        "access_token": settings.ig_access_token,
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = httpx.get(
                f"{IG_API_BASE}/{settings.ig_business_id}",
                params=params,
                timeout=30.0,
            )
            data = resp.json()

            # Rate limit — back off and retry
            is_rate_limited = (
                resp.status_code in (429, 403)
                or "Application request limit reached" in str(data.get("error", {}))
            )
            if is_rate_limited:
                wait = 300 * (attempt + 1)  # 5min, 10min, 15min
                logger.warning(f"Rate limit hit for @{clean_handle}, waiting {wait}s...")
                time.sleep(wait)
                continue

            return _parse_response(clean_handle, resp)

        except Exception as e:
            last_error = str(e)
            logger.warning(f"Attempt {attempt + 1} failed for @{clean_handle}: {e}")
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))

    return IGProfile(
        username=clean_handle, ig_user_id=None, followers=None,
        post_count=None, bio=None, error=last_error,
    )


def exchange_token(url: str, params: dict) -> dict:
    """GET a Graph token endpoint and return its JSON.

    The request carries the app secret and a live token in the query string,
    so failures are reported without the request: httpx's own exceptions embed
    the full URL in their message, which would otherwise end up in job logs.
    """
    try:
        resp = httpx.get(url, params=params, timeout=30.0)
    except httpx.HTTPError as e:
        raise RuntimeError(f"token exchange request failed: {type(e).__name__}") from None
    if resp.status_code >= 400:
        raise RuntimeError(f"token exchange failed: HTTP {resp.status_code}: {resp.text[:300]}") from None
    return resp.json()


def refresh_long_lived_token() -> dict:
    """Exchange the current token for a fresh 60-day long-lived token."""
    return exchange_token(
        "https://graph.facebook.com/v24.0/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": settings.ig_app_id,
            "client_secret": settings.ig_app_secret,
            "fb_exchange_token": settings.ig_access_token,
        },
    )
