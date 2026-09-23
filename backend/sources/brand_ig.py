"""
Instagram Graph API client for owned brand accounts (@niltv, @nilstar, ...).

Uses direct Graph API access (not Business Discovery) to pull profile data,
posts, and per-post insights (views, reach, saves, shares).
Each account has its own access token and numeric IG user id — pass both to
fetch_brand_profile(). Defaults to the original @niltv credentials
(BRAND_IG_ACCESS_TOKEN / BRAND_IG_USER_ID) for backward compatibility.
Account registry lives in Settings.brand_ig_targets().
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from backend.config import get_settings
from backend.sources.instagram import exchange_token

logger = logging.getLogger(__name__)

IG_API_BASE = "https://graph.facebook.com/v24.0"

# "Instagram API with Instagram Login" — no Facebook Page required. Tokens
# are host-locked: IG-login tokens only work here, FB-login tokens only on
# graph.facebook.com. Media/insights call shapes are identical on both.
IG_LOGIN_API_BASE = "https://graph.instagram.com/v24.0"


def _api_base(api: str) -> str:
    return IG_LOGIN_API_BASE if api == "ig" else IG_API_BASE

# Small delay between per-post insight calls to stay well under rate limits.
INSIGHT_INTERVAL = 1.5  # seconds


@dataclass
class BrandPost:
    ig_post_id: str
    posted_at: Optional[datetime]
    media_type: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    permalink: Optional[str]
    caption: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str] = None
    impressions: Optional[int] = None
    reach: Optional[int] = None
    saves: Optional[int] = None
    views: Optional[int] = None
    shares: Optional[int] = None


@dataclass
class BrandProfile:
    username: str
    followers: Optional[int]
    post_count: Optional[int]
    bio: Optional[str]
    posts: list[BrandPost] = field(default_factory=list)
    error: Optional[str] = None


def _parse_post(p: dict) -> BrandPost:
    posted_at = None
    if p.get("timestamp"):
        try:
            posted_at = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            pass
    return BrandPost(
        ig_post_id=p["id"],
        posted_at=posted_at,
        media_type=p.get("media_type"),
        like_count=p.get("like_count"),
        comment_count=p.get("comments_count"),
        permalink=p.get("permalink"),
        caption=p.get("caption"),
        media_url=p.get("media_url") or p.get("thumbnail_url"),
        thumbnail_url=p.get("thumbnail_url"),
    )


def _parse_insights_response(data: dict) -> dict:
    result = {}
    for item in data.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        # Newer metrics (views, total_interactions) return under `total_value`;
        # older ones (reach, saved) under `values[].value`. Handle both.
        val = values[0].get("value") if values else None
        if val is None and isinstance(item.get("total_value"), dict):
            val = item["total_value"].get("value")
        if val is None:
            val = item.get("value")
        if name and val is not None:
            result[name] = val
    return result


def _fetch_post_insights(
    post_id: str, token: str, media_type: str | None = None, api: str = "fb"
) -> dict:
    """Fetch insights for a single post.

    `views` is Instagram's universal consumption metric (v22+), available for
    FEED (image/carousel), VIDEO, and Reels — so we request it for every post.
    `impressions` was deprecated for media created on/after 2024-07-02, so we no
    longer request it; `total_interactions` (engagement volume) is still captured
    into the legacy `impressions` column as a backward-compatible proxy. Tiers
    fall back progressively in case a metric is invalid for a given media type.
    """
    def _call(metrics: str) -> dict | None:
        try:
            resp = httpx.get(
                f"{_api_base(api)}/{post_id}/insights",
                params={"metric": metrics, "access_token": token},
                timeout=15.0,
            )
            data = resp.json()
            if resp.status_code >= 400 or "error" in data:
                return None
            return _parse_insights_response(data)
        except Exception:
            return None

    for metrics in (
        "views,reach,saved,shares,total_interactions",
        "views,reach,saved,shares",
        "views,reach,saved,total_interactions",
        "views,reach,saved",
        "reach,saved",
    ):
        result = _call(metrics)
        if result is not None:
            # Keep the legacy impressions column populated with engagement volume.
            if "total_interactions" in result:
                result["impressions"] = result.pop("total_interactions")
            return result

    logger.debug(f"Insights unavailable for {post_id}")
    return {}


def fetch_brand_profile(
    ig_user_id: Optional[str] = None,
    access_token: Optional[str] = None,
    limit: int = 25,
    api: str = "fb",
) -> BrandProfile:
    """Fetch profile + recent posts + per-post insights for an owned brand
    account. Defaults to the @niltv credentials when none are given."""
    settings = get_settings()
    token = access_token or settings.brand_ig_access_token
    user_id = ig_user_id or settings.brand_ig_user_id
    base = _api_base(api)

    # 1. Profile (Instagram Login's /me does not expose `biography`)
    profile_fields = (
        "username,followers_count,media_count" if api == "ig"
        else "username,followers_count,media_count,biography"
    )
    try:
        resp = httpx.get(
            f"{base}/{user_id}",
            params={
                "fields": profile_fields,
                "access_token": token,
            },
            timeout=30.0,
        )
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            return BrandProfile(
                username="",
                followers=None,
                post_count=None,
                bio=None,
                error=data.get("error", {}).get("message", resp.text),
            )
        profile = BrandProfile(
            username=data.get("username", ""),
            followers=data.get("followers_count"),
            post_count=data.get("media_count"),
            bio=data.get("biography"),
        )
    except Exception as e:
        return BrandProfile(username="", followers=None, post_count=None, bio=None, error=str(e))

    # 2. Recent posts
    try:
        resp = httpx.get(
            f"{base}/{user_id}/media",
            params={
                "fields": (
                    "id,timestamp,media_type,like_count,comments_count,"
                    "permalink,caption,media_url,thumbnail_url"
                ),
                "limit": limit,
                "access_token": token,
            },
            timeout=30.0,
        )
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            logger.warning(f"Media fetch failed: {data.get('error', {}).get('message', '')}")
            return profile
        posts_raw = data.get("data", [])
    except Exception as e:
        logger.warning(f"Media fetch exception: {e}")
        return profile

    # 3. Parse posts and fetch per-post insights
    for p in posts_raw:
        try:
            post = _parse_post(p)
            time.sleep(INSIGHT_INTERVAL)
            insights = _fetch_post_insights(p["id"], token, media_type=p.get("media_type"), api=api)
            post.impressions = insights.get("impressions")
            post.reach = insights.get("reach")
            post.saves = insights.get("saved")
            post.views = insights.get("views")
            post.shares = insights.get("shares")
            profile.posts.append(post)
        except Exception as e:
            logger.warning(f"Failed to parse post {p.get('id')}: {e}")

    return profile


def fetch_all_brand_posts(
    ig_user_id: Optional[str] = None,
    access_token: Optional[str] = None,
    page_limit: int = 50,
    max_pages: int = 40,
    api: str = "fb",
) -> list[BrandPost]:
    """Page through an owned account's ENTIRE /media edge, fetching per-post
    insights for every post. Used by the one-off backfill job — the nightly
    job only refreshes recent posts. max_pages is a runaway guard (~2000
    posts at the default page size)."""
    settings = get_settings()
    token = access_token or settings.brand_ig_access_token
    user_id = ig_user_id or settings.brand_ig_user_id

    posts: list[BrandPost] = []
    url: Optional[str] = f"{_api_base(api)}/{user_id}/media"
    params: Optional[dict] = {
        "fields": (
            "id,timestamp,media_type,like_count,comments_count,"
            "permalink,caption,media_url,thumbnail_url"
        ),
        "limit": page_limit,
        "access_token": token,
    }

    for page in range(max_pages):
        try:
            resp = httpx.get(url, params=params, timeout=30.0)
            data = resp.json()
        except Exception as e:
            logger.warning(f"Media page {page} fetch exception: {e}")
            break
        if resp.status_code >= 400 or "error" in data:
            logger.warning(f"Media page {page} failed: {data.get('error', {}).get('message', '')}")
            break

        for p in data.get("data", []):
            try:
                post = _parse_post(p)
                time.sleep(INSIGHT_INTERVAL)
                insights = _fetch_post_insights(p["id"], token, media_type=p.get("media_type"), api=api)
                post.impressions = insights.get("impressions")
                post.reach = insights.get("reach")
                post.saves = insights.get("saved")
                post.views = insights.get("views")
                post.shares = insights.get("shares")
                posts.append(post)
            except Exception as e:
                logger.warning(f"Failed to parse post {p.get('id')}: {e}")

        # The `next` link embeds all query params (including the token).
        url = data.get("paging", {}).get("next")
        params = None
        if not url:
            break
        logger.info(f"Fetched page {page + 1} ({len(posts)} posts so far)...")

    return posts


def refresh_brand_token(token: Optional[str] = None) -> dict:
    """Refresh a brand token for a fresh 60-day long-lived token.

    Facebook Login tokens ("EAA...") are exchanged via graph.facebook.com
    with the app id/secret; Instagram Login tokens ("IG...") use their own
    refresh endpoint on graph.instagram.com (no secret needed, but the token
    must be at least 24h old and still valid). Defaults to the @niltv token.
    """
    settings = get_settings()
    tok = token or settings.brand_ig_access_token

    if tok.startswith("IG"):
        return exchange_token(
            f"{IG_LOGIN_API_BASE}/refresh_access_token",
            {"grant_type": "ig_refresh_token", "access_token": tok},
        )
    return exchange_token(
        f"{IG_API_BASE}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": settings.brand_ig_app_id,
            "client_secret": settings.brand_ig_app_secret,
            "fb_exchange_token": tok,
        },
    )
