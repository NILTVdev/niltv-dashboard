"""
Import the Campus Ambassadors master sheet into the ambassador registry.

The sheet keys on name + school and has NO Instagram handles, so each row is
fuzzy-matched against existing ambassadors (by display_name, then by
name-vs-handle similarity). Matched rows get their roster fields updated;
unmatched rows are created with a NULL handle (status confirmed,
source='sheet_import') — fill the handle later via the admin update endpoint
and their collab posts attribute the same night.

Follower numbers are self-reported survey data: they land as one
ambassador_snapshots row per person with source='reported', never mixed
into the nightly Business Discovery trendline. TikTok/YouTube have no pull
pipeline, so re-importing a fresh sheet is how those numbers move.

The sheet itself is NOT committed (*.csv is gitignored). Pass the path to a
CSV export, or place it at DEFAULT_SHEET.

Run with the venv active and a filled .env:

    python -m scripts.import_ambassador_sheet --dry-run            # match report only
    python -m scripts.import_ambassador_sheet                      # write it
    python -m scripts.import_ambassador_sheet path/to/sheet.csv --cohort F27
    python -m scripts.import_ambassador_sheet --deactivate-missing # retire cohort rows absent from the sheet

Idempotent: re-running updates roster fields, skips unchanged reported
snapshots, and never duplicates people it can match. ALWAYS eyeball the
match report before a non-dry run — name-to-handle matching is heuristic.

Requires migrations 020-024.
"""

import argparse
import csv
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from backend.database import SessionLocal
from backend.jobs.ambassadors import infer_campuses
from backend.jobs.precompute import precompute_ambassador_cache
from backend.models import Ambassador, AmbassadorSnapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SHEET = "data/niltv_campus_ambassadors_f26.csv"
DEFAULT_COHORT = "F26"

# Values that mean "no number" even though they aren't empty.
_NULLISH = {"n/a", "na", "none", "-", "nan"}
# Number tokens: comma-grouped ("1,332"), k-suffixed ("24.6k"), or plain.
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*[kK]\b|\d+(?:\.\d+)?")


