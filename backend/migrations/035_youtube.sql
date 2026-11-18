-- 035: YouTube channel and video data.
--
-- Stage 1, public data (YouTube Data API v3, API key only), written nightly by
-- backend.jobs.run_youtube:
--   youtube_channels           one row per tracked channel (YOUTUBE_CHANNEL_IDS).
--   youtube_channel_snapshots  subscribers / total views / video count, one row
--                              per channel per UTC day (a re-run the same day
--                              overwrites that day's row).
--   youtube_videos             every upload with its current counts.
--   youtube_video_snapshots    per-video counts, one row per video per UTC day.
--
-- is_short is a duration rule: duration <= 180 seconds. The Data API does not
-- say whether a video is a Short or report its aspect ratio, so a short
-- horizontal upload also counts as a Short.
--
-- Stage 2, YouTube Analytics API v2 (needs the channel owner's one-time OAuth
-- consent, see scripts/youtube_oauth.py), written by
-- backend.jobs.run_youtube_analytics:
--   youtube_daily_analytics    channel metrics per day; the last 30 days are
--                              re-pulled every night and upserted, because
--                              YouTube revises recent days.
--   youtube_video_analytics    per-video totals over a window (28 days) that
--                              ends on period_end.
--
-- No foreign keys on the analytics tables: the OAuth channel can be pulled
-- before the public-data job has seen it, and analytics can name videos the
-- uploads playlist no longer lists.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id          TEXT PRIMARY KEY,
    title               TEXT,
    handle              TEXT,
    uploads_playlist_id TEXT,
    thumbnail_url       TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS youtube_channel_snapshots (
    id          SERIAL PRIMARY KEY,
    channel_id  TEXT NOT NULL REFERENCES youtube_channels(channel_id) ON DELETE CASCADE,
    day         DATE NOT NULL,
    pulled_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    subscribers BIGINT,      -- NULL when the channel hides its subscriber count
    total_views BIGINT,
    video_count INTEGER,
    CONSTRAINT uq_youtube_channel_snapshot_day UNIQUE (channel_id, day)
);

CREATE INDEX IF NOT EXISTS idx_youtube_channel_snap_pulled
    ON youtube_channel_snapshots(pulled_at);

CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id      TEXT PRIMARY KEY,
    channel_id    TEXT NOT NULL REFERENCES youtube_channels(channel_id) ON DELETE CASCADE,
    title         TEXT,
    published_at  TIMESTAMPTZ,
    duration_sec  INTEGER,
    is_short      BOOLEAN,
    thumbnail_url TEXT,
    views         BIGINT,
    likes         BIGINT,    -- NULL when the owner hides likes
    comments      BIGINT,    -- NULL when comments are off
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel_published
    ON youtube_videos(channel_id, published_at);

CREATE TABLE IF NOT EXISTS youtube_video_snapshots (
    id       SERIAL PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES youtube_videos(video_id) ON DELETE CASCADE,
    day      DATE NOT NULL,
    views    BIGINT,
    likes    BIGINT,
    comments BIGINT,
    CONSTRAINT uq_youtube_video_snapshot_day UNIQUE (video_id, day)
);

CREATE TABLE IF NOT EXISTS youtube_daily_analytics (
    id                         SERIAL PRIMARY KEY,
    channel_id                 TEXT NOT NULL,
    day                        DATE NOT NULL,
    views                      BIGINT,
    estimated_minutes_watched  BIGINT,
    average_view_duration_sec  INTEGER,
    average_view_percentage    NUMERIC,
    subscribers_gained         INTEGER,
    subscribers_lost           INTEGER,
    pulled_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_youtube_daily_analytics_day UNIQUE (channel_id, day)
);

CREATE TABLE IF NOT EXISTS youtube_video_analytics (
    id                         SERIAL PRIMARY KEY,
    video_id                   TEXT NOT NULL,
    period_end                 DATE NOT NULL,
    window_days                INTEGER NOT NULL,
    views                      BIGINT,
    estimated_minutes_watched  BIGINT,
    average_view_duration_sec  INTEGER,
    average_view_percentage    NUMERIC,
    pulled_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_youtube_video_analytics_period UNIQUE (video_id, period_end, window_days)
);
