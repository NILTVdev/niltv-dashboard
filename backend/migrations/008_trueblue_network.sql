-- TrueBlue TV network posts (Zoomph campaign data across all affiliated accounts)

CREATE TABLE IF NOT EXISTS trueblue_network_posts (
    id SERIAL PRIMARY KEY,
    post_id TEXT UNIQUE NOT NULL,
    account_username TEXT,
    account_name TEXT,
    description TEXT,
    duration_sec INTEGER,
    publish_time TIMESTAMPTZ,
    permalink TEXT,
    post_type TEXT,
    views INTEGER,
    likes INTEGER,
    shares INTEGER,
    comments INTEGER,
    saves INTEGER,
    reach INTEGER,
    follows INTEGER,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trueblue_network_publish_time ON trueblue_network_posts (publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_trueblue_network_username ON trueblue_network_posts (account_username);
