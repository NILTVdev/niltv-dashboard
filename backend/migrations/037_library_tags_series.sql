-- 037: Library carries the rest of the content API tagging.
--
-- New library_items columns, sent by the app's sync:
--   tags         staff tags from the admin tool (the content API's partner tags)
--   asset_type   'episode' | 'clip' | 'short', as the content API reports it
--   series_id, series_name, season, episode   the show a clip belongs to
--
-- Tags and the series name join the search vector at weight B, so a search
-- for a tag or a show finds its clips. A generated column cannot change its
-- expression in place, so search is dropped and added again with the new
-- function (Postgres recomputes it for every row; the table is small).
--
-- The helper functions stay schema-qualified (see 036) so pg_dump restores.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE library_items ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE library_items ADD COLUMN IF NOT EXISTS asset_type TEXT;
ALTER TABLE library_items ADD COLUMN IF NOT EXISTS series_id TEXT;
ALTER TABLE library_items ADD COLUMN IF NOT EXISTS series_name TEXT;
ALTER TABLE library_items ADD COLUMN IF NOT EXISTS season INTEGER;
ALTER TABLE library_items ADD COLUMN IF NOT EXISTS episode INTEGER;

CREATE OR REPLACE FUNCTION public.library_search_vector_v2(
    title TEXT, caption TEXT, summary TEXT, keywords TEXT[],
    sport TEXT, school TEXT, content_type TEXT, content_types TEXT[],
    categories TEXT[], sponsor TEXT, athletes JSONB, unresolved_handles TEXT[],
    tags TEXT[], series_name TEXT)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT public.library_search_vector(title, caption, summary, keywords, sport, school, content_type,
                                        content_types, categories, sponsor, athletes, unresolved_handles)
        || public.library_tsv(public.library_join(tags) || ' ' || COALESCE(series_name, ''), 'B')
$$;

DROP INDEX IF EXISTS idx_library_items_search;
ALTER TABLE library_items DROP COLUMN IF EXISTS search;
ALTER TABLE library_items ADD COLUMN search tsvector GENERATED ALWAYS AS (public.library_search_vector_v2(
    title, caption, summary, keywords, sport, school, content_type, content_types, categories, sponsor,
    athletes, unresolved_handles, tags, series_name)) STORED;
CREATE INDEX IF NOT EXISTS idx_library_items_search ON library_items USING GIN (search);

CREATE INDEX IF NOT EXISTS idx_library_items_tags ON library_items USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_library_items_series ON library_items (series_id);
