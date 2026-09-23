-- 027: Clear token stamps on brand_accounts rows that do not hold their own token.
--
-- token_refreshed_at / token_expires_at describe a row's OWN access_token.
-- A row that moves from its own token onto the shared BRAND_IG_ACCESS_TOKEN
-- (access_token = NULL) keeps its old stamps, which then read as a real
-- expiry on the registry page. The refresh job only ever re-stamps own-token
-- rows, so those stamps never clear on their own. The registry API also hides
-- stamps on shared-token rows.
--
-- Applied automatically by scripts/migrate.py on deploy.

UPDATE brand_accounts
SET token_expires_at = NULL,
    token_refreshed_at = NULL,
    updated_at = NOW()
WHERE access_token IS NULL
  AND (token_expires_at IS NOT NULL OR token_refreshed_at IS NOT NULL);
