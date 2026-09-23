#!/usr/bin/env python3
"""
Seed a LOCAL / DEV database from a folder of backup JSON files (default
seed/backups/). The backups never contain tokens.

    python -m scripts.seed_local --backups seed/backups

Maintainers with bucket access can add --sync to download the backups first
(for example --sync --days 30).

What it fills:
  brand_accounts          one row per channel folder (backups/brand_ig_<account>/),
                          api='fb', active, network_pull for the channels the
                          nightly collab walk covers, access_token NULL, ig_user_id 'seed'.
  brand_snapshots         one per channel per backup day (followers, post_count, bio).
  brand_posts             the latest backup's owned posts per channel (insights included).
  niltv_network_posts     every daily backups/niltv_network/<date>.json replayed in date
  + snapshots             order through import_niltv_network.upsert_posts (source=graph),
                          so views/likes history and collab tags look like production.

Idempotent: re-running updates in place. Refuses to run when ENVIRONMENT=production.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs.import_niltv_network import SOURCE_GRAPH, upsert_posts
from backend.models import BrandAccount, BrandPost, BrandSnapshot

BUCKET = "niltv-dashboard-backups"
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "seed" / "backups"
# Channels the nightly collab walk covers (brand_accounts.network_pull=true).
NETWORK_PULL = {"niltv", "brazostv", "chapelhilltv", "collegestationtv", "dorecitytv",
                "goldendometv", "redpacktv", "saltcitytv", "starkvilletv"}
CAMPUS = {"chapelhilltv": "unc", "dorecitytv": "vanderbilt", "goldendometv": "notre-dame",
          "starkvilletv": "mississippi-state", "truebluetv": "duke"}


def _ts(v):
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def sync(dest: Path, days: int) -> None:
    """Copy the last `days` of niltv_network + brand_ig* backups from S3."""
    import boto3
    s3 = boto3.client("s3", region_name=get_settings().aws_region)
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    paginator = s3.get_paginator("list_objects_v2")
    n = 0
    for page in paginator.paginate(Bucket=BUCKET, Prefix="backups/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) != 3 or not (parts[1] == "niltv_network" or parts[1].startswith("brand_ig")):
                continue
            if parts[2][:10] < cutoff:
                continue
            target = dest / parts[1] / parts[2]
            if target.exists() and target.stat().st_size == obj["Size"]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(BUCKET, key, str(target))
            n += 1
    print(f"synced {n} new file(s) into {dest}")


def seed_brands(db, root: Path) -> None:
    for folder in sorted(root.glob("brand_ig*")):
        files = sorted(folder.glob("*.json"))
        if not files:
            continue
        account = folder.name.replace("brand_ig_", "") if folder.name != "brand_ig" else "niltv"
        latest = json.loads(files[-1].read_text(encoding="utf-8"))
        row = db.query(BrandAccount).filter_by(account=account).first()
        if row is None:
            row = BrandAccount(account=account, ig_user_id="seed", api="fb", active=True)
            db.add(row)
        row.username = latest.get("username") or account
        row.network_pull = account in NETWORK_PULL
        row.campus = CAMPUS.get(account, row.campus)
        row.access_token = None
        row.notes = "seeded from S3 backups — no token"
        db.flush()

        existing_days = {
            s.pulled_at.date() for s in db.query(BrandSnapshot).filter_by(account=account).all() if s.pulled_at
        }
        for f in files:
            day = datetime.strptime(f.stem[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if day.date() in existing_days:
                continue
            j = json.loads(f.read_text(encoding="utf-8"))
            db.add(BrandSnapshot(account=account, pulled_at=day + timedelta(hours=5),
                                 username=j.get("username"), followers=j.get("followers"),
                                 post_count=j.get("post_count"), bio=j.get("bio")))
        for p in latest.get("posts") or []:
            if not p.get("ig_post_id"):
                continue
            bp = db.query(BrandPost).filter_by(ig_post_id=p["ig_post_id"]).first()
            if bp is None:
                bp = BrandPost(account=account, ig_post_id=p["ig_post_id"])
                db.add(bp)
            for k in ("media_type", "caption", "like_count", "comment_count", "permalink",
                      "media_url", "thumbnail_url", "impressions", "reach", "saves", "views", "shares"):
                if p.get(k) is not None:
                    setattr(bp, k, p[k])
            bp.posted_at = _ts(p.get("posted_at"))
        db.commit()
        print(f"  {account:18} {len(files)} snapshot day(s), {len(latest.get('posts') or [])} owned posts")


def seed_network(db, root: Path) -> None:
    files = sorted((root / "niltv_network").glob("*.json"))
    if not files:
        print("  no niltv_network backups found")
        return
    for f in files:
        j = json.loads(f.read_text(encoding="utf-8"))
        rows = []
        for p in j.get("posts", []):
            r = dict(p)
            r["publish_time"] = _ts(r.get("publish_time"))
            r.pop("_bucket", None)
            rows.append(r)
        captured = _ts(j.get("pulled_at")) or datetime.strptime(f.stem[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        inserted, updated = upsert_posts(db, rows, captured_at=captured, source=SOURCE_GRAPH)
        print(f"  {f.stem}: {len(rows)} posts ({inserted} new, {updated} updated)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed a local/dev database from the nightly S3 backups")
    ap.add_argument("--backups", type=Path, default=DEFAULT_DIR, help=f"backup folder (default {DEFAULT_DIR})")
    ap.add_argument("--sync", action="store_true", help="download backups from S3 first (needs bucket read access)")
    ap.add_argument("--days", type=int, default=30, help="with --sync: how many days back (default 30)")
    args = ap.parse_args()

    settings = get_settings()
    if settings.is_production:
        print("refusing to seed: ENVIRONMENT=production", file=sys.stderr)
        return 2
    if args.sync:
        sync(args.backups, args.days)
    if not args.backups.exists():
        print(f"no backups at {args.backups}; run with --sync or copy a folder there", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        print("brand accounts / snapshots / owned posts:")
        seed_brands(db, args.backups)
        print("network posts (chronological replay):")
        seed_network(db, args.backups)
    finally:
        db.close()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
