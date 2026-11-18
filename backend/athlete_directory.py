"""One searchable list of athletes, merged from the three places they live.

Sources
  athletes      the Duke roster (TrueBlueTV), with measured Instagram data
  ambassadors   the NIL TV ambassador registry, with measured Instagram data
  applications  athlete signups from niltv.com, with self-reported numbers

Every row of the three tables becomes a node, and nodes that describe the same
athlete are joined into one person. Links, strongest first:

  1. applications.ambassador_id -> ambassadors.id
  2. ambassadors.athlete_id     -> athletes.id
  3. the same normalized Instagram handle on any of applications.instagram,
     ambassadors.ig_username (and previous_usernames) and athletes.ig_handle

A handle match never joins two different ambassadors or two different roster
athletes into one person: those are separate records on purpose, and the
foreign keys above already said who belongs with whom. Names alone never
link anything (two athletes can share a name).

Each person gets a stable key from its strongest record: ``amb-<id>`` if an
ambassador is in the group, else ``ath-<id>``, else ``app-<id>`` (the newest
application). ``resolve_key`` also accepts the key of any other record in the
group, so a link saved while someone was only an applicant keeps working after
they become an ambassador.

The tables hold hundreds to low thousands of rows, so the merge runs in
Python, and the result is reused until one of the source tables changes
(``build_directory``). tests/test_athlete_directory.py times both paths.

Contact fields (email, college email, phone) and free-text application answers
never leave this module in ``Person``; ``private_details`` returns them for
admin callers only.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.models import Ambassador, Application, Athlete, NiltvNetworkPost

SOURCES = ("athlete", "ambassador", "application")
STATUSES = ("ambassador_confirmed", "roster", "ambassador_candidate", "applicant")
SORTS = ("followers", "collab_views", "name", "newest")

# The athletes table is the Duke roster: its rows carry no school or campus.
ROSTER_SCHOOL = "Duke"
ROSTER_CAMPUS = "duke"

# ── Normalizers ───────────────────────────────────────────────────────────────

_IG_USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")
_IG_URL = re.compile(r"^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/+", re.I)
# Answers people type when they have no account. Never treated as a handle.
_NOT_A_HANDLE = {"none", "na", "n", "no", "nope", "null", "nil", "private", "instagram", "ig", "x", "tbd", "pending",
                 # Instagram page paths, in case one slips past the URL rules below.
                 "p", "reel", "reels", "tv", "stories", "explore", "accounts", "direct", "_u"}
# instagram.com/<word>/... pages that are not a profile. "_u/<name>" and
# "stories/<name>" carry the username in the next segment; the rest (a post,
# reel or video link) carry no username at all.
_IG_PREFIX_PATHS = {"_u", "stories"}
_IG_NON_PROFILE_PATHS = {"p", "reel", "reels", "tv", "explore", "accounts", "direct"}


def normalize_handle(raw: Optional[str]) -> Optional[str]:
    """Bare lowercase Instagram username, or None when the text is not one.

    Handles "@Jane", "jane.", "https://www.instagram.com/jane/?hl=en",
    "instagram.com/jane" and stray whitespace. A post, reel or video link has no username in it
    and gives None.
    """
    if not raw:
        return None
    s = raw.strip()
    m = _IG_URL.match(s)
    if m:
        parts = [x for x in re.split(r"[?#]", s[m.end():], maxsplit=1)[0].split("/") if x]
        if parts and parts[0].lower() in _IG_PREFIX_PATHS:
            parts = parts[1:]
        if not parts or parts[0].lower() in _IG_NON_PROFILE_PATHS:
            return None
        s = parts[0]
    s = s.strip().lstrip("@").rstrip("./").lower()
    if not s or s in _NOT_A_HANDLE or not _IG_USERNAME.match(s):
        return None
    return s


_NUM = r"(\d[\d,]*(?:\.\d+)?)"
# The suffix must end the word, so "500 maybe" is 500, not 500 million.
_SUFFIX = r"(k|m|thousand|million)?(?![a-z])"
_RANGE = re.compile(_NUM + r"\s*" + _SUFFIX + r"\s*(?:-|to|–)\s*" + _NUM + r"\s*" + _SUFFIX)
_SINGLE = re.compile(_NUM + r"\s*" + _SUFFIX)
_MULT = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}
_MAX_FOLLOWERS = 1_000_000_000


def _to_number(digits: str, suffix: Optional[str]) -> Optional[int]:
    digits = digits.replace(",", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    value *= _MULT.get(suffix or "", 1)
    n = int(round(value))
    return n if 0 <= n < _MAX_FOLLOWERS else None


def parse_follower_count(text: Optional[str]) -> Optional[int]:
    """Self-reported follower text to a number: "12.5k" -> 12500,
    "1,200" -> 1200, "1.2M" -> 1200000, "10-20k" -> 10000 (the low end).
    Anything without a number is None."""
    if not text:
        return None
    s = text.strip().lower().replace("+", "").replace("~", "")
    m = _RANGE.search(s)
    if m:
        low, low_suffix, _high, high_suffix = m.groups()
        return _to_number(low, low_suffix or high_suffix)
    m = _SINGLE.search(s)
    if not m:
        return None
    return _to_number(m.group(1), m.group(2))


def _clean(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = str(text).strip()
    return text or None


# ── Loading ───────────────────────────────────────────────────────────────────

_ATHLETE_COLS = (
    Athlete.id, Athlete.name, Athlete.sport, Athlete.year, Athlete.ig_handle,
    Athlete.tiktok_handle, Athlete.x_handle, Athlete.cached_ig_followers,
    Athlete.cached_last_pulled, Athlete.created_at,
)
_AMBASSADOR_COLS = (
    Ambassador.id, Ambassador.ig_username, Ambassador.display_name, Ambassador.previous_usernames,
    Ambassador.campus, Ambassador.school, Ambassador.sport, Ambassador.year, Ambassador.gender,
    Ambassador.profile_pic_url, Ambassador.status, Ambassador.athlete_id,
    Ambassador.cached_followers, Ambassador.cached_collab_posts, Ambassador.cached_collab_views,
    Ambassador.cached_collab_engagement, Ambassador.cached_last_pulled, Ambassador.created_at,
)
# No contact fields and no free-text answers: those are read per person by
# private_details(), for admins only.
_APPLICATION_COLS = (
    Application.id, Application.ambassador_id, Application.first_name, Application.last_name,
    Application.university, Application.sport, Application.year, Application.campus_channel,
    Application.instagram, Application.instagram_followers, Application.tiktok,
    Application.tiktok_followers, Application.youtube, Application.youtube_subscribers,
    Application.nil_deals_done, Application.nil_deals_wanted, Application.content_type,
    Application.consent_partners, Application.status, Application.created_at, Application.updated_at,
)


@dataclass
class Records:
    athletes: list[dict]
    ambassadors: list[dict]
    applications: list[dict]
    # Network posts not stamped with an ambassador, keyed by the poster's
    # lowercase handle: (posts, views, engagement).
    posts_by_handle: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    # Network posts stamped with an ambassador, keyed by ambassador id. Used
    # when an ambassador's cached_collab_* columns have not been computed yet.
    posts_by_ambassador: dict[int, tuple[int, int, int]] = field(default_factory=dict)


def _rows(db: Session, stmt) -> list[dict]:
    result = db.execute(stmt)
    keys = list(result.keys())
    return [dict(zip(keys, row)) for row in result.all()]


def load_records(db: Session) -> Records:
    """Every row the merge needs, in four queries. Inactive roster rows and
    removed or inactive ambassadors are left out."""
    athletes = _rows(db, select(*_ATHLETE_COLS).where(Athlete.active.is_(True)))
    ambassadors = _rows(db, select(*_AMBASSADOR_COLS)
                        .where(Ambassador.active.is_(True), Ambassador.status != "removed"))
    applications = _rows(db, select(*_APPLICATION_COLS))

    engagement = (func.coalesce(NiltvNetworkPost.likes, 0) + func.coalesce(NiltvNetworkPost.comments, 0)
                  + func.coalesce(NiltvNetworkPost.shares, 0) + func.coalesce(NiltvNetworkPost.saves, 0))
    handle = func.lower(NiltvNetworkPost.account_username)
    rows = db.execute(
        select(handle, func.count(), func.coalesce(func.sum(NiltvNetworkPost.views), 0),
               func.coalesce(func.sum(engagement), 0))
        .where(NiltvNetworkPost.ambassador_id.is_(None), NiltvNetworkPost.account_username.isnot(None))
        .group_by(handle)
    ).all()
    posts_by_handle = {h: (int(n), int(v), int(e)) for h, n, v, e in rows if h}
    rows = db.execute(
        select(NiltvNetworkPost.ambassador_id, func.count(),
               func.coalesce(func.sum(NiltvNetworkPost.views), 0), func.coalesce(func.sum(engagement), 0))
        .where(NiltvNetworkPost.ambassador_id.isnot(None))
        .group_by(NiltvNetworkPost.ambassador_id)
    ).all()
    posts_by_ambassador = {i: (int(n), int(v), int(e)) for i, n, v, e in rows}
    return Records(athletes, ambassadors, applications, posts_by_handle, posts_by_ambassador)


# ── Merge ─────────────────────────────────────────────────────────────────────

Node = tuple[str, int]  # ("ath" | "amb" | "app", id)


class _Groups:
    """Union-find over record nodes that refuses a soft (handle) join which
    would put two ambassadors or two roster athletes in one person."""

    def __init__(self, nodes: Iterable[Node]):
        self.parent: dict[Node, Node] = {}
        self.members: dict[Node, set[Node]] = {}
        for n in nodes:
            self.parent[n] = n
            self.members[n] = {n}

    def find(self, n: Node) -> Node:
        while self.parent[n] != n:
            self.parent[n] = self.parent[self.parent[n]]
            n = self.parent[n]
        return n

    def _kinds(self, root: Node, kind: str) -> set[int]:
        return {i for k, i in self.members[root] if k == kind}

    def union(self, a: Node, b: Node, *, soft: bool = False) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if soft:
            for kind in ("amb", "ath"):
                if self._kinds(ra, kind) and self._kinds(rb, kind):
                    return False
        if len(self.members[ra]) < len(self.members[rb]):
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.members[ra] |= self.members.pop(rb)
        return True

    def groups(self) -> list[set[Node]]:
        return list(self.members.values())


def _ambassador_handles(a: dict) -> list[str]:
    raw = [a.get("ig_username")] + (a.get("previous_usernames") or "").split(",")
    return [h for h in (normalize_handle(x) for x in raw) if h]


def merge(records: Records) -> list[dict]:
    """Join the records into people. Returns person dicts (see ``_person``).

    Each record's normalized handle is stored on it as ``_ig`` (ambassadors
    also get ``_igs``: current handle first, then previous ones) so the person
    builder does not redo the work."""
    ath = {r["id"]: r for r in records.athletes}
    amb = {r["id"]: r for r in records.ambassadors}
    app = {r["id"]: r for r in records.applications}
    for r in ath.values():
        r["_ig"] = normalize_handle(r.get("ig_handle"))
    for r in amb.values():
        r["_ig"] = normalize_handle(r.get("ig_username"))
        r["_igs"] = _ambassador_handles(r)
    for r in app.values():
        r["_ig"] = normalize_handle(r.get("instagram"))
    g = _Groups([("ath", i) for i in ath] + [("amb", i) for i in amb] + [("app", i) for i in app])

    # 1 + 2: the foreign keys staff or the pipeline already set.
    for r in app.values():
        if r.get("ambassador_id") in amb:
            g.union(("app", r["id"]), ("amb", r["ambassador_id"]))
    for r in amb.values():
        if r.get("athlete_id") in ath:
            g.union(("amb", r["id"]), ("ath", r["athlete_id"]))

    # 3: the same Instagram handle. Current handles first, so a handle someone
    # gave up and another athlete took is matched to its current owner.
    by_handle: dict[str, list[Node]] = {}
    for r in amb.values():
        if r["_ig"]:
            by_handle.setdefault(r["_ig"], []).append(("amb", r["id"]))
    for r in ath.values():
        if r["_ig"]:
            by_handle.setdefault(r["_ig"], []).append(("ath", r["id"]))
    for r in amb.values():
        for h in r["_igs"]:
            if h != r["_ig"]:
                by_handle.setdefault(h, []).append(("amb", r["id"]))
    for i in sorted(app):
        if app[i]["_ig"]:
            by_handle.setdefault(app[i]["_ig"], []).append(("app", i))
    for nodes in by_handle.values():
        first = nodes[0]
        for other in nodes[1:]:
            g.union(first, other, soft=True)

    people = []
    for members in g.groups():
        a_rows, m_rows, p_rows = [], [], []
        for kind, i in members:
            if kind == "ath":
                a_rows.append(ath[i])
            elif kind == "amb":
                m_rows.append(amb[i])
            else:
                p_rows.append(app[i])
        if len(a_rows) > 1:
            a_rows.sort(key=lambda r: r["id"])
        if len(m_rows) > 1:
            # A confirmed ambassador's row is the one staff keep up to date.
            m_rows.sort(key=lambda r: (r["status"] != "confirmed", r["id"]))
        if len(p_rows) > 1:
            p_rows.sort(key=_app_recency, reverse=True)
        people.append(_person(a_rows, m_rows, p_rows, records))
    return people


def _app_recency(r: dict) -> tuple:
    ts = r.get("updated_at") or r.get("created_at")
    return (ts.timestamp() if ts else 0, r["id"])


def _first_of(values: Iterable[Any]) -> Any:
    """First value that is not None or blank text (text comes back stripped)."""
    for v in values:
        if v.__class__ is str:
            v = v.strip() or None
        if v is not None:
            return v
    return None


def _first(*values: Any) -> Any:
    return _first_of(values)


_EMPTY: dict = {}


def _status(athletes: list[dict], ambassadors: list[dict]) -> str:
    if any(a["status"] == "confirmed" for a in ambassadors):
        return "ambassador_confirmed"
    if athletes:
        return "roster"
    if ambassadors:
        return "ambassador_candidate"
    return "applicant"


def _sum_known(values: Iterable[Optional[int]]) -> Optional[int]:
    """Sum of the known values, or None when none is known."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _collab_stats(ambassadors: list[dict], ig_handle: Optional[str],
                  records: Records) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(posts, views, engagement) of a person's NIL TV collabs. None means
    unknown, never zero.

    An ambassador's collabs are the posts stamped with their id: the cached
    columns when the precompute job has filled them, else counted live. Other
    people get the unstamped posts whose poster handle is theirs."""
    if ambassadors:
        rows = []
        for m in ambassadors:
            if m.get("cached_collab_posts") is not None:
                rows.append((m["cached_collab_posts"], m.get("cached_collab_views"),
                             m.get("cached_collab_engagement")))
            else:
                rows.append(records.posts_by_ambassador.get(m["id"], (0, None, None)))
        return (_sum_known(r[0] for r in rows), _sum_known(r[1] for r in rows),
                _sum_known(r[2] for r in rows))
    if ig_handle and ig_handle in records.posts_by_handle:
        return records.posts_by_handle[ig_handle]
    return 0, None, None


def _person(athletes: list[dict], ambassadors: list[dict], applications: list[dict],
            records: Records) -> dict:
    """One person from their records. Each list is already in priority order:
    athletes by id, ambassadors confirmed first, applications newest first."""
    a0 = athletes[0] if athletes else _EMPTY
    m0 = ambassadors[0] if ambassadors else _EMPTY
    p0 = applications[0] if applications else _EMPTY

    if m0:
        key = f"amb-{m0['id']}"
    elif a0:
        key = f"ath-{a0['id']}"
    else:
        key = f"app-{p0['id']}"
    member_keys = ([f"amb-{r['id']}" for r in ambassadors] + [f"ath-{r['id']}" for r in athletes]
                   + [f"app-{r['id']}" for r in applications])

    app_name = None
    if p0:
        app_name = " ".join(x for x in (_clean(p0.get("first_name")), _clean(p0.get("last_name"))) if x) or None
    ig_handle = m0.get("_ig") or a0.get("_ig") or _first_of(r["_ig"] for r in applications)

    # Followers: a measured count wins over a self-reported one; between two
    # measured counts, the newer pull wins.
    measured = [(m["cached_followers"], m.get("cached_last_pulled"), "ambassador")
                for m in ambassadors if m.get("cached_followers") is not None]
    measured += [(a["cached_ig_followers"], a.get("cached_last_pulled"), "roster")
                 for a in athletes if a.get("cached_ig_followers") is not None]
    followers = followers_as_of = followers_source = None
    self_reported = False
    if measured:
        if len(measured) > 1:
            measured.sort(key=lambda x: x[1].timestamp() if x[1] else 0, reverse=True)
        followers, followers_as_of, followers_source = measured[0]
    else:
        for r in applications:
            n = parse_follower_count(r.get("instagram_followers"))
            if n is not None:
                followers, followers_as_of = n, r.get("updated_at") or r.get("created_at")
                followers_source, self_reported = "application", True
                break

    collab_posts, collab_views, collab_engagement = _collab_stats(ambassadors, ig_handle, records)

    # Every Instagram handle on any of their records, the main one first. Used
    # to find their clips in the content library; not part of PersonOut.
    ig_handles = list(dict.fromkeys(h for h in (
        ig_handle, *(h for m in ambassadors for h in m.get("_igs", ())),
        *(r.get("_ig") for r in (*athletes, *applications))) if h))

    created = [r.get("created_at") for r in (*athletes, *ambassadors, *applications) if r.get("created_at")]
    pulled = [r.get("cached_last_pulled") for r in (*athletes, *ambassadors) if r.get("cached_last_pulled")]
    app_dates = [r.get("created_at") for r in applications if r.get("created_at")]

    return {
        "key": key,
        "member_keys": member_keys,
        "sources": [s for s, rows in (("athlete", athletes), ("ambassador", ambassadors),
                                      ("application", applications)) if rows],
        "athlete_ids": [r["id"] for r in athletes],
        "ambassador_ids": [r["id"] for r in ambassadors],
        "application_ids": [r["id"] for r in applications],
        "display_name": _first(a0.get("name"), m0.get("display_name"), app_name,
                               ig_handle and f"@{ig_handle}") or key,
        "sport": _first(a0.get("sport"), m0.get("sport"), p0.get("sport")),
        "school": _first(m0.get("school"), p0.get("university"), ROSTER_SCHOOL if athletes else None),
        "year": _first(a0.get("year"), m0.get("year"), p0.get("year")),
        "campus": _first(m0.get("campus"), p0.get("campus_channel"), ROSTER_CAMPUS if athletes else None),
        "gender": _first(m0.get("gender")),
        "status": _status(athletes, ambassadors),
        "application_status": _clean(p0.get("status")),
        "ig_handle": ig_handle,
        "ig_handles": ig_handles,
        "followers": followers,
        "followers_source": followers_source,
        "followers_as_of": followers_as_of,
        "followers_self_reported": self_reported,
        "tiktok_handle": _first_of((a0.get("tiktok_handle"), *(r.get("tiktok") for r in applications))),
        "tiktok_followers": _first_of(parse_follower_count(r.get("tiktok_followers")) for r in applications),
        "youtube_handle": _first_of(r.get("youtube") for r in applications),
        "youtube_subscribers": _first_of(parse_follower_count(r.get("youtube_subscribers"))
                                         for r in applications),
        "x_handle": _first(a0.get("x_handle")),
        "profile_pic_url": _first_of(m.get("profile_pic_url") for m in ambassadors),
        "nil_deals_done": _first(p0.get("nil_deals_done")),
        "nil_deals_wanted": _first(p0.get("nil_deals_wanted")),
        "content_type": _first(p0.get("content_type")),
        "partner_consent": p0.get("consent_partners") if applications else None,
        "applied_at": min(app_dates) if app_dates else None,
        "first_seen": min(created) if created else None,
        "collab_posts": collab_posts,
        "collab_views": collab_views,
        "collab_engagement": collab_engagement,
        "last_pulled": max(pulled) if pulled else None,
    }


# The merged list is reused while the source tables are unchanged. The
# fingerprint is each table's row count and the sum of its rows' xmin (the id
# of the transaction that last wrote the row), so any insert, update or delete
# changes it. One indexless pass over a few thousand rows costs a couple of
# milliseconds. The TTL is a backstop. Callers must not mutate the people.
CACHE_TTL_SECONDS = 300
_FINGERPRINT = text("""
    SELECT (SELECT count(*) || ':' || coalesce(sum(xmin::text::bigint), 0) FROM athletes),
           (SELECT count(*) || ':' || coalesce(sum(xmin::text::bigint), 0) FROM ambassadors),
           (SELECT count(*) || ':' || coalesce(sum(xmin::text::bigint), 0) FROM applications),
           (SELECT count(*) || ':' || coalesce(sum(xmin::text::bigint), 0) FROM niltv_network_posts)
