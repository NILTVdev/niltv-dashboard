"""
Cron job: Pull NILTV owned + collaborative Instagram posts via the Graph API
and upsert them into the niltv_network_posts table.

Runs every three hours at :15:
    scripts/run_job.sh backend.jobs.run_niltv_network

Replaces the manual CSV upload for views/likes/comments (fully automated). The
CSV upload remains available to backfill shares/saves/reach for collaborative
posts, which the Graph API can't expose (those belong to the athlete's account).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.brand_registry import get_network_accounts
from backend.database import SessionLocal
from backend.jobs.ambassadors import run_ambassador_passes
from backend.jobs.base import run_job, send_sns_alert, upload_to_s3
from backend.jobs.import_niltv_network import SOURCE_GRAPH, upsert_posts
from backend.sources.niltv_collab import fetch_network_posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _pull_niltv_network(db: Session) -> int:
    # Every registry account flagged network_pull walks its owned +
    # collaborative_media edges — this is how athlete collab posts enter the
    # system for each campus channel. See backend/brand_registry.py.
    accounts = get_network_accounts(db)
    if not accounts:
        logger.error("No network accounts configured (brand_accounts.network_pull or BRAND_IG_* env) — aborting.")
        return 0

    pulled_at = datetime.now(tz=timezone.utc)
    all_rows: dict[str, dict] = {}  # post_id -> row, dedupe across accounts
    failed: list[tuple[str, str]] = []  # (account, error) — a channel whose edge
    # failed contributes no tags tonight; the rest still land, and we alert.

    for account, user_id, token in accounts:
        try:
            rows = fetch_network_posts(user_id, token)
        except Exception as e:
            logger.error(f"[{account}] Fetch failed for {user_id}: {e}")
            failed.append((account, str(e)[:300]))
            continue
        for row in rows:
            existing = all_rows.get(row["post_id"])
            if existing is None:
                row["collab_accounts"] = account
                all_rows[row["post_id"]] = row
            else:
                # Same post surfaced via another of our accounts' edges —
                # accumulate the attribution (e.g. "niltv,starkvilletv").
                accounts_seen = {a for a in (existing.get("collab_accounts") or "").split(",") if a}
                accounts_seen.add(account)
                existing["collab_accounts"] = ",".join(sorted(accounts_seen))

    rows = list(all_rows.values())
    if failed:
        # Collab tags only ever grow, so a missed night self-heals on the next
        # successful walk — but a brand-new post pulled tonight via another
        # channel would sit without this channel's tag until then. Say so.
        detail = "\n".join(f"- {a}: {err}" for a, err in failed)
        send_sns_alert(
            subject=f"[NILTV Dashboard] network pull: {len(failed)} channel(s) failed",
            message=f"Time: {pulled_at}\nChannels whose owned/collaborative_media walk failed "
                    f"(their collab tags are missing from tonight's pull):\n{detail}",
        )
    if not rows:
        logger.warning("No posts fetched — nothing to upsert.")
        return 0

    inserted, updated = upsert_posts(db, rows, captured_at=pulled_at, source=SOURCE_GRAPH)
    logger.info(f"NILTV network pull: {inserted} inserted, {updated} updated ({len(rows)} posts)")

    date_str = pulled_at.strftime("%Y-%m-%d")
    upload_to_s3(
        {"pulled_at": pulled_at.isoformat(), "post_count": len(rows), "posts": rows},
        f"backups/niltv_network/{date_str}.json",
    )

    # Stamp ambassador_id on new rows + infer campuses + refresh rollups.
    # Never raises — attribution must not fail the media pull.
    run_ambassador_passes(db)

    return inserted


def main():
    db = SessionLocal()
    try:
        run_job("run_niltv_network", db, _pull_niltv_network, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
