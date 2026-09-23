-- 027: rename the 'scraper' views_source value to 'public'.
--
-- views_source records which feed last wrote `views`. The lowest-ranked value
-- is called 'public' in code (import_niltv_network.SOURCE_PUBLIC).

UPDATE niltv_network_posts SET views_source = 'public' WHERE views_source = 'scraper';

COMMENT ON COLUMN niltv_network_posts.views_source IS
    'Who last wrote views: graph (nightly Graph API) > export (Business Suite CSV) > bd / public (play count). A lower-ranked source never overwrites a higher one.';