""")
_cache_lock = threading.Lock()
_cache: Optional[tuple[tuple, float, list[dict]]] = None


def build_directory(db: Session) -> list[dict]:
    """Every person, merged. Served from the per-process cache when the
    source tables have not changed since the last build."""
    global _cache
    fingerprint = tuple(db.execute(_FINGERPRINT).one())
    with _cache_lock:
        if _cache and _cache[0] == fingerprint and time.monotonic() - _cache[1] < CACHE_TTL_SECONDS:
            return _cache[2]
    people = merge(load_records(db))
    with _cache_lock:
        _cache = (fingerprint, time.monotonic(), people)
    return people


def clear_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def resolve_key(people: list[dict], key: str) -> Optional[dict]:
    """The person whose key, or any of whose record keys, is ``key``."""
    for p in people:
        if p["key"] == key or key in p["member_keys"]:
            return p
    return None


def keys_by_handle(people: list[dict]) -> dict[str, str]:
    """Normalized Instagram handle -> person key. A person's main handle wins
    over a handle someone else used before (a previous username or an old
    signup), so a handle that changed owners points at its current owner."""
    out: dict[str, str] = {}
    for p in people:
        if p["ig_handle"]:
            out.setdefault(p["ig_handle"], p["key"])
    for p in people:
        for h in p.get("ig_handles", ()):
            out.setdefault(h, p["key"])
    return out


# ── Search, filters, sort ─────────────────────────────────────────────────────


@dataclass
class Query:
    q: Optional[str] = None
    sport: Optional[str] = None
    school: Optional[str] = None
    campus: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    partner_consent: Optional[bool] = None
    min_followers: Optional[int] = None
    max_followers: Optional[int] = None
    has_content: Optional[bool] = None
    sort: str = "followers"

    def as_dict(self) -> dict:
        return asdict(self)


def _fold(s: Optional[str]) -> str:
    return (s or "").strip().casefold()


def _matches(p: dict, f: Query) -> bool:
    if f.q:
        needle = _fold(f.q).lstrip("@")
        hay = " ".join(_fold(p.get(k)) for k in (
            "display_name", "ig_handle", "tiktok_handle", "youtube_handle", "x_handle",
            "school", "sport", "campus"))
        if not all(term in hay for term in needle.split()):
            return False
    for name in ("sport", "school", "campus"):
        want = getattr(f, name)
        if want and _fold(p.get(name)) != _fold(want):
            return False
    if f.status and p["status"] != f.status:
        return False
    if f.source and f.source not in p["sources"]:
        return False
    if f.partner_consent is not None and (p["partner_consent"] is True) != f.partner_consent:
        return False
    if f.min_followers is not None and (p["followers"] is None or p["followers"] < f.min_followers):
        return False
    if f.max_followers is not None and (p["followers"] is None or p["followers"] > f.max_followers):
        return False
    if f.has_content is not None and ((p["collab_posts"] or 0) > 0) != f.has_content:
        return False
    return True


def _ts(v: Optional[datetime]) -> float:
    return v.timestamp() if v else float("-inf")


def apply(people: list[dict], f: Query) -> list[dict]:
    """Filter and sort. Missing numbers sort last; ties go by name."""
    out = [p for p in people if _matches(p, f)]
    by_name = lambda p: (_fold(p["display_name"]), p["key"])  # noqa: E731
    out.sort(key=by_name)
    if f.sort == "followers":
        out.sort(key=lambda p: -(p["followers"] if p["followers"] is not None else -1))
    elif f.sort == "collab_views":
        out.sort(key=lambda p: -(p["collab_views"] if p["collab_views"] is not None else -1))
    elif f.sort == "newest":
        out.sort(key=lambda p: _ts(p["first_seen"]), reverse=True)
    return out


def facets(people: list[dict]) -> dict[str, list[dict]]:
    """Distinct sports, schools, campuses and statuses with counts, most
    common first. Values that differ only in case count as one."""
    out: dict[str, list[dict]] = {}
    for name in ("sport", "school", "campus", "status"):
        counts: dict[str, list] = {}
        for p in people:
            v = _clean(p.get(name))
            if not v:
                continue
            slot = counts.setdefault(v.casefold(), [v, 0])
            slot[1] += 1
        out[name] = [{"value": v, "count": n}
                     for v, n in sorted(counts.values(), key=lambda x: (-x[1], x[0].casefold()))]
    return out


# ── Per-person extras (detail page) ───────────────────────────────────────────


def private_details(db: Session, person: dict) -> list[dict]:
    """Contact fields and application answers, newest application first.
    Admin callers only: the router decides, this only reads."""
    ids = person["application_ids"]
    if not ids:
        return []
    rows = db.query(Application).filter(Application.id.in_(ids)).all()
    rows.sort(key=lambda r: ids.index(r.id))
    return [{
        "application_id": r.id,
        "email": r.email,
        "college_email": r.college_email,
        "phone": r.phone,
        "first_name": r.first_name,
        "last_name": r.last_name,
        "status": r.status,
        "submitted_at": r.created_at,
        "updated_at": r.updated_at,
        "roster_link": r.roster_link,
        "international": r.international,
        "instagram": r.instagram,
        "instagram_followers": r.instagram_followers,
        "tiktok": r.tiktok,
        "tiktok_followers": r.tiktok_followers,
        "youtube": r.youtube,
        "youtube_subscribers": r.youtube_subscribers,
        "other_followers": r.other_followers,
        "purpose": r.purpose,
        "description": r.description,
        "answers": r.answers,
        "consent_program_email": r.consent_program_email,
        "consent_sms": r.consent_sms,
        "consent_marketing": r.consent_marketing,
        "consent_partners": r.consent_partners,
        "consent_at": r.consent_at,
    } for r in rows]


def contacts_by_application(db: Session, application_ids: list[int]) -> dict[int, dict]:
    """Email, college email and phone per application id (CSV export, admins only)."""
    if not application_ids:
        return {}
    rows = db.query(Application.id, Application.email, Application.college_email, Application.phone) \
        .filter(Application.id.in_(application_ids)).all()
    return {r.id: {"email": r.email, "college_email": r.college_email, "phone": r.phone} for r in rows}