def parse_count(val) -> int | None:
    """Best-effort follower count from a messy survey cell.

    Handles '39,900', '24.6k', '150 / 1700' (max wins), prose like
    '972- I started it only a couple months ago', and N/A variants.
    Returns None when no number is present.
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in _NULLISH:
        return None
    candidates = []
    for tok in _NUM_RE.findall(s):
        tok = tok.strip().lower()
        if tok.endswith("k"):
            candidates.append(int(float(tok[:-1].strip()) * 1000))
        else:
            candidates.append(int(float(tok.replace(",", ""))))
    return max(candidates) if candidates else None


def name_key(s: str | None) -> str:
    """Lowercase alpha-only key for name/handle comparison."""
    return re.sub(r"[^a-z]", "", (s or "").lower())


def parse_sheet(fh) -> tuple[list[dict], int]:
    """Parse the master CSV into row dicts, deduping repeated names (last
    occurrence wins — later rows are assumed fresher). Returns (rows, dupes).
    Summary columns to the right of M/F are ignored."""
    by_key: dict[str, dict] = {}
    dupes = 0
    for raw in csv.DictReader(fh):
        name = (raw.get("NAME") or "").strip()
        if not name:
            continue
        key = name_key(name)
        if key in by_key:
            dupes += 1
        by_key[key] = {
            "name": name,
            "name_key": key,
            "school": (raw.get("SCHOOL") or "").strip() or None,
            "sport": (raw.get("SPORT") or "").strip() or None,
            "year": (raw.get("YEAR (F26)") or "").strip() or None,
            "gender": (raw.get("M/F") or "").strip().upper() or None,
            "ig_followers": parse_count(raw.get("Insta Followers")),
            "tiktok_followers": parse_count(raw.get("TikTok Followers")),
            "youtube_subscribers": parse_count(raw.get("YouTube Subscribers")),
        }
    return list(by_key.values()), dupes


TIER_SCORE = {"exact-name": 100, "handle-contains": 90, "handle-fuzzy": 85, "last-name": 60, "first-name": 50}
# Below this score a match is reported for review instead of applied: a first
# name alone can match two different people on one cohort sheet, and writing
# the sheet's name/school onto the wrong row is worse than leaving it blank.
DEFAULT_MIN_SCORE = 85


def match_ambassador(row: dict, existing: list[Ambassador]) -> tuple[Ambassador | None, str]:
    """Match one sheet row to an existing ambassador.

    Tiers: exact display-name (100), full-name vs handle containment (90),
    fuzzy full-name ratio >= 0.85 (85), last name in handle (60), long first
    name in handle (50). A tie at the top score is ambiguous -> no match.
    Returns (ambassador | None, tier_label).
    """
    tokens = [t for t in re.split(r"\s+", row["name"].lower()) if name_key(t)]
    full = row["name_key"]
    first = name_key(tokens[0]) if tokens else ""
    last = name_key(tokens[-1]) if len(tokens) > 1 else ""

    scored: list[tuple[int, Ambassador]] = []
    for a in existing:
        best = 0
        if a.display_name and name_key(a.display_name) == full:
            best = 100
        ukey = name_key(a.ig_username)
        if ukey and len(full) >= 6:
            if best < 90 and (full in ukey or ukey in full):
                best = 90
            if best < 85 and SequenceMatcher(None, full, ukey).ratio() >= 0.85:
                best = 85
        if ukey and best < 60 and len(last) >= 4 and last in ukey:
            best = 60
        if ukey and best < 50 and len(first) >= 5 and first in ukey:
            best = 50
        if best:
            scored.append((best, a))

    if not scored:
        return None, "none"
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous"
    score, winner = scored[0]
    tier = {100: "exact-name", 90: "handle-contains", 85: "handle-fuzzy", 60: "last-name", 50: "first-name"}[score]
    return winner, tier


def _latest_reported(db, ambassador_id: int) -> AmbassadorSnapshot | None:
    return (
        db.query(AmbassadorSnapshot)
        .filter(AmbassadorSnapshot.ambassador_id == ambassador_id, AmbassadorSnapshot.source == "reported")
        .order_by(AmbassadorSnapshot.pulled_at.desc())
        .first()
    )


def import_rows(db, rows: list[dict], cohort: str, deactivate_missing: bool = False,
                min_score: int = DEFAULT_MIN_SCORE) -> dict:
    """Upsert sheet rows into the registry. Returns a report dict.

    A match scoring below `min_score` is neither applied nor turned into a new
    row: it lands in report["review"] for a person to resolve (add the handle
    to the sheet, or fill the row via the admin update). A second sheet row
    landing on an ambassador already claimed in this run is a "conflict" and
    is skipped the same way. After the write, campus inference runs so rows
    whose school is one of our campus nodes pick up their campus immediately."""
    now = datetime.now(tz=timezone.utc)
    existing = db.query(Ambassador).all()
    report = {
        "matched": [], "created": [], "ambiguous": [], "review": [], "conflict": [],
        "snapshots": 0, "deactivated": [], "campus_assigned": 0,
    }
    touched_ids: set[int] = set()

    for row in rows:
        ambassador, tier = match_ambassador(row, existing)
        if ambassador is None and tier == "ambiguous":
            report["ambiguous"].append(row["name"])
            continue
        if ambassador is not None and TIER_SCORE.get(tier, 0) < min_score:
            report["review"].append((row["name"], ambassador.ig_username, tier))
            continue
        if ambassador is not None and ambassador.id is not None and ambassador.id in touched_ids:
            report["conflict"].append((row["name"], ambassador.ig_username, tier))
            continue

        if ambassador is None:
            ambassador = Ambassador(
                display_name=row["name"], status="confirmed", source="sheet_import",
            )
            db.add(ambassador)
            existing.append(ambassador)
            report["created"].append(row["name"])
        else:
            report["matched"].append((row["name"], ambassador.ig_username, tier))
            ambassador.updated_at = now

        # Sheet is authoritative for roster fields.
        ambassador.display_name = row["name"]
        ambassador.school = row["school"]
        ambassador.sport = row["sport"]
        ambassador.year = row["year"]
        ambassador.gender = row["gender"]
        ambassador.cohort = cohort
        db.flush()  # assigns id for new rows
        touched_ids.add(ambassador.id)

        # One 'reported' snapshot per import, skipped when identical to the
        # last one so re-running the same sheet doesn't stack duplicates.
        values = (row["ig_followers"], row["tiktok_followers"], row["youtube_subscribers"])
        if any(v is not None for v in values):
            prev = _latest_reported(db, ambassador.id)
            if not prev or (prev.followers, prev.tiktok_followers, prev.youtube_subscribers) != values:
                db.add(AmbassadorSnapshot(
                    ambassador_id=ambassador.id, pulled_at=now, source="reported",
                    followers=row["ig_followers"],
                    tiktok_followers=row["tiktok_followers"],
                    youtube_subscribers=row["youtube_subscribers"],
                ))
                report["snapshots"] += 1

    if deactivate_missing:
        # Only rows of THIS cohort can be retired by its sheet; auto-discovered
        # ambassadors (cohort NULL) are never touched. Soft only — history and
        # attributed posts stay intact.
        for a in existing:
            if a.cohort == cohort and a.id not in touched_ids and a.active and a.id is not None:
                a.active = False
                a.updated_at = now
                report["deactivated"].append(a.display_name or a.ig_username or str(a.id))

    db.commit()
    report["campus_assigned"] = infer_campuses(db)
    precompute_ambassador_cache(db)
    return report


def main():
    parser = argparse.ArgumentParser(description="Import the Campus Ambassadors master sheet")
    parser.add_argument("csv_file", nargs="?", default=DEFAULT_SHEET)
    parser.add_argument("--cohort", default=DEFAULT_COHORT)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--deactivate-missing", action="store_true",
                        help="soft-retire ambassadors of this cohort absent from the sheet")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE,
                        help=f"apply matches at or above this score; weaker ones are listed for review "
                             f"(default {DEFAULT_MIN_SCORE}: exact name, handle contains name, fuzzy name)")
    args = parser.parse_args()

    with open(args.csv_file, encoding="utf-8-sig") as fh:
        rows, dupes = parse_sheet(fh)

    db = SessionLocal()
    if args.dry_run:
        db.commit = db.flush  # type: ignore[method-assign]
    try:
        report = import_rows(db, rows, cohort=args.cohort, deactivate_missing=args.deactivate_missing,
                             min_score=args.min_score)

        print(f"\n{'='*76}")
        print(f"  AMBASSADOR SHEET IMPORT {'(DRY RUN — nothing written)' if args.dry_run else ''}")
        print(f"  {args.csv_file} → cohort {args.cohort} · {len(rows)} people ({dupes} in-sheet dupes collapsed)")
        print(f"{'='*76}")
        print(f"  Matched to existing ({len(report['matched'])}):")
        for name, username, tier in report["matched"]:
            flag = "" if tier in ("exact-name", "handle-contains", "handle-fuzzy") else "   <-- VERIFY"
            print(f"    {name:<32} -> @{username:<26} [{tier}]{flag}")
        print(f"  Created with NO handle ({len(report['created'])}) — fill via admin update:")
        for name in report["created"]:
            print(f"    {name}")
        if report["review"]:
            print(f"  REVIEW — weak match, skipped ({len(report['review'])}); add the handle to the sheet "
                  f"or set school/campus via admin update:")
            for name, username, tier in report["review"]:
                print(f"    {name:<32} ~> @{username:<26} [{tier}]")
        if report["conflict"]:
            print(f"  CONFLICT — ambassador already claimed by an earlier row, skipped ({len(report['conflict'])}):")
            for name, username, tier in report["conflict"]:
                print(f"    {name:<32} ~> @{username:<26} [{tier}]")
        if report["ambiguous"]:
            print(f"  AMBIGUOUS — skipped, resolve by hand ({len(report['ambiguous'])}):")
            for name in report["ambiguous"]:
                print(f"    {name}")
        print(f"  Campus assigned from posts/school: {report['campus_assigned']}")
        if report["deactivated"]:
            print(f"  Deactivated ({len(report['deactivated'])}): {', '.join(report['deactivated'])}")
        print(f"  Reported snapshots written: {report['snapshots']}")
        print(f"{'='*76}\n")

        if args.dry_run:
            db.rollback()
            print("Dry run — rolled back. Re-run without --dry-run to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
