"""
Instagram collaborative-media client (Graph API) for the NILTV network.

Pulls every post from an account's `/media` (owned) and `/collaborative_media`
(collab) edges using INLINE edge fields — the only way to read metrics for
collaborator-owned posts (a per-object GET fails with "missing permissions").

Returns normalized dicts ready for backend.jobs.import_niltv_network.upsert_posts.

Metric availability (an IG platform constraint, not a bug):
    views / likes / comments .... owned + collaborative   (inline edge fields)
    shares / saves / reach ...... owned only               (insights edge)
For collaborative posts, shares/saves/reach come back as None and are left for
the CSV upload to backfill.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

IG_API_BASE = "https://graph.facebook.com/v25.0"
PAGE_LIMIT = 25          # owned /media edge is cheap — large pages are fine
COLLAB_PAGE_LIMIT = 3    # collaborative_media is expensive — must page tiny
MIN_PAGE_LIMIT = 1       # shrink to this when a page 500s
PAGE_RETRIES = 5         # per-page attempts (shrinking) before giving up on it
PAGE_BACKOFF = 5.0       # base seconds to back off after a failed page
INTER_PAGE_PAUSE = 1.5   # seconds between pages — be gentle on the edge
INSIGHT_INTERVAL = 1.0   # seconds between owned-post insight calls

# Fields requested inline on the media edges. `username` + `caption` give us the
# original poster (account attribution) and description for collaborator posts.
# media_url/thumbnail_url feed the app ingest bridge (available inline even for
# collaborator-owned posts; short-lived, refreshed every pull).
EDGE_FIELDS = (
    "id,total_views_count,like_count,comments_count,"
    "media_type,media_product_type,timestamp,permalink,caption,username,"
    "media_url,thumbnail_url"
)

# Insight metrics for OWNED posts only (the insights edge requires ownership).
# `views` is the universal consumption metric (v22+) and is the ONLY way to read
# views for image/carousel FEED posts — the inline total_views_count edge field
# only populates for video/Reels. Tiers fall back progressively so older media
# (created before `views` existed) still resolve reach/saves/shares.
INSIGHT_TIERS = [
    "views,reach,saved,shares,total_interactions",
    "views,reach,saved",
    "reach,saved,shares,total_interactions",
    "reach,saved",
]

# Retried inside _get. "(#200) Provide valid app ID" appears sporadically.
TRANSIENT_HINTS = ("rate limit", "calls to", "please wait", "try again", "provide valid app id")

# Server-side 500s on the expensive collaborative_media edge. Recoverable by
# shrinking the page size and retrying the same cursor (see _collect_edge).
# Both "reduce the amount of data" and a bare "unknown error" show up here.
PAGE_ERROR_HINTS = ("reduce the amount of data", "unknown error")

# The collaborative_media edge computes total_views_count server-side and is slow
# even at small pages, so allow a generous read timeout (connect stays short).
REQUEST_TIMEOUT = httpx.Timeout(90.0, connect=10.0)
MAX_ATTEMPTS = 4


def _get(url: str, params: dict, _attempt: int = 1) -> dict:
    try:
        resp = httpx.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        # Network-level timeout/transport error — retry, then surface as RuntimeError.
        if _attempt <= MAX_ATTEMPTS:
            logger.warning(f"request error ({e!r}) — retry {_attempt}/{MAX_ATTEMPTS}")
            time.sleep(3 * _attempt)
            return _get(url, params, _attempt + 1)
        raise RuntimeError(f"request failed after {MAX_ATTEMPTS} retries: {e}")

    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        msg = data.get("error", {}).get("message", resp.text)
        if _attempt <= MAX_ATTEMPTS and any(h in msg.lower() for h in TRANSIENT_HINTS):
            time.sleep(3 * _attempt)
            return _get(url, params, _attempt + 1)
        raise RuntimeError(msg)
    return data


def _collect_edge(user_id: str, edge: str, token: str, start_limit: int = PAGE_LIMIT) -> list[dict]:
    """Page an edge with inline fields.

    The collaborative_media edge computes total_views_count server-side and
    500s on anything but tiny pages, and even those fail intermittently. So for
    each page we retry the *same cursor* with a shrinking page size (down to 1)
    and a backoff before moving on. A page that can't be recovered is logged and
    skipped rather than raised — a partial pull still yields data, and owned
    posts (fetched separately) are never lost to a collab failure.
    """
    items: list[dict] = []
    url = f"{IG_API_BASE}/{user_id}/{edge}"
    after: Optional[str] = None
    while True:
        limit = start_limit
        data = None
        for attempt in range(1, PAGE_RETRIES + 1):
            params: dict = {"fields": EDGE_FIELDS, "limit": limit, "access_token": token}
            if after:
                params["after"] = after
            try:
                data = _get(url, params)
                break
            except RuntimeError as e:
                if not any(h in str(e).lower() for h in PAGE_ERROR_HINTS):
                    raise  # non-recoverable (auth, bad request, …) — let it surface
                new_limit = max(MIN_PAGE_LIMIT, limit - 1)
                logger.warning(
                    f"/{edge} page 500 (limit={limit}, attempt {attempt}/{PAGE_RETRIES}) "
                    f"— shrinking to {new_limit}"
                )
                limit = new_limit
                time.sleep(PAGE_BACKOFF * attempt)
        if data is None:
            logger.error(
                f"/{edge}: gave up on a page after {PAGE_RETRIES} attempts — "
                f"returning {len(items)} collected so far"
            )
            break
        items.extend(data.get("data", []))
        after = data.get("paging", {}).get("cursors", {}).get("after")
        if not data.get("paging", {}).get("next") or not after:
            break
        time.sleep(INTER_PAGE_PAUSE)
    return items


def _fetch_owned_insights(media_id: str, token: str) -> dict:
    """reach/saved/shares for an OWNED post; {} if unavailable."""
    for metrics in INSIGHT_TIERS:
        try:
            data = _get(f"{IG_API_BASE}/{media_id}/insights", {"metric": metrics, "access_token": token})
        except RuntimeError:
            continue
        out: dict = {}
        for item in data.get("data", []):
            values = item.get("values") or []
            # `views`/`total_interactions` come back under `total_value`; reach/saved
            # under `values[].value`. Handle both so views isn't silently dropped.
            value = values[0].get("value") if values else None
            if value is None and isinstance(item.get("total_value"), dict):
                value = item["total_value"].get("value")
            if value is not None:
                out[item["name"]] = value
        return out
    return {}


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_row(item: dict, bucket: str) -> dict:
    return {
        "post_id": item["id"],
        "account_username": item.get("username"),
        "account_name": None,                       # not exposed by the edge
        "description": item.get("caption"),
        "duration_sec": None,
        "publish_time": _parse_ts(item.get("timestamp")),
        "permalink": item.get("permalink"),
        # REELS from media_product_type; otherwise media_type splits the generic
        # FEED label into IMAGE / CAROUSEL_ALBUM / VIDEO (normalised on upsert).
        "post_type": item.get("media_product_type") or item.get("media_type"),
        "_media_type": item.get("media_type"),
        "media_url": item.get("media_url"),
        "thumbnail_url": item.get("thumbnail_url"),
        "views": item.get("total_views_count"),
        "likes": item.get("like_count"),
        "comments": item.get("comments_count"),
        "shares": None,                             # owned-only (filled below)
        "saves": None,
        "reach": None,
        "follows": None,
        "_bucket": bucket,
    }


def fetch_network_posts(user_id: str, token: str, owned_insights: bool = True) -> list[dict]:
    """Fetch normalized owned + collaborative post dicts for one account.

    Dedupes by post_id. For owned posts (and only if `owned_insights`), enriches
    shares/saves/reach from the insights edge.
    """
    rows: dict[str, dict] = {}  # post_id -> row (dedupe)

    # Fetch the two edges independently so a collaborative_media failure never
    # discards the owned posts (the owned edge is cheap and reliable).
    try:
        owned = _collect_edge(user_id, "media", token, start_limit=PAGE_LIMIT)
    except Exception as e:
        logger.error(f"{user_id}: owned /media fetch failed: {e}")
        owned = []
    try:
        collab = _collect_edge(user_id, "collaborative_media", token, start_limit=COLLAB_PAGE_LIMIT)
    except Exception as e:
        logger.error(f"{user_id}: /collaborative_media fetch failed: {e}")
        collab = []
    logger.info(f"{user_id}: {len(owned)} owned + {len(collab)} collaborative posts")

    for item in owned:
        rows.setdefault(item["id"], _to_row(item, "owned"))
    for item in collab:
        rows.setdefault(item["id"], _to_row(item, "collaborative"))

    if owned_insights:
        for row in rows.values():
            if row["_bucket"] != "owned":
                continue
            time.sleep(INSIGHT_INTERVAL)
            ins = _fetch_owned_insights(row["post_id"], token)
            row["shares"] = ins.get("shares")
            row["saves"] = ins.get("saved")
            row["reach"] = ins.get("reach")
            # Inline total_views_count is video/Reels-only; for image/carousel
            # feed posts, views come from the insights `views` metric.
            if row["views"] is None:
                row["views"] = ins.get("views")

    out = list(rows.values())
    for row in out:
        row.pop("_bucket", None)
    return out
