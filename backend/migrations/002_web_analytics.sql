-- Web Analytics tables: GA4, Google Search Console

CREATE TABLE ga4_daily_snapshots (
    id              SERIAL PRIMARY KEY,
    date            TIMESTAMPTZ NOT NULL,
    pulled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sessions        INTEGER,
    total_users     INTEGER,
    pageviews       INTEGER,
    bounce_rate     NUMERIC,
    engagement_rate NUMERIC,
    source          TEXT,
    medium          TEXT
);

CREATE TABLE gsc_daily_snapshots (
    id              SERIAL PRIMARY KEY,
    date            TIMESTAMPTZ NOT NULL,
    pulled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query           TEXT,
    page            TEXT,
    clicks          INTEGER,
    impressions     INTEGER,
    ctr             NUMERIC,
    position        NUMERIC
);

CREATE INDEX idx_ga4_date ON ga4_daily_snapshots (date DESC);
CREATE INDEX idx_gsc_date ON gsc_daily_snapshots (date DESC);
