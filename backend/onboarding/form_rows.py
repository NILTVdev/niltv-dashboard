"""Map Google Form response rows (any of the form versions) to the intake payload.

The responses spreadsheet has several tabs from three generations of the
form, with different headers ("Email Address" vs "personal email", "IG link"
vs "Insta", one Name column vs First/Last ...). Columns are matched by
keyword so every generation lands in the same intake fields the website form
posts. Pure functions, no I/O, so the mapping is unit-testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

# ordered (form key, [header keywords that identify the column]).
# First matching rule per header wins; a header matches a rule when every
# keyword group has a hit (groups are "any of" lists).
_RULES: list[tuple[str, list[list[str]]]] = [
    ("submittedAt", [["timestamp"]]),
    ("personalEmail", [["personal email"]]),
    ("accountEmail", [["email address"]]),
    ("collegeEmail", [["college email", "school email"]]),
    ("email", [["email"]]),                       # generic "Email" column (after the specific ones)
    ("phone", [["phone"]]),
    ("firstName", [["first name"]]),
    ("lastName", [["last name"]]),
    ("fullName", [["name"]]),
    ("campusChannel", [["channel"]]),             # "Does your college also have a channel? ..."
    ("international", [["international"]]),
    ("rosterLink", [["roster"]]),
    ("university", [["university", "school"]]),
    ("sport", [["sport"]]),
    ("year", [["year"]]),
    ("bestContent", [["best content"]]),
    ("instagramFollowers", [["insta", "instagram"], ["follower"]]),
    ("instagram", [["ig link", "insta", "instagram"]]),
    ("tiktokFollowers", [["tiktok", "tt "], ["follower"]]),
    ("tiktok", [["tiktok"]]),
    ("youtubeSubscribers", [["youtube", "yt "], ["subscriber", "follow"]]),
    ("youtube", [["youtube", "yt "]]),
    ("linkedin", [["linkedin"]]),
    ("facebook", [["facebook"]]),
    ("otherFollowers", [["other platform"]]),
    ("contentType", [["type of content", "content category"]]),
    ("purpose", [["goal", "purpose"]]),
    ("nilDealsDone", [["nil deal"]]),
    ("nilDealsWanted", [["companies", "partner with"]]),
]

_SKIP_TAB_WORDS = ("roster", "summary", "contact", "channel")


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.replace("\\", "").strip().lower())


def map_header(header: list[str], rows: Optional[list[list[str]]] = None) -> dict[int, str]:
    """column index -> form key, for the columns we understand.

    ``rows`` (a few data rows) lets a timestamp column with a BLANK header be
    recognised by its values: one generation of the form sheet lost the
    "Timestamp" label but every row still starts with the submission time."""
    out: dict[int, str] = {}
    taken: set[str] = set()
    for idx, raw in enumerate(header):
        h = _norm(raw)
        if not h:
            continue
        for key, groups in _RULES:
            if key in taken:
                continue
            if all(any(kw in h for kw in group) for group in groups):
                out[idx] = key
                taken.add(key)
                break
    if "submittedAt" not in taken and rows:
        width = max(len(header), max((len(r) for r in rows), default=0))
        for idx in range(width):
            if idx < len(header) and header[idx].strip():
                continue
            vals = [str(r[idx]).strip() for r in rows if idx < len(r) and str(r[idx]).strip()]
            if vals and sum(1 for v in vals if parse_timestamp(v)) >= max(1, len(vals) * 0.8):
                out[idx] = "submittedAt"
                break
    return out


def is_form_tab(header: list[str], rows: Optional[list[list[str]]] = None) -> bool:
    """A responses tab has a Timestamp column and some email column."""
    keys = set(map_header(header, rows).values())
    return "submittedAt" in keys and bool(keys & {"email", "personalEmail", "accountEmail", "collegeEmail"})


def parse_timestamp(value: str) -> Optional[datetime]:
    """'6/4/2026 16:09:36' (Sheets US format) or ISO. Naive -> UTC."""
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _email(v: Any) -> str:
    v = str(v or "").strip().lower()
    return v if "@" in v and " " not in v else ""


def split_name(full: str) -> tuple[str, str]:
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def row_to_payload(header: list[str], row: list[str], tab: str = "",
                   cmap: Optional[dict[int, str]] = None) -> Optional[dict]:
    """One sheet row -> the flat payload ``pipeline.intake`` expects, or None
    when there is no usable email. Unknown-but-present columns are kept under
    ``extra`` so nothing the athlete wrote is lost (it lands in answers).
    Pass ``cmap`` from ``map_header(header, rows)`` when the header is partial."""
    cmap = cmap if cmap is not None else map_header(header)
    vals: dict[str, str] = {}
    extra: dict[str, str] = {}
    for idx, cell in enumerate(row):
        cell = str(cell or "").strip()
        if not cell:
            continue
        key = cmap.get(idx)
        if key:
            vals[key] = cell
        elif idx < len(header) and header[idx].strip():
            extra[header[idx].strip()] = cell

    personal = _email(vals.get("personalEmail")) or _email(vals.get("accountEmail"))
    generic = _email(vals.get("email"))
    college = _email(vals.get("collegeEmail"))
    if not college and generic and generic.endswith(".edu"):
        college = generic
    email = personal or (generic if generic != college else "") or college
    if not email:
        return None

    first, last = vals.get("firstName", ""), vals.get("lastName", "")
    if not first and vals.get("fullName"):
        first, last = split_name(vals["fullName"])

    payload: dict[str, Any] = {
        "email": email,
        "collegeEmail": college or None,
        "phone": vals.get("phone"),
        "firstName": first or None,
        "lastName": last or None,
        "university": vals.get("university"),
        "sport": vals.get("sport"),
        "year": vals.get("year"),
        "instagram": vals.get("instagram"),
        "instagramFollowers": vals.get("instagramFollowers"),
        "tiktok": vals.get("tiktok"),
        "tiktokFollowers": vals.get("tiktokFollowers"),
        "youtube": vals.get("youtube"),
        "youtubeSubscribers": vals.get("youtubeSubscribers"),
        "otherFollowers": vals.get("otherFollowers"),
        "contentType": vals.get("contentType"),
        "purpose": vals.get("purpose"),
        "nilDealsDone": vals.get("nilDealsDone"),
        "nilDealsWanted": vals.get("nilDealsWanted"),
        "campusChannel": vals.get("campusChannel"),
        "international": vals.get("international"),
        "rosterLink": vals.get("rosterLink"),
        "bestContent": vals.get("bestContent"),
        "linkedin": vals.get("linkedin"),
        "facebook": vals.get("facebook"),
        "submittedAt": vals.get("submittedAt"),
        "source": "google-form",
        "formTab": tab,
        "consentVersion": "google-form-legacy",   # the Google Form had no consent block
    }
    if extra:
        payload["extra"] = extra
    return {k: v for k, v in payload.items() if v not in (None, "")}
