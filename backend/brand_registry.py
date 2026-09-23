"""
Merged registry of owned brand IG accounts the pipeline pulls.

Source of truth is the brand_accounts table (onboard with
scripts/add_brand_account.py); the legacy .env registry
(Settings.brand_ig_targets()) remains as a fallback so existing deploys
keep working before/without the migration. A DB row overrides the env
entry with the same account name; setting a row inactive removes the
account entirely, even if it is still listed in .env.

Target dict shape (superset of the legacy env shape, so the jobs and the
token-refresh cron can consume either):
    account        DB discriminator (brand_posts.account)
    ig_user_id     numeric id, or "me" for Instagram-Login tokens
    access_token   resolved token (portfolio fallback already applied)
    token_env_var  .env var holding the token (env-sourced targets only, else None)
    db_id          brand_accounts.id (DB-sourced targets only, else None)
    own_token      True when the target has its own token (False = shares the
                   BRAND_IG_ACCESS_TOKEN portfolio grant)
    api            "fb" | "ig"
    limit          media fetch limit per nightly run
    campus         school/node grouping (DB-sourced only)
    network_pull   include in the collab/network job
"""

import logging

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import BrandAccount

logger = logging.getLogger(__name__)


def get_brand_targets(db: Session) -> list[dict]:
    settings = get_settings()

    targets: dict[str, dict] = {}
    for t in settings.brand_ig_targets():
        targets[t["account"]] = {
            **t,
            "db_id": None,
            "own_token": t["token_env_var"] != "BRAND_IG_ACCESS_TOKEN" or t["account"] == "niltv",
            "campus": None,
            # Matches the historical behavior of run_niltv_network: only the
            # main brand account walked the collaborative_media edge.
            "network_pull": t["account"] == "niltv",
        }

    try:
        rows = db.query(BrandAccount).order_by(BrandAccount.id).all()
    except Exception as e:
        # Table not migrated yet — env registry still serves everything.
        logger.warning(f"brand_accounts unavailable ({e}); using .env registry only.")
        db.rollback()
        return list(targets.values())

    for row in rows:
        if (row.api or "fb") == "bd":
            # Manual channel: no token can reach it; run_manual_channels.py owns it
            # (Business Discovery + CSV uploads). Never a Graph pull target.
            continue
        if not row.active:
            targets.pop(row.account, None)
            continue
        token = row.access_token or settings.brand_ig_access_token
        if not token:
            logger.warning(f"[{row.account}] no token and no BRAND_IG_ACCESS_TOKEN fallback — skipping.")
            continue
        targets[row.account] = {
            "account": row.account,
            "ig_user_id": row.ig_user_id,
            "access_token": token,
            "token_env_var": None,
            "db_id": row.id,
            "own_token": bool(row.access_token),
            "api": row.api or "fb",
            "limit": row.post_limit or 25,
            "campus": row.campus,
            "network_pull": bool(row.network_pull),
        }

    return list(targets.values())


def get_network_accounts(db: Session) -> list[tuple[str, str, str]]:
    """(account, ig_user_id, token) triples for the collab/network job. Only
    Facebook-API accounts qualify — the collaborative_media edge lives on
    graph.facebook.com and Instagram-Login tokens are host-locked away from it.
    The account name feeds collab_accounts attribution on network posts."""
    triples: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for t in get_brand_targets(db):
        if not t["network_pull"] or t.get("api") != "fb":
            continue
        if t["ig_user_id"] in seen:
            continue
        seen.add(t["ig_user_id"])
        triples.append((t["account"], t["ig_user_id"], t["access_token"]))
    return triples
