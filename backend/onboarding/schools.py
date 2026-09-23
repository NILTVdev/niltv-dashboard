"""Canonical school names (spelling guard) + campus channel slugs.

Schools come from the federal IPEDS institution list bundled as
``schools.json`` beside this module (the same file the signup form searches). ``canonical``
maps whatever an athlete typed ("Duke", "UNC chapel hill", "Baylor ") to the
official name; anything it cannot match is returned as typed so nothing is
lost, with ``matched=False`` so the dashboard can show it for review.
"""

from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA = Path(__file__).parent / "schools.json"

# Hand aliases for the way athletes actually write schools. Keys are normalized.
ALIASES = {
    "duke": "Duke University",
    "unc": "University of North Carolina at Chapel Hill",
    "unc chapel hill": "University of North Carolina at Chapel Hill",
    "university of north carolina": "University of North Carolina at Chapel Hill",
    "north carolina": "University of North Carolina at Chapel Hill",
    "nc state": "North Carolina State University at Raleigh",
    "ncsu": "North Carolina State University at Raleigh",
    "north carolina state university": "North Carolina State University at Raleigh",
    "baylor": "Baylor University",
    "vanderbilt": "Vanderbilt University",
    "vandy": "Vanderbilt University",
    "syracuse": "Syracuse University",
    "notre dame": "University of Notre Dame",
    "wake forest": "Wake Forest University",
    "texas a&m": "Texas A&M University-College Station",
    "texas a&m university": "Texas A&M University-College Station",
    "texas university a&m": "Texas A&M University-College Station",
    "tamu": "Texas A&M University-College Station",
    "mississippi state": "Mississippi State University",
    "arizona state": "Arizona State University Campus Immersion",
    "arizona state university": "Arizona State University Campus Immersion",
    "asu": "Arizona State University Campus Immersion",
    "ucla": "University of California-Los Angeles",
    "ucf": "University of Central Florida",
    "university of central florida big 12": "University of Central Florida",
    "tcu": "Texas Christian University",
    "temple": "Temple University",
    "illinois": "University of Illinois Urbana-Champaign",
    "university of illinois urbana champaign": "University of Illinois Urbana-Champaign",
    "auburn": "Auburn University",
    "texas state": "Texas State University",
    "texas tech": "Texas Tech University",
    "michigan state": "Michigan State University",
    "penn state": "Pennsylvania State University-Main Campus",
    "penn state university": "Pennsylvania State University-Main Campus",
    "university of michigan": "University of Michigan-Ann Arbor",
    "university of wisconsin": "University of Wisconsin-Madison",
    "university of wisconsin madison": "University of Wisconsin-Madison",
    "university of alabama": "The University of Alabama",
    "university of tennessee": "The University of Tennessee-Knoxville",
    "university of miami": "University of Miami",
    "university of missouri mizzou": "University of Missouri-Columbia",
    "university of missouri": "University of Missouri-Columbia",
    "university of pittsburgh": "University of Pittsburgh-Pittsburgh Campus",
    "ottawa university": "Ottawa University-Kansas City",
    "the college of william and mary": "William & Mary",
    "college of william and mary": "William & Mary",
    "univ of alaska anchorage": "University of Alaska Anchorage",
    "the citadel": "Citadel Military College of South Carolina",
    "umass lowell": "University of Massachusetts-Lowell",
    "univeristy of louisville": "University of Louisville",
    "university of toldeo": "University of Toledo",
    "lindsey wilson university": "Lindsey Wilson College",
    "dallas college brookhaven": "Dallas College",
    "morehead state": "Morehead State University",
    "north carolina a&t": "North Carolina A & T State University",
    "suny purchase": "SUNY at Purchase College",
    "university of cincinnati": "University of Cincinnati-Main Campus",
    "wingate": "Wingate University",
    "citadel shenandoah university": "Citadel Military College of South Carolina",
}

