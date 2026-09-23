-- TrueBlue TV Instagram tracking tables

CREATE TABLE IF NOT EXISTS trueblue_snapshots (
    id SERIAL PRIMARY KEY,
    pulled_at TIMESTAMPTZ DEFAULT NOW(),
    followers INTEGER,
    following INTEGER,
    post_count INTEGER,
    bio TEXT
);

CREATE TABLE IF NOT EXISTS trueblue_posts (
    id SERIAL PRIMARY KEY,
    shortcode TEXT UNIQUE NOT NULL,
    posted_at TIMESTAMPTZ,
    media_type TEXT,
    caption TEXT,
    like_count INTEGER,
    comment_count INTEGER,
    permalink TEXT,
    media_url TEXT,
    is_video BOOLEAN DEFAULT FALSE,
    video_view_count INTEGER,
    pulled_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trueblue_posts_posted_at ON trueblue_posts (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_trueblue_snapshots_pulled_at ON trueblue_snapshots (pulled_at DESC);
