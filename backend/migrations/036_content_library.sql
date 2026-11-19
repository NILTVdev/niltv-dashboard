-- 036: Content library, fed by the NIL TV app's hourly ingest.
--
-- library_items: one row per app content id, as the app labelled it (sport,
-- school, content types, categories, sponsor, athletes, keywords, summary, QC
-- state). The app POSTs a full snapshot to /api/library/sync; rows from the
-- same stage that are missing from a full snapshot are marked removed, never
-- deleted. ig_post_id joins niltv_network_posts.post_id for view counts.
--
-- search is a generated tsvector. Each piece is indexed twice: the english
-- config (stemmed, so "games" finds "game") and the simple config (unstemmed,
-- so a prefix query like "basketb:*" finds "basketball"). Weights: title and
-- athletes A, keywords, summary and labels B, caption C.
--
-- library_sync_runs: one row per sync call, ok or not, for the status line.
--
-- The helper functions call each other schema-qualified (public.). pg_dump
-- restores with an empty search_path and inlines library_search_vector while it
-- creates library_items, so an unqualified call would fail the restore.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE OR REPLACE FUNCTION public.library_tsv(doc TEXT, weight "char")
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT setweight(to_tsvector('english'::regconfig, COALESCE(doc, ''))
                     || to_tsvector('simple'::regconfig, COALESCE(doc, '')), weight)
$$;

CREATE OR REPLACE FUNCTION public.library_join(parts TEXT[])
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT COALESCE(array_to_string(parts, ' '), '')
$$;

-- Athlete names and handles from the athletes jsonb array.
CREATE OR REPLACE FUNCTION public.library_athlete_text(athletes JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT COALESCE(string_agg(COALESCE(a->>'name', '') || ' ' || COALESCE(a->>'handle', ''), ' '), '')
    FROM jsonb_array_elements(
        CASE WHEN jsonb_typeof(athletes) = 'array' THEN athletes ELSE '[]'::jsonb END) AS a
$$;

CREATE OR REPLACE FUNCTION public.library_search_vector(
    title TEXT, caption TEXT, summary TEXT, keywords TEXT[],
    sport TEXT, school TEXT, content_type TEXT, content_types TEXT[],
    categories TEXT[], sponsor TEXT, athletes JSONB, unresolved_handles TEXT[])
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT public.library_tsv(title, 'A')
        || public.library_tsv(public.library_athlete_text(athletes) || ' ' || public.library_join(unresolved_handles), 'A')
        || public.library_tsv(public.library_join(keywords) || ' ' || COALESCE(summary, ''), 'B')
        || public.library_tsv(concat_ws(' ', sport, school, content_type, public.library_join(content_types),
                                 public.library_join(categories), sponsor), 'B')
        || public.library_tsv(caption, 'C')
$$;

CREATE TABLE IF NOT EXISTS library_items (
    content_id         TEXT PRIMARY KEY,
    stage              TEXT NOT NULL,
    ig_post_id         TEXT,
    channel_id         TEXT,
    channel_name       TEXT,
    title              TEXT NOT NULL DEFAULT '',
    caption            TEXT,
    summary            TEXT,
    keywords           TEXT[] NOT NULL DEFAULT '{}',
    sport              TEXT,
    school             TEXT,
    content_type       TEXT,
    content_types      TEXT[] NOT NULL DEFAULT '{}',
    categories         TEXT[] NOT NULL DEFAULT '{}',
    sponsor            TEXT,
    athletes           JSONB NOT NULL DEFAULT '[]',
    unresolved_handles TEXT[] NOT NULL DEFAULT '{}',
    status             TEXT NOT NULL DEFAULT '',
    qc_state           TEXT,
    poster_url         TEXT,
    video_url          TEXT,
    duration_sec       DOUBLE PRECISION,
    posted_at          TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ,
    removed            BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_synced_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    search             tsvector GENERATED ALWAYS AS (library_search_vector(
                           title, caption, summary, keywords, sport, school, content_type,
                           content_types, categories, sponsor, athletes, unresolved_handles)) STORED
);

CREATE INDEX IF NOT EXISTS idx_library_items_search ON library_items USING GIN (search);
CREATE INDEX IF NOT EXISTS idx_library_items_content_types ON library_items USING GIN (content_types);
CREATE INDEX IF NOT EXISTS idx_library_items_categories ON library_items USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_library_items_athletes ON library_items USING GIN (athletes jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_library_items_ig_post ON library_items (ig_post_id);
CREATE INDEX IF NOT EXISTS idx_library_items_posted ON library_items (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_library_items_stage ON library_items (stage, removed);

CREATE TABLE IF NOT EXISTS library_sync_runs (
    id           SERIAL PRIMARY KEY,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stage        TEXT,
    generated_at TIMESTAMPTZ,
    received     INTEGER NOT NULL DEFAULT 0,
    upserted     INTEGER NOT NULL DEFAULT 0,
    removed      INTEGER NOT NULL DEFAULT 0,
    ok           BOOLEAN NOT NULL DEFAULT FALSE,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_library_sync_runs_received ON library_sync_runs (received_at DESC);