CHANNEL_SLUGS = {
    "truebluetv": "truebluetv", "true blue tv": "truebluetv", "trueblue tv": "truebluetv",
    "chapelhilltv": "chapelhilltv", "chapel hill tv": "chapelhilltv",
    "redpacktv": "redpacktv", "red pack tv": "redpacktv",
    "dorecitytv": "dorecitytv", "dore city tv": "dorecitytv",
    "starkvilletv": "starkvilletv", "starkville tv": "starkvilletv",
    "collegestationtv": "collegestationtv", "college station tv": "collegestationtv",
    "brazostv": "brazostv", "brazos tv": "brazostv",
    "goldendometv": "goldendometv", "golden dome tv": "goldendometv",
    "goldsalemtv": "goldsalemtv", "gold salem tv": "goldsalemtv",
    "saltcitytv": "saltcitytv", "salt city tv": "saltcitytv",
}
CHANNEL_BY_SCHOOL = {
    "Duke University": "truebluetv",
    "University of North Carolina at Chapel Hill": "chapelhilltv",
    "North Carolina State University at Raleigh": "redpacktv",
    "Vanderbilt University": "dorecitytv",
    "Mississippi State University": "starkvilletv",
    "Texas A&M University-College Station": "collegestationtv",
    "Baylor University": "brazostv",
    "University of Notre Dame": "goldendometv",
    "Wake Forest University": "goldsalemtv",
    "Syracuse University": "saltcitytv",
}
CHANNEL_LABELS = {
    "truebluetv": "TrueBlue TV", "chapelhilltv": "Chapel Hill TV", "redpacktv": "Red Pack TV",
    "dorecitytv": "Dore City TV", "starkvilletv": "Starkville TV", "collegestationtv": "College Station TV",
    "brazostv": "Brazos TV", "goldendometv": "Golden Dome TV", "goldsalemtv": "Gold Salem TV",
    "saltcitytv": "Salt City TV", "other": "Other",
}


def _norm(v: str) -> str:
    v = (v or "").lower().replace("&amp;", "&").replace(" and ", " & ")
    v = re.sub(r"\(.*?\)", " ", v)
    v = re.sub(r"[^a-z0-9& ]+", " ", v)
    v = re.sub(r"\b(the)\b", " ", v)
    return re.sub(r"\s+", " ", v).strip()


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, str], list[str], dict[str, str]]:
    """(normalized name -> official, [normalized names], official -> domain)"""
    try:
        rows = json.loads(DATA.read_text(encoding="utf-8"))
    except OSError:
        rows = []
    by_norm: dict[str, str] = {}
    domains: dict[str, str] = {}
    for r in rows:
        by_norm.setdefault(_norm(r["n"]), r["n"])
        domains[r["n"]] = r.get("d", "")
        for alias in (r.get("a") or "").split("|"):
            if alias.strip():
                by_norm.setdefault(_norm(alias), r["n"])
    for alias, official in ALIASES.items():
        by_norm[_norm(alias)] = official
    return by_norm, list(by_norm), domains


def canonical(name: Optional[str]) -> tuple[str, bool]:
    """(canonical name, matched). Unmatched input comes back trimmed, as typed."""
    raw = (name or "").strip()
    if not raw:
        return "", False
    by_norm, keys, _ = _index()
    n = _norm(raw)
    if n in by_norm:
        return by_norm[n], True
    # "X University" <-> "University of X" style misses: try dropping generic words
    stripped = re.sub(r"\b(university|college|of|at)\b", " ", n)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped and stripped in by_norm:
        return by_norm[stripped], True
    close = difflib.get_close_matches(n, keys, n=1, cutoff=0.92)
    if close:
        return by_norm[close[0]], True
    return raw, False


def domain_for(canonical_name: str) -> str:
    return _index()[2].get(canonical_name, "")


def channel_slug(value: Optional[str], school: Optional[str] = None) -> str:
    """Form value (slug or old label) -> channel slug; falls back to the school."""
    v = (value or "").strip().lower()
    if v:
        base = re.sub(r"\(.*?\)", "", v).replace("&amp;", "&").strip()
        if base in CHANNEL_SLUGS:
            return CHANNEL_SLUGS[base]
        if v in ("other", "not listed") or v.startswith("not listed"):
            return "other"
    if school:
        return CHANNEL_BY_SCHOOL.get(school, "")
    return "other" if v else ""
