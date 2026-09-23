"""
One-off backfill: full-history insights for every owned brand account.

The nightly run_brand_ig job only refreshes each account's most recent posts,
so older @niltv rows predate the `shares` column (and any post that fell out
of the refresh window is missing whatever metrics were added since). This job
pages through the ENTIRE /media edge of every account in the merged registry
(brand_accounts table + legacy .env — see backend/brand_registry.py), pulls
per-post insights (views, reach, saves, shares + likes/comments), upserts into
brand_posts, and copies owned-account insights onto matching
niltv_network_posts rows.

Run manually (expect ~1.5s per post — a few hundred posts take minutes):
    ./scripts/run_job.sh backend.jobs.backfill_brand_ig
Backfill a single account (e.g. right after onboarding a campus channel):
    ./scripts/run_job.sh backend.jobs.backfill_brand_ig truebluetv
"""

import logging
import sys
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.brand_registry import get_brand_targets
from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.jobs.run_brand_ig import enrich_network_from_brand, upsert_brand_posts
from backend.sources.brand_ig import fetch_all_brand_posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _backfill(db: Session, only_account: str | None = None) -> int:
    targets = get_brand_targets(db)
    if only_account:
        targets = [t for t in targets if t["account"] == only_account]
        if not targets:
            logger.error(f"Account '{only_account}' not found in the registry — aborting.")
            return 0
    if not targets:
        logger.error("No brand accounts configured — aborting.")
        return 0

    pulled_at = datetime.now(tz=timezone.utc)

    total = 0
    for target in targets:
        account = target["account"]
        logger.info(f"[{account}] Backfilling full post history...")

        posts = fetch_all_brand_posts(
            ig_user_id=target["ig_user_id"],
            access_token=target["access_token"],
            api=target.get("api", "fb"),
        )
        if not posts:
            logger.warning(f"[{account}] No posts returned — check token grants for this account.")
            continue

        inserted = upsert_brand_posts(db, account, posts, pulled_at)
        enriched = enrich_network_from_brand(db, posts, pulled_at)
        logger.info(
            f"[{account}] Backfill complete: {len(posts)} posts processed, "
            f"{inserted} inserted, {len(posts) - inserted} updated, "
            f"{enriched} network rows enriched."
        )
        total += len(posts)

    return total


def main():
    only_account = sys.argv[1] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        run_job("backfill_brand_ig", db, _backfill, db, only_account)
    finally:
        db.close()


if __name__ == "__main__":
    main()
