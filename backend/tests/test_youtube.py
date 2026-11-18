"""YouTube: duration parsing, the nightly jobs (HTTP mocked, no network),
the /api/youtube routes, the network screen card and role access.

Runs in CI against the seeded Postgres. Channel and video ids are made up.
"""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import accounts
from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs import run_youtube, run_youtube_analytics
from backend.main import app
from backend.models import (
    BrandSnapshot, DashboardUser, YoutubeChannel, YoutubeChannelSnapshot, YoutubeDailyAnalytics,
    YoutubeVideo, YoutubeVideoAnalytics, YoutubeVideoSnapshot,
)
from backend.routers.youtube import prev_month_start
from backend.sources import youtube as yt

client = TestClient(app)
AUTH = {"X-API-Key": "test"}
CH = "UCtestchannel0000000000a"
FAKE_KEY = "fake-youtube-key-for-tests"


def _clean():
    db = SessionLocal()
    try:
        for model in (YoutubeVideoAnalytics, YoutubeDailyAnalytics, YoutubeVideoSnapshot,
                      YoutubeVideo, YoutubeChannelSnapshot, YoutubeChannel):
            db.query(model).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_tables(monkeypatch):
    _clean()
    s = get_settings()
    for field in ("youtube_api_key", "youtube_oauth_client_id",
                  "youtube_oauth_client_secret", "youtube_oauth_refresh_token"):
        monkeypatch.setattr(s, field, "")
    monkeypatch.setattr(s, "youtube_channel_ids", CH)
    monkeypatch.setattr(yt.time, "sleep", lambda *_: None)
    monkeypatch.setattr(run_youtube, "upload_to_s3", lambda *_a, **_k: "skipped")
    monkeypatch.setattr(run_youtube_analytics, "upload_to_s3", lambda *_a, **_k: "skipped")
    yield
    _clean()


# ── Duration parsing ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,seconds", [
    ("PT45S", 45),
    ("PT3M", 180),
    ("PT3M1S", 181),
    ("PT1H2M3S", 3723),
    ("PT10H", 36000),
    ("P1DT2S", 86402),
    ("P0D", 0),            # live stream in progress
    ("PT1.5S", 1),
    ("", None),
    (None, None),
    ("PT", None),
    ("garbage", None),
])
def test_parse_duration(raw, seconds):
    assert yt.parse_duration(raw) == seconds


def test_short_rule_is_duration_only():
    assert yt.is_short(59) is True
    assert yt.is_short(180) is True
    assert yt.is_short(181) is False
    assert yt.is_short(0) is False
    assert yt.is_short(None) is None


def test_empty_channel_ids_mean_the_default(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "youtube_channel_ids", " , ")
    assert s.youtube_channel_id_list() == ["UCUymcAQIWHuhxwogARfes5A"]
    monkeypatch.setattr(s, "youtube_channel_ids", "UCa, UCb")
    assert s.youtube_channel_id_list() == ["UCa", "UCb"]


def test_consent_url_asks_for_offline_read_only_access():
    from urllib.parse import parse_qs, urlparse
    from scripts.youtube_oauth import build_auth_url
    q = parse_qs(urlparse(build_auth_url("cid", "http://127.0.0.1:5555/", "st", "ch")).query)
    assert q["scope"][0].split() == [
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]
    assert (q["access_type"][0], q["prompt"][0]) == ("offline", "consent")
    assert (q["redirect_uri"][0], q["state"][0], q["code_challenge_method"][0]) == (
        "http://127.0.0.1:5555/", "st", "S256")


# ── Mocked YouTube Data API ──────────────────────────────────────────────────

def _video(vid, duration, views, likes=10, comments=2, published="2026-10-01T15:00:00Z"):
    return {
        "id": vid,
        "snippet": {"channelId": CH, "title": f"Sample video {vid}", "publishedAt": published,
                    "thumbnails": {"medium": {"url": f"https://i.ytimg.com/vi/{vid}/mq.jpg"}}},
        "statistics": {"viewCount": str(views), "likeCount": str(likes), "commentCount": str(comments)},
        "contentDetails": {"duration": duration},
    }


