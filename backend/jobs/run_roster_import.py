"""
Job: Import / sync athletes from the roster spreadsheet into the database.

The xlsx contains athlete PII and is NOT tracked in git. The job reads the path
in ROSTER_XLSX, or data/roster.xlsx under the repo root when that is unset. To
update the roster, replace that file, then run this job manually:
    python -m backend.jobs.run_roster_import

Behaviour:
  - Upsert athletes found in the xlsx (add new, update existing)
  - Mark athletes no longer in the xlsx as inactive (preserves their data)
"""

import logging
from datetime import datetime, timezone
import os
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Athlete
from backend.jobs.base import run_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

XLSX_PATH = Path(os.environ.get("ROSTER_XLSX") or Path(__file__).parent.parent.parent / "data" / "roster.xlsx")


def _parse_handle(val) -> str | None:
    if pd.isna(val) or not str(val).strip():
        return None
    return str(val).strip().lstrip("@") or None


def _import_roster(db: Session) -> int:
    if not XLSX_PATH.exists():
        raise FileNotFoundError(f"Roster file not found at: {XLSX_PATH}")

    df = pd.read_excel(XLSX_PATH)
    logger.info(f"Loaded {len(df)} rows from {XLSX_PATH.name}")

    for col in ("First Name", "Last Name"):
        if col not in df.columns:
            raise ValueError(f"Missing required column in xlsx: '{col}'")

    df["name"] = df["First Name"].str.strip() + " " + df["Last Name"].str.strip()
    df["ig_handle"] = df.get("Insta Handle", pd.Series(dtype=str)).apply(_parse_handle)
    df["tiktok_handle"] = df.get("TikTok Handle", pd.Series(dtype=str)).apply(_parse_handle)
    df["x_handle"] = df.get("X Handle", pd.Series(dtype=str)).apply(_parse_handle)
    df["sport"] = df.get("Sport", pd.Series(dtype=str)).apply(
        lambda v: str(v).strip() if not pd.isna(v) else None
    )
    df["year"] = df.get("Year", pd.Series(dtype=str)).apply(
        lambda v: str(v).strip() if not pd.isna(v) else None
    )

    # Deduplicate: if the same ig_handle appears twice in the xlsx, keep first row only
    before = len(df)
    df = df.drop_duplicates(subset=["ig_handle"], keep="first")
    df = df.drop_duplicates(subset=["name"], keep="first")
    dupes = before - len(df)
    if dupes:
        logger.warning(f"Dropped {dupes} duplicate rows from roster (same ig_handle or name).")

    current_ig_handles = set(df["ig_handle"].dropna().tolist())
    new_count = 0

    for _, row in df.iterrows():
        name = str(row["name"]).strip()
        ig_handle = row.get("ig_handle")
        if not name:
            continue

        # Match by ig_handle first, then fall back to name
        existing = None
        if ig_handle:
            existing = db.query(Athlete).filter(Athlete.ig_handle == ig_handle).first()
        if not existing:
            existing = db.query(Athlete).filter(Athlete.name == name).first()

        now = datetime.now(tz=timezone.utc)

        if existing:
            existing.name = name
            existing.sport = row.get("sport")
            existing.year = row.get("year")
            existing.ig_handle = ig_handle
            existing.tiktok_handle = row.get("tiktok_handle")
            existing.x_handle = row.get("x_handle")
            existing.active = True
            existing.updated_at = now
        else:
            db.add(Athlete(
                name=name,
                sport=row.get("sport"),
                year=row.get("year"),
                ig_handle=ig_handle,
                tiktok_handle=row.get("tiktok_handle"),
                x_handle=row.get("x_handle"),
                active=True,
            ))
            new_count += 1

    # Athletes no longer in the roster → mark inactive (data preserved)
    deactivated = (
        db.query(Athlete)
        .filter(
            Athlete.active == True,
            Athlete.ig_handle.isnot(None),
            ~Athlete.ig_handle.in_(current_ig_handles),
        )
        .update({"active": False, "updated_at": datetime.now(tz=timezone.utc)}, synchronize_session=False)
    )
    if deactivated:
        logger.info(f"Marked {deactivated} athletes as inactive (no longer in roster).")

    db.commit()
    logger.info(f"Roster import done. {new_count} new athletes added.")
    return new_count


def main():
    db = SessionLocal()
    try:
        run_job("run_roster_import", db, _import_roster, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
