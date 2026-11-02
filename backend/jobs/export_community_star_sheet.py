"""Mirror the Community Star applications into the staff Google Sheet.

Writes the "Community Star" tab (one row per application, newest first) to
COMMUNITY_STAR_SHEET_ID, or to the athlete applications sheet
(APPLICATIONS_SHEET_ID) when that is empty. The brief asks for every
application in a live sheet so the team can review them before picking the
25 finalists.

The sheet is a read-only mirror. Edits made in it are overwritten on the next
run; the database is the system of record.

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
from backend.routers.community_star import SEASON

logger = logging.getLogger(__name__)

TAB = "Community Star"

HEADER = [
    "ID", "Applied (UTC)", "Full name", "Email", "Phone",
    "School", "School state", "School from list", "Sport", "Class year",
    "Instagram", "Application post", "Community", "What they're doing", "Organization",
    "Collab invited", "Rules + eligible", "18+", "Privacy",
    "Email opt-in", "SMS opt-in", "Partner opt-in", "Consent version",
    "Confirmation sent", "UTM",
]


def _d(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if dt else ""


def _yes(v: Optional[bool]) -> str:
    return "yes" if v else ""


def _row(a: CommunityStarApplication) -> list[Any]:
    utm = a.utm or {}
    return [
        a.id,
        _d(a.created_at),
        a.full_name,
        a.email,
        a.phone,
        a.school,
        a.school_state or "",
        _yes(a.school_matched),
        a.sport,
        a.class_year,
        f"@{a.instagram}",
        a.post_url,
        a.community,
        a.work,
        a.organization or "",
        _yes(a.collab_invited),
        _yes(a.eligible_and_rules),
        _yes(a.confirm_age),
        _yes(a.consent_privacy),
        _yes(a.consent_email),
        _yes(a.consent_sms),
        _yes(a.consent_partners),
        a.consent_version or "",
        _yes(a.confirmation_sent),
        ", ".join(f"{k}={v}" for k, v in utm.items()),
    ]


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
    n = sheets.write_table(sheet_id, TAB, HEADER, [_row(a) for a in apps])
    logger.info("exported %d community star applications to sheet %s", n, sheet_id)
    return n


def main():
    db = SessionLocal()
    try:
        run_job("export_community_star_sheet", db, export_community_star, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