class FakeYouTube:
    """Answers channels / playlistItems / videos like the Data API does."""

    def __init__(self, views=1000, subscribers=500, fail_first=0):
        self.views = views
        self.subscribers = subscribers
        self.fail_first = fail_first
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_first:
            self.fail_first -= 1
            return httpx.Response(503, json={"error": {"errors": [{"reason": "backendError"}]}})
        path = request.url.path
        params = request.url.params
        assert params.get("key") == FAKE_KEY
        if path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{
                "id": CH,
                "snippet": {"title": "Sample Channel", "customUrl": "@samplechannel", "thumbnails": {}},
                "statistics": {"subscriberCount": str(self.subscribers), "viewCount": "90000", "videoCount": "3"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUtestchannel0000000000a"}},
            }]})
        if path.endswith("/playlistItems"):
            if params.get("pageToken") == "p2":
                return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "vidC"}}]})
            return httpx.Response(200, json={"nextPageToken": "p2", "items": [
                {"contentDetails": {"videoId": "vidA"}}, {"contentDetails": {"videoId": "vidB"}}]})
        if path.endswith("/videos"):
            ids = params.get("id").split(",")
            catalog = {
                "vidA": _video("vidA", "PT45S", self.views),
                "vidB": _video("vidB", "PT12M30S", self.views * 2),
                "vidC": _video("vidC", "PT3M", 50),
            }
            return httpx.Response(200, json={"items": [catalog[i] for i in ids if i in catalog]})
        return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _configure_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "youtube_api_key", FAKE_KEY)


def test_job_without_key_logs_and_writes_nothing(caplog):
    fake = FakeYouTube()
    db = SessionLocal()
    try:
        with caplog.at_level("INFO"):
            assert run_youtube.pull_youtube(db, client=_http(fake)) == 0
    finally:
        db.close()
    assert fake.requests == []
    assert "not configured" in caplog.text


