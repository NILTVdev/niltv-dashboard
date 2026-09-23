"""
One-off backfill: populate the ambassador registry from historical data.

Runs the same three passes the nightly jobs run (welcome parser over all
@niltv captions, attribution over every network post, campus inference),
then the cache precompute — so historical posts show up on the tracking
page right away. Idempotent: safe to re-run.

Run with the venv active and a filled .env:

    python -m scripts.backfill_ambassadors --dry-run   # show what would change
    python -m scripts.backfill_ambassadors             # write it

    # Include campus-channel announcement accounts in the caption scan:
    python -m scripts.backfill_ambassadors --accounts niltv,truebluetv

Requires migrations 020-022.
"""

import argparse
import logging

from backend.database import SessionLocal
from backend.jobs.ambassadors import (
    ANNOUNCE_ACCOUNTS,
    attribute_posts,
    infer_campuses,
    scan_welcome_posts,
)
from backend.jobs.precompute import precompute_ambassador_cache
from backend.models import Ambassador

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill the ambassador registry from historical data")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing them")
    parser.add_argument(
        "--accounts", default=",".join(ANNOUNCE_ACCOUNTS),
        help="comma list of announce accounts to scan for welcome posts (default: %(default)s)",
    )
    args = parser.parse_args()

    accounts = tuple(a.strip().lower() for a in args.accounts.split(",") if a.strip())

    db = SessionLocal()
    if args.dry_run:
        # Downgrade commits to flushes so the passes run exactly as they
        # would in production, then throw everything away at the end.
        db.commit = db.flush  # type: ignore[method-assign]

    try:
        scan_counts = scan_welcome_posts(db, accounts=accounts)
        stamped = attribute_posts(db)
        campuses = infer_campuses(db)
        precompute_ambassador_cache(db)

        rows = (
            db.query(Ambassador)
            .filter(Ambassador.status != "removed")
            .order_by(Ambassador.status.desc(), Ambassador.ig_username)
            .all()
        )
        print(f"\n{'='*72}")
        print(f"  AMBASSADOR BACKFILL {'(DRY RUN — nothing written)' if args.dry_run else ''}")
        print(f"{'='*72}")
        print(f"  Welcome scan: {scan_counts or 'no welcome posts found'}")
        print(f"  Posts attributed: {stamped}")
        print(f"  Campuses inferred: {campuses}")
        print(f"  Registry ({len(rows)} non-removed):")
        for a in rows:
            print(
                f"    @{a.ig_username:<28} {a.status:<10} campus={a.campus or '—':<12} "
                f"posts={a.cached_collab_posts or 0:<4} views={a.cached_collab_views or 0}"
            )
        print(f"{'='*72}\n")

        if args.dry_run:
            db.rollback()
            print("Dry run — rolled back. Re-run without --dry-run to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
