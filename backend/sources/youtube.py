"""
YouTube clients over plain HTTP (httpx).

Data API v3 (API key, public data):
    fetch_channels()      channels.list   part=snippet,statistics,contentDetails
    fetch_upload_ids()    playlistItems.list, paged through the uploads playlist
    fetch_videos()        videos.list     part=snippet,statistics,contentDetails,
                                          in batches of 50 ids

Analytics API v2 (OAuth, owner consent):
    refresh_access_token()  refresh token -> short-lived access token
    fetch_my_channel()      channels.list mine=true with that token
    query_report()          reports.query, rows returned as dicts

Quota: every Data API list call above costs 1 unit (10,000 per day by
default), so a channel with N uploads costs about 1 + 2 * ceil(N / 50) units.

Errors never carry the request URL: the API key travels as a query parameter,
and httpx puts the full URL into its own exception messages. YouTubeAPIError
holds the status code and Google's error reason only.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

import httpx

logger = logging.getLogger(__name__)

DATA_API = "https://www.googleapis.com/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Shorts are capped at 3 minutes. The Data API reports neither a Shorts flag
# nor the aspect ratio, so the rule is duration only: <= 180 s is a Short.
SHORT_MAX_SECONDS = 180
VIDEOS_BATCH = 50
MAX_ATTEMPTS = 3
RETRY_BACKOFF = 2.0  # seconds, doubled after each failed attempt
TIMEOUT = 30.0


class YouTubeAPIError(RuntimeError):
    def __init__(self, status: int, reason: str):
        super().__init__(f"YouTube API error {status}: {reason}")
        self.status = status
        self.reason = reason


_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: Optional[str]) -> Optional[int]:
    """ISO 8601 duration as YouTube returns it ("PT1H2M3S", "P1DT2S", "PT45S")
    to whole seconds. Live streams in progress report "P0D". Anything that
    does not parse returns None."""
    if not value:
        return None
    m = _DURATION_RE.match(value.strip())
    if not m or value.strip() in ("P", "PT"):
        return None
    parts = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return int(parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"])


def is_short(duration_sec: Optional[int]) -> Optional[bool]:
    if duration_sec is None:
        return None
    return 0 < duration_sec <= SHORT_MAX_SECONDS


def _int(value) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _best_thumbnail(snippet: dict) -> Optional[str]:
    thumbs = snippet.get("thumbnails") or {}
    for size in ("medium", "high", "default", "standard", "maxres"):
        url = (thumbs.get(size) or {}).get("url")
        if url:
            return url
    return None


def _error_reason(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        return resp.reason_phrase or "unknown error"
    if isinstance(err, dict):
        reasons = [e.get("reason") for e in err.get("errors") or [] if e.get("reason")]
        return ", ".join(reasons) or err.get("message") or "unknown error"
    if isinstance(err, str):  # OAuth token endpoint: {"error": "invalid_grant", ...}
        return err
    return resp.reason_phrase or "unknown error"


class Calls:
    """Counts API calls so a job can log what it spent against the quota."""

    def __init__(self):
        self.count = 0


def request_json(client: httpx.Client, method: str, url: str, calls: Optional[Calls] = None,
                 **kwargs) -> dict:
    """One API call with retries on 5xx, 429 and network errors. 4xx raises at once."""
    delay = RETRY_BACKOFF
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if calls is not None:
            calls.count += 1
        try:
            resp = client.request(method, url, timeout=TIMEOUT, **kwargs)
        except httpx.TransportError as e:
            if attempt == MAX_ATTEMPTS:
                raise YouTubeAPIError(0, f"network error: {type(e).__name__}") from None
            logger.warning(f"YouTube call failed ({type(e).__name__}), retry {attempt}/{MAX_ATTEMPTS - 1}")
        else:
            if resp.status_code < 400:
                return resp.json()
            reason = _error_reason(resp)
            if resp.status_code < 500 and resp.status_code != 429:
                raise YouTubeAPIError(resp.status_code, reason)
            if attempt == MAX_ATTEMPTS:
                raise YouTubeAPIError(resp.status_code, reason)
            logger.warning(f"YouTube returned {resp.status_code} ({reason}), retry {attempt}/{MAX_ATTEMPTS - 1}")
        time.sleep(delay)
        delay *= 2
    raise AssertionError("unreachable")


# ── Data API v3 ──────────────────────────────────────────────────────────────

@dataclass
class ChannelData:
    channel_id: str
    title: Optional[str]
    handle: Optional[str]
    uploads_playlist_id: Optional[str]
    thumbnail_url: Optional[str]
    subscribers: Optional[int]
    total_views: Optional[int]
    video_count: Optional[int]


@dataclass
class VideoData:
    video_id: str
    channel_id: Optional[str]
    title: Optional[str]
    published_at: Optional[datetime]
    duration_sec: Optional[int]
    is_short: Optional[bool]
    thumbnail_url: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]


def _parse_channel(item: dict) -> ChannelData:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    hidden = stats.get("hiddenSubscriberCount") is True
    return ChannelData(
        channel_id=item["id"],
        title=snippet.get("title"),
        handle=snippet.get("customUrl"),
        uploads_playlist_id=uploads,
        thumbnail_url=_best_thumbnail(snippet),
        subscribers=None if hidden else _int(stats.get("subscriberCount")),
        total_views=_int(stats.get("viewCount")),
        video_count=_int(stats.get("videoCount")),
    )


def _parse_video(item: dict) -> VideoData:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    duration = parse_duration((item.get("contentDetails") or {}).get("duration"))
    return VideoData(
        video_id=item["id"],
        channel_id=snippet.get("channelId"),
        title=snippet.get("title"),
        published_at=_parse_time(snippet.get("publishedAt")),
        duration_sec=duration,
        is_short=is_short(duration),
        thumbnail_url=_best_thumbnail(snippet),
        views=_int(stats.get("viewCount")),
        likes=_int(stats.get("likeCount")),
        comments=_int(stats.get("commentCount")),
    )


def fetch_channels(client: httpx.Client, api_key: str, channel_ids: list[str],
                   calls: Optional[Calls] = None) -> list[ChannelData]:
    """channels.list for up to 50 ids. Unknown ids are simply absent."""
    data = request_json(client, "GET", f"{DATA_API}/channels", calls, params={
        "part": "snippet,statistics,contentDetails",
        "id": ",".join(channel_ids[:VIDEOS_BATCH]),
        "maxResults": VIDEOS_BATCH,
        "key": api_key,
    })
    return [_parse_channel(i) for i in data.get("items") or []]


def fetch_upload_ids(client: httpx.Client, api_key: str, playlist_id: str,
                     calls: Optional[Calls] = None) -> list[str]:
    """Every video id in an uploads playlist, newest first. A channel with no
    uploads has no playlist yet (404 playlistNotFound): that is an empty list."""
    ids: list[str] = []
    page_token: Optional[str] = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50, "key": api_key}
        if page_token:
            params["pageToken"] = page_token
        try:
            data = request_json(client, "GET", f"{DATA_API}/playlistItems", calls, params=params)
        except YouTubeAPIError as e:
            if e.status == 404:
                return ids
            raise
        for item in data.get("items") or []:
            vid = (item.get("contentDetails") or {}).get("videoId")
            if vid and vid not in ids:
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids


def _batches(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_videos(client: httpx.Client, api_key: str, video_ids: list[str],
                 calls: Optional[Calls] = None) -> list[VideoData]:
    """videos.list in batches of 50. Private or deleted ids are absent."""
    out: list[VideoData] = []
    for batch in _batches(video_ids, VIDEOS_BATCH):
        data = request_json(client, "GET", f"{DATA_API}/videos", calls, params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "maxResults": VIDEOS_BATCH,
            "key": api_key,
        })
        out.extend(_parse_video(i) for i in data.get("items") or [])
    return out


# ── Analytics API v2 (OAuth) ─────────────────────────────────────────────────

def refresh_access_token(client: httpx.Client, client_id: str, client_secret: str,
                         refresh_token: str) -> str:
    data = request_json(client, "POST", TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    token = data.get("access_token")
    if not token:
        raise YouTubeAPIError(0, "token response had no access_token")
    return token


def fetch_my_channel(client: httpx.Client, access_token: str,
                     calls: Optional[Calls] = None) -> ChannelData:
    """The channel the OAuth grant belongs to."""
    data = request_json(client, "GET", f"{DATA_API}/channels", calls,
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"part": "snippet,statistics,contentDetails", "mine": "true"})
    items = data.get("items") or []
    if not items:
        raise YouTubeAPIError(0, "the authorized Google account has no YouTube channel")
    return _parse_channel(items[0])


def query_report(client: httpx.Client, access_token: str, params: dict,
                 calls: Optional[Calls] = None) -> list[dict]:
    """reports.query; each row becomes a dict keyed by column name."""
    data = request_json(client, "GET", ANALYTICS_API, calls,
                        headers={"Authorization": f"Bearer {access_token}"}, params=params)
    names = [h.get("name") for h in data.get("columnHeaders") or []]
    return [dict(zip(names, row)) for row in data.get("rows") or []]