def test_job_upserts_one_snapshot_per_day(monkeypatch):
    _configure_key(monkeypatch)
    day1 = datetime(2026, 11, 2, 5, 25, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        fake = FakeYouTube(views=1000, subscribers=500)
        assert run_youtube.pull_youtube(db, client=_http(fake), now=day1) == 4  # channel + 3 videos
        # channels 1 + playlist pages 2 + one videos batch = 4 quota units
        assert len(fake.requests) == 4

        # Same day again with new counts: rows are updated, not duplicated.
        run_youtube.pull_youtube(db, client=_http(FakeYouTube(views=1500, subscribers=510)),
                                 now=day1 + timedelta(hours=3))
        db.expire_all()
        snaps = db.query(YoutubeChannelSnapshot).all()
        assert [(s.day, s.subscribers) for s in snaps] == [(date(2026, 11, 2), 510)]
        assert db.query(YoutubeVideoSnapshot).count() == 3
        a = db.get(YoutubeVideo, "vidA")
        assert (a.views, a.duration_sec, a.is_short) == (1500, 45, True)
        assert db.get(YoutubeVideo, "vidB").is_short is False
        assert db.get(YoutubeVideo, "vidC").is_short is True        # exactly 180 s
        ch = db.get(YoutubeChannel, CH)
        assert (ch.handle, ch.uploads_playlist_id) == ("@samplechannel", "UUtestchannel0000000000a")

        # Next day: a second row per channel and per video.
        run_youtube.pull_youtube(db, client=_http(FakeYouTube(views=2000, subscribers=520)),
                                 now=day1 + timedelta(days=1))
        assert db.query(YoutubeChannelSnapshot).count() == 2
        assert db.query(YoutubeVideoSnapshot).count() == 6
    finally:
        db.close()


def test_job_retries_server_errors(monkeypatch):
    _configure_key(monkeypatch)
    fake = FakeYouTube(fail_first=2)
    db = SessionLocal()
    try:
        assert run_youtube.pull_youtube(db, client=_http(fake)) == 4
    finally:
        db.close()
    assert len(fake.requests) == 6  # two 503s, then the four real calls


def test_client_errors_do_not_leak_the_key():
    def forbidden(request):
        return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
    with pytest.raises(yt.YouTubeAPIError) as e:
        yt.fetch_channels(_http(forbidden), FAKE_KEY, [CH])
    assert e.value.status == 403
    assert "quotaExceeded" in str(e.value)
    assert FAKE_KEY not in str(e.value)


# ── /api/youtube/summary ─────────────────────────────────────────────────────

def _seed_snapshots(rows: list[tuple[date, int, int]]):
    db = SessionLocal()
    try:
        db.add(YoutubeChannel(channel_id=CH, title="Sample Channel", handle="@samplechannel"))
        db.flush()
        for day, subs, views in rows:
            db.add(YoutubeChannelSnapshot(
                channel_id=CH, day=day, subscribers=subs, total_views=views, video_count=3,
                pulled_at=datetime(day.year, day.month, day.day, 5, 25, tzinfo=timezone.utc)))
        db.commit()
    finally:
        db.close()


def _summary_channel() -> dict:
    r = client.get("/api/youtube/summary", headers=AUTH)
    assert r.status_code == 200
    channels = r.json()["channels"]
    assert len(channels) == 1
    return channels[0]


def test_summary_empty_before_first_pull():
    r = client.get("/api/youtube/summary", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"channels": [], "last_pulled": None}


def test_summary_rolling_changes():
    today = datetime.now(timezone.utc).date()
    _seed_snapshots([
        (today - timedelta(days=30), 400, 50_000),   # 28-day baseline, 2 days early (grace)
        (today - timedelta(days=7), 480, 80_000),
        (today, 500, 90_000),
    ])
    ch = _summary_channel()
    assert (ch["subscribers"], ch["total_views"]) == (500, 90_000)
    assert ch["changes"]["subscribers_7d"] == 20
    assert ch["changes"]["views_7d"] == 10_000
    assert ch["changes"]["subscribers_28d"] == 100
    assert len(ch["series"]) == 3


def test_summary_change_needs_a_snapshot_at_both_ends():
    today = datetime.now(timezone.utc).date()
    # Only one snapshot older than the 7-day mark, and far outside the grace.
    _seed_snapshots([(today - timedelta(days=40), 300, 10_000), (today, 500, 90_000)])
    changes = _summary_channel()["changes"]
    assert changes["subscribers_7d"] is None
    assert changes["subscribers_28d"] is None


def test_month_change_needs_snapshots_from_both_months():
    today = datetime.now(timezone.utc).date()
    prior = prev_month_start(today)
    # The month before last and today, nothing in the prior month: the current
    # month's change is unknown (null), not 0 and not a two-month change.
    _seed_snapshots([(prior - timedelta(days=1), 300, 10_000), (today, 500, 90_000)])
    changes = _summary_channel()["changes"]
    assert changes["subscribers_month"] is None
    assert changes["views_month"] is None
    assert changes["subscribers_prior_month"] is None


def test_month_change_with_both_months():
    today = datetime.now(timezone.utc).date()
    month_start = today.replace(day=1)
    _seed_snapshots([(month_start - timedelta(days=1), 450, 70_000), (today, 500, 90_000)])
    changes = _summary_channel()["changes"]
    assert changes["subscribers_month"] == 50
    assert changes["views_month"] == 20_000


# ── /api/youtube/videos ──────────────────────────────────────────────────────

def _seed_videos():
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add(YoutubeChannel(channel_id=CH, title="Sample Channel"))
        db.flush()
        db.add_all([
            YoutubeVideo(video_id="old_long", channel_id=CH, title="Season recap", is_short=False,
                         duration_sec=900, views=10_000, published_at=now - timedelta(days=100)),
            YoutubeVideo(video_id="new_short", channel_id=CH, title="Game day 100% hype", is_short=True,
                         duration_sec=30, views=2_000, published_at=now - timedelta(days=2)),
            YoutubeVideo(video_id="mid_short", channel_id=CH, title="Practice clip", is_short=True,
                         duration_sec=50, views=3_000, published_at=now - timedelta(days=30)),
        ])
        db.commit()
    finally:
        db.close()


def _ids(**params) -> list[str]:
    r = client.get("/api/youtube/videos", headers=AUTH, params=params)
    assert r.status_code == 200, r.text
    return [v["video_id"] for v in r.json()["items"]]


def test_videos_sort_filter_search_and_paging():
    _seed_videos()
    assert _ids() == ["old_long", "mid_short", "new_short"]
    assert _ids(sort="views_per_day") == ["new_short", "old_long", "mid_short"]
    assert _ids(sort="published") == ["new_short", "mid_short", "old_long"]
    assert _ids(format="shorts") == ["mid_short", "new_short"]
    assert _ids(format="long") == ["old_long"]
    assert _ids(q="100%") == ["new_short"]          # % is literal, not a wildcard
    assert _ids(q="clip") == ["mid_short"]
    page = client.get("/api/youtube/videos", headers=AUTH, params={"page": 2, "page_size": 2}).json()
    assert page["total"] == 3 and [v["video_id"] for v in page["items"]] == ["new_short"]
    first = client.get("/api/youtube/videos", headers=AUTH).json()["items"][0]
    assert first["url"] == "https://www.youtube.com/watch?v=old_long"
    assert first["views_per_day"] == pytest.approx(100, abs=1)


# ── /api/youtube/status and analytics ────────────────────────────────────────

def test_status_reports_configuration(monkeypatch):
    body = client.get("/api/youtube/status", headers=AUTH).json()
    assert body["configured"] is False and body["analytics_connected"] is False
    assert body["channel_ids"] == [CH] and body["last_pull"] is None
    _configure_key(monkeypatch)
    assert client.get("/api/youtube/status", headers=AUTH).json()["configured"] is True


def test_analytics_not_configured(caplog):
    r = client.get("/api/youtube/analytics", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["connected"] is False
    calls = []
    db = SessionLocal()
    try:
        with caplog.at_level("INFO"):
            assert run_youtube_analytics.pull_youtube_analytics(
                db, client=_http(lambda req: calls.append(req) or httpx.Response(500))) == 0
    finally:
        db.close()
    assert calls == []
    assert "not connected" in caplog.text


def _configure_oauth(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "youtube_oauth_client_id", "fake-client-id")
    monkeypatch.setattr(s, "youtube_oauth_client_secret", "fake-client-secret")
    monkeypatch.setattr(s, "youtube_oauth_refresh_token", "fake-refresh-token")


def _fake_analytics(request: httpx.Request) -> httpx.Response:
    if request.url.host == "oauth2.googleapis.com":
        assert b"refresh_token=fake-refresh-token" in request.content
        return httpx.Response(200, json={"access_token": "fake-access", "expires_in": 3599})
    assert request.headers["Authorization"] == "Bearer fake-access"
    if request.url.path.endswith("/channels"):
        return httpx.Response(200, json={"items": [{"id": CH, "snippet": {"title": "Sample Channel"}}]})
    params = request.url.params
    assert params["ids"] == "channel==MINE"
    if params["dimensions"] == "day":
        return httpx.Response(200, json={
            "columnHeaders": [{"name": n} for n in (
                "day", "views", "estimatedMinutesWatched", "averageViewDuration",
                "averageViewPercentage", "subscribersGained", "subscribersLost")],
            "rows": [["2026-11-01", 100, 600, 30, 40.0, 5, 1],
                     ["2026-11-02", 300, 1200, 50, 60.0, 7, 2]],
        })
    assert params["sort"] == "-views" and params["maxResults"] == "200"
    return httpx.Response(200, json={
        "columnHeaders": [{"name": n} for n in (
            "video", "views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage")],
        "rows": [["vidA", 250, 600, 40, 70.5], ["vidB", 150, 1800, 200, 35.0]],
    })


def test_analytics_job_and_route(monkeypatch):
    _configure_oauth(monkeypatch)
    now = datetime(2026, 11, 3, 5, 40, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        assert run_youtube_analytics.pull_youtube_analytics(db, client=_http(_fake_analytics), now=now) == 4
        # Re-pull overlaps: same days upsert in place.
        run_youtube_analytics.pull_youtube_analytics(db, client=_http(_fake_analytics), now=now)
        assert db.query(YoutubeDailyAnalytics).count() == 2
        assert db.query(YoutubeVideoAnalytics).count() == 2
        assert db.get(YoutubeChannel, CH).title == "Sample Channel"
    finally:
        db.close()

    body = client.get("/api/youtube/analytics", headers=AUTH).json()
    assert body["connected"] is True
    assert [d["watch_hours"] for d in body["daily"]] == [10.0, 20.0]
    t = body["totals_28d"]
    assert (t["views"], t["watch_hours"], t["subscribers_net"]) == (400, 30.0, 9)
    assert t["average_view_duration_sec"] == 45              # (30*100 + 50*300) / 400
    assert t["average_view_percentage"] == 55.0
    assert body["top_videos_period_end"] == "2026-11-02"
    assert [v["video_id"] for v in body["top_videos"]] == ["vidB", "vidA"]   # by watch time
    assert body["top_videos"][0]["watch_hours"] == 30.0


# ── Network screen ───────────────────────────────────────────────────────────

def _platform(summary: dict, name: str) -> dict:
    return next(p for p in summary["platforms"] if p["platform"] == name)


def test_network_screen_youtube_card():
    db = SessionLocal()
    try:
        db.query(BrandSnapshot).delete()
        db.add(BrandSnapshot(account="niltv", username="niltv", followers=1000,
                             pulled_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
        db.commit()
    finally:
        db.close()
    try:
        body = client.get("/api/network-screen/summary?mode=month", headers=AUTH).json()
        assert _platform(body, "youtube")["available"] is False
        assert body["aggregate"]["platforms_live"] == 1
        assert body["aggregate"]["total_followers"] == 1000

        today = datetime.now(timezone.utc).date()
        _seed_snapshots([(today, 500, 90_000)])
        body = client.get("/api/network-screen/summary?mode=month", headers=AUTH).json()
        yt_card = _platform(body, "youtube")
        assert yt_card["available"] is True
        cur = yt_card["current_month"]
        assert cur["followers"] == 500
        # No snapshot in the prior month: unknown, not a fake 0.
        assert cur["new_followers_monthly"] is None
        assert cur["collabs_published_monthly"] is None
        assert cur["collab_data_warning"] is False
        assert body["aggregate"]["platforms_live"] == 2
        assert body["aggregate"]["total_followers"] == 1500
    finally:
        db = SessionLocal()
        try:
            db.query(BrandSnapshot).delete()
            db.commit()
        finally:
            db.close()


# ── Access ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["general", "demo"])
@pytest.mark.parametrize("path", ["/api/youtube/summary", "/api/youtube/videos",
                                  "/api/youtube/status", "/api/youtube/analytics"])
def test_role_policy_reads_but_never_writes(role, path):
    assert accounts.allowed(role, "GET", path) is True
    assert accounts.allowed(role, "POST", path) is False


@pytest.fixture()
def users():
    db = SessionLocal()
    db.query(DashboardUser).delete()
    made = []
    for role in ("general", "demo"):
        u = DashboardUser(email=f"{role}-yt@example.com", name=role, role=role,
                          password_hash=accounts.hash_password("correct horse battery"), active=True)
        db.add(u)
        made.append(u)
    db.commit()
    yield [(u.id, u.session_version or 1) for u in made]
    db.query(DashboardUser).delete()
    db.commit()
    db.close()


def test_general_and_demo_accounts_can_read_youtube(users):
    for uid, version in users:
        headers = {**AUTH, "X-Dashboard-User": str(uid), "X-Dashboard-Session-Version": str(version)}
        for path in ("/api/youtube/summary", "/api/youtube/videos",
                     "/api/youtube/status", "/api/youtube/analytics"):
            assert client.get(path, headers=headers).status_code == 200, path
        assert client.post("/api/youtube/summary", headers=headers).status_code in (403, 405)
