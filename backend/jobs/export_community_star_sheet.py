"""Mirror the Community Star applications into the staff Google Sheet.

Writes the "Community Star" tab (one row per application, newest first) to
COMMUNITY_STAR_SHEET_ID, or to the athlete applications sheet
(APPLICATIONS_SHEET_ID) when that is empty. The brief asks for every
application in a live sheet so the team can review them before picking the
25 finalists.

Three TEAM columns are editable in the sheet (tinted header):
  Collab accepted (checkbox), Stage (dropdown), Notes.
Each run first reads the tab back and imports a team-column edit when the
cell no longer matches what the last run wrote (sheet_seen on the row), so
edits made in the sheet and in the dashboard's Community Star page both
survive; when both change the same cell between two runs, the sheet wins.
Every other column is a read-only mirror, overwritten on each run; the
database is the system of record.

Once the finalists are published, Stage is dashboard only: a sheet edit to it
is ignored and the next write puts the database value back. The separate
"Votes" tab then carries per-finalist counts for the team.

Schedule: every 15 minutes.
No-op (exit 0, one log line) until one of the sheet ids is set.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.models import CommunityStarApplication
from backend.onboarding import sheets
from backend.routers.community_star import SEASON, STAGE_LABELS, STAGES, apply_review, parse_stage
from backend.routers.community_star_voting import get_program, vote_tallies

logger = logging.getLogger(__name__)

TAB = "Community Star"
VOTES_TAB = "Votes"
VOTES_HEADER = ["ID", "Finalist", "School", "Stage", "Confirmed", "Pending", "Void", "Updated (UTC)"]

# Team columns: header -> review field. Kept beside the entry so a reviewer
# sees the post link and the decision together.
TEAM = {"Collab accepted": "collab_accepted", "Stage": "stage", "Notes": "notes"}

HEADER = [
    "ID", "Applied (UTC)", "Full name", "School", "Sport", "Class year", "Community",
    "Instagram", "Application post",
    *TEAM,
    "What they're doing", "Organization", "Email", "Phone", "School state", "School from list",
    "Collab invited", "Rules + eligible", "18+", "Privacy",
    "Email opt-in", "SMS opt-in", "Consent version", "Confirmation sent", "UTM", "Dashboard",
]
_TRUE = {"true", "yes", "y", "x", "1", "✓", "✔"}


def _d(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if dt else ""


def _yes(v: Optional[bool]) -> str:
    return "yes" if v else ""


def _team_value(a: CommunityStarApplication, field: str) -> Any:
    """What the sheet cell shows for a team field."""
    if field == "collab_accepted":
        return bool(a.collab_accepted)
    if field == "stage":
        return STAGE_LABELS.get(a.stage, a.stage)
    return a.notes or ""


def _norm(field: str, value: Any) -> str:
    """A team cell as a comparable string ('yes'/'' , stage key, text)."""
    if field == "collab_accepted":
        return "yes" if value is True or str(value).strip().lower() in _TRUE else ""
    if field == "stage":
        return parse_stage(value) or f"?{value}"
    return str(value if value is not None else "").strip()


def _row(a: CommunityStarApplication) -> list[Any]:
    utm = a.utm or {}
    return [
        a.id,
        _d(a.created_at),
        a.full_name,
        a.school,
        a.sport,
        a.class_year,
        a.community,
        f"@{a.instagram}",
        a.post_url,
        *[_team_value(a, f) for f in TEAM.values()],
        a.work,
        a.organization or "",
        a.email,
        a.phone,
        a.school_state or "",
        _yes(a.school_matched),
        _yes(a.collab_invited),
        _yes(a.eligible_and_rules),
        _yes(a.confirm_age),
        _yes(a.consent_privacy),
        _yes(a.consent_email),
        _yes(a.consent_sms),
        a.consent_version or "",
        _yes(a.confirmation_sent),
        ", ".join(f"{k}={v}" for k, v in utm.items()),
        f"{get_settings().dashboard_base_url.rstrip('/')}/community-star?id={a.id}",
    ]


def import_sheet_edits(db: Session, sheet_id: str, by_id: dict[int, CommunityStarApplication],
                       stage_locked: bool = False) -> int:
    """Apply team-column edits made in the sheet since the last run. Returns
    the number of rows changed. ``stage_locked`` skips the Stage column."""
    table = sheets.read_table(sheet_id, TAB)
    if not table:
        return 0
    header = [str(h).strip() for h in table[0]]
    if "ID" not in header:
        return 0
    id_col = header.index("ID")
    cols = {field: header.index(name) for name, field in TEAM.items() if name in header}
    changed_rows = 0
    for cells in table[1:]:
        try:
            a = by_id.get(int(cells[id_col]))
        except (IndexError, TypeError, ValueError):
            continue
        if a is None or not a.sheet_seen:
            continue   # not written by a previous run yet: nothing to compare
        edits = {}
        for field, c in cols.items():
            if field == "stage" and stage_locked:
                continue
            cell = cells[c] if c < len(cells) else ""
            now = _norm(field, cell)
            if now != a.sheet_seen.get(field, now):
                if field == "stage" and now.startswith("?"):
                    logger.warning("community star sheet: row %s has unknown stage %r; ignored", a.id, cell)
                    continue
                edits[field] = (now == "yes") if field == "collab_accepted" else cell
        if edits:
            try:
                apply_review(db, a, edits, by="sheet")
                changed_rows += 1
            except ValueError as e:
                logger.warning("community star sheet: row %s edit ignored: %s", a.id, e)
    db.commit()
    return changed_rows


def write_votes_tab(db: Session, sheet_id: str) -> None:
    """Per-finalist counts on their own tab. A failure here must not cost the
    applications tab its run."""
    stamp = _d(datetime.now(tz=timezone.utc))
    rows = [[r["id"], r["name"], r["school"], STAGE_LABELS.get(r["stage"], r["stage"]),
             r["confirmed"], r["pending"], r["void"], stamp] for r in vote_tallies(db)]
    try:
        sheets.write_table(sheet_id, VOTES_TAB, VOTES_HEADER, rows)
    except sheets.SheetsError as e:
        logger.warning("community star sheet: votes tab skipped: %s", e)


def export_community_star(db: Session) -> int:
    s = get_settings()
    sheet_id = s.community_star_sheet_id or s.applications_sheet_id
    if not sheet_id:
        logger.info("COMMUNITY_STAR_SHEET_ID / APPLICATIONS_SHEET_ID not set; nothing to export")
        return 0
    apps = (db.query(CommunityStarApplication)
            .filter(CommunityStarApplication.season == SEASON)
            .order_by(CommunityStarApplication.created_at.desc(), CommunityStarApplication.id.desc())
            .all())
    published = get_program(db).finalists_published_at is not None
    imported = import_sheet_edits(db, sheet_id, {a.id: a for a in apps}, stage_locked=published)

    n = sheets.write_table(sheet_id, TAB, HEADER, [_row(a) for a in apps])
    team_cols = [HEADER.index(name) for name in TEAM]
    sheets.style_columns(
        sheet_id, TAB, n,
        checkboxes=[HEADER.index("Collab accepted")],
        dropdowns={HEADER.index("Stage"): [STAGE_LABELS[k] for k in STAGES]},
        highlight=team_cols)
    for a in apps:
        a.sheet_seen = {f: _norm(f, _team_value(a, f)) for f in TEAM.values()}
    db.commit()
    if published:
        write_votes_tab(db, sheet_id)
    logger.info("exported %d community star applications to sheet %s (%d sheet edits imported)",
                n, sheet_id, imported)
    return n


def main():
    db = SessionLocal()
    try:
        run_job("export_community_star_sheet", db, export_community_star, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
