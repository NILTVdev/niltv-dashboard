"""Mirror the applications table into the staff Google Sheet.

Writes two tabs to the spreadsheet in ``APPLICATIONS_SHEET_ID``:
  - "Applications": one row per athlete with status, dates, what Stripe still
    needs, and a link back to the dashboard row
  - "Summary": counts by status + last refresh time

The sheet is a read-only mirror for staff. Edits made in the sheet are
overwritten on the next run; the dashboard is the system of record. Raw form
answers stay out of the sheet (they're in the dashboard detail panel).

Schedule: every 15 minutes.
No-op (exit 0, one log line) until APPLICATIONS_SHEET_ID is set.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.models import Application
from backend.onboarding import pipeline, schools, sheets

logger = logging.getLogger(__name__)

def _dashboard_url() -> str:
    return f"{get_settings().dashboard_base_url.rstrip('/')}/niltv-onboarding"

HEADER = [
    "ID", "Status", "First name", "Last name", "Email", "College email", "Phone",
    "School", "School as typed", "Sport", "Year", "Campus channel", "Roster link", "International",
    "Instagram", "IG followers", "TikTok", "TikTok followers", "YouTube", "YouTube subscribers", "Other followers",
    "Content type", "Purpose", "NIL deals done", "NIL deals wanted", "Best content",
    "Applied", "Approved", "Reviewed by", "Agreement", "Agreement sent",
    "Signed", "Stripe account", "Payouts enabled", "Stripe still needs", "Stripe link sent",
    "Accepted", "Declined reason", "Source", "Submissions", "Consent version", "Terms", "18+",
    "Notes", "Dashboard",
]

STATUS_ORDER = ["applicant", "approved", "agreement_sent", "signed", "stripe_pending", "accepted", "declined"]


def _d(dt: Optional[datetime]) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if dt else ""


def _row(a: Application) -> list[Any]:
    due = list(a.stripe_requirements_due or [])
    needs = ", ".join(dict.fromkeys(pipeline._humanize(d) for d in due))  # deduped, ordered
    if a.status == "accepted" and not due:
        needs = ""
    answers = a.answers or {}
    return [
        a.id,
        a.status,
        a.first_name or "",
        a.last_name or "",
        a.email,
        a.college_email or "",
        a.phone or "",
        a.university or "",
        answers.get("universityAsTyped") or "",
        a.sport or "",
        a.year or "",
        schools.CHANNEL_LABELS.get(a.campus_channel or "", a.campus_channel or ""),
        a.roster_link or "",
        "yes" if a.international else ("no" if a.international is False else ""),
        f"@{a.instagram}" if a.instagram else "",
        a.instagram_followers or "",
        f"@{a.tiktok}" if a.tiktok else "",
        a.tiktok_followers or "",
        a.youtube or "",
        a.youtube_subscribers or "",
        a.other_followers or "",
        a.content_type or "",
        a.purpose or "",
        a.nil_deals_done or "",
        a.nil_deals_wanted or "",
        answers.get("bestContent") or "",
        _d(a.created_at),
        _d(a.reviewed_at) if a.status != "declined" else "",
        a.reviewed_by or "",
        a.docusign_status or "",
        _d(a.agreement_sent_at),
        _d(a.signed_at),
        a.stripe_account_id or "",
        "yes" if a.stripe_payouts_enabled else ("no" if a.stripe_account_id else ""),
        needs,
        _d(a.stripe_link_sent_at),
        _d(a.accepted_at),
        a.decline_reason or "",
        a.source or "",
        a.submit_count or 1,
        a.consent_version or "",
        "yes" if a.consent_terms else "",
        "yes" if a.confirm_age else "",
        a.notes or "",
        f"{_dashboard_url()}?id={a.id}",
    ]


def export_applications(db: Session) -> int:
    s = get_settings()
    if not s.applications_sheet_id:
        logger.info("APPLICATIONS_SHEET_ID not set; nothing to export")
        return 0
    apps = db.query(Application).order_by(Application.created_at.desc().nullslast(), Application.id.desc()).all()
    rows = [_row(a) for a in apps]
    n = sheets.write_table(s.applications_sheet_id, "Applications", HEADER, rows)

    counts = {st: 0 for st in STATUS_ORDER}
    for a in apps:
        counts[a.status] = counts.get(a.status, 0) + 1
    summary = [[st.replace("_", " "), counts.get(st, 0)] for st in STATUS_ORDER]
    by_school: dict[str, int] = {}
    by_sport: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    for a in apps:
        if a.university:
            by_school[a.university] = by_school.get(a.university, 0) + 1
        if a.sport:
            by_sport[a.sport] = by_sport.get(a.sport, 0) + 1
        if a.campus_channel:
            label = schools.CHANNEL_LABELS.get(a.campus_channel, a.campus_channel)
            by_channel[label] = by_channel.get(label, 0) + 1
    summary += [["total athletes", len(apps)],
                ["open (not accepted/declined)", sum(1 for a in apps if a.status not in ("accepted", "declined"))],
                ["schools", len(by_school)],
                ["sports", len(by_sport)],
                ["campus channels", len(by_channel)],
                ["last refresh (UTC)", datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M")]]
    sheets.write_table(s.applications_sheet_id, "Summary", ["Status", "Count"], summary)
    sheets.write_table(s.applications_sheet_id, "By school", ["School", "Athletes"],
                       sorted(by_school.items(), key=lambda kv: (-kv[1], kv[0])))
    sheets.write_table(s.applications_sheet_id, "By sport", ["Sport", "Athletes"],
                       sorted(by_sport.items(), key=lambda kv: (-kv[1], kv[0])))
    sheets.write_table(s.applications_sheet_id, "By channel", ["Campus channel", "Athletes"],
                       sorted(by_channel.items(), key=lambda kv: (-kv[1], kv[0])))
    logger.info("exported %d applications to sheet %s", n, s.applications_sheet_id)
    return n


def main():
    db = SessionLocal()
    try:
        run_job("export_applications_sheet", db, export_applications, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
