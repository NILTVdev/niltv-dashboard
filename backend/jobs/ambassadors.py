"""
Ambassador passes: welcome-post discovery, collab attribution, campus inference.

Ambassadors enter the registry two ways:
  1. The welcome parser scans @niltv brand_posts captions for the
     "welcome our new ambassador @x" announcements. Exactly one external
     @mention auto-confirms the ambassador; zero or several mentions create
     status='candidate' rows for review on the admin page.
  2. The admin endpoints (backend/routers/ambassadors.py) add, confirm,
     remove, or edit rows by hand. status='removed' is final for ingest —
     the parser never resurrects a removed row.

The attribution pass stamps ambassador_id onto niltv_network_posts and
the network table by matching the post's account_username (the original
poster, captured inline by the collab fetch) against the registry. Campus
is then inferred from which of OUR channels carried the post
(collab_accounts -> brand_accounts.campus); a manually set campus always wins.

Every entry point used by the cron jobs is wrapped by run_ambassador_passes /
run_welcome_scan, which catch and log instead of raising — media and
thumbnail ingestion for the app must never be interrupted by ambassador
bookkeeping.

All scans are full-table and idempotent: re-running is always safe, there is
no incremental state to lose.
"""

import logging
import random
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    BrandAccount,
    BrandPost,
    NiltvNetworkPost,
)

logger = logging.getLogger(__name__)

# Re-check inaccessible (personal) accounts after 7 days — same convention
# as the athlete pull; they may switch to a Business/Creator account.
RECHECK_DAYS = 7

# Accounts whose posts are scanned for welcome announcements. Campus channels
# can be added here once they start announcing their own ambassadors.
ANNOUNCE_ACCOUNTS = ("niltv",)

# "welcome ... ambassador" in either order, up to 80 chars apart — covers
# "Welcome our newest NILTV ambassador @x" as well as "Our new ambassador
# @x — welcome to the family". Deliberately requires both words: a caption
# that merely says "welcome" (game hype) or "ambassador" (bio credit) alone
# never matches.
WELCOME_RE = re.compile(
    r"welcom\w*\b.{0,80}?\bambassador|ambassador\w*\b.{0,80}?\bwelcom",
    re.IGNORECASE | re.DOTALL,
)

# IG usernames: letters, digits, underscore, period (max 30 chars). Trailing
# periods are sentence punctuation, not part of the handle.
MENTION_RE = re.compile(r"@([A-Za-z0-9._]{1,30})")


def normalize_username(handle: str | None) -> str:
    """Lowercased bare username: no @, no whitespace, no trailing periods."""
    if not handle:
        return ""
    return handle.strip().lstrip("@").rstrip(".").lower()


def extract_mentions(caption: str | None) -> list[str]:
    """Normalized @mentions in caption order, deduped."""
    if not caption:
        return []
    seen: set[str] = set()
    mentions: list[str] = []
    for m in MENTION_RE.findall(caption):
        handle = normalize_username(m)
        if handle and handle not in seen:
            seen.add(handle)
            mentions.append(handle)
    return mentions


def owned_usernames(db: Session) -> set[str]:
    """Handles that belong to US — never ambassador candidates. Union of the
    registry rows (account + username) and the legacy .env account names, so
    a welcome caption that also tags @niltv or a campus channel still counts
    as a single-mention announcement."""
    owned: set[str] = set()
    for row in db.query(BrandAccount.account, BrandAccount.username).all():
        for value in row:
            handle = normalize_username(value)
            if handle:
                owned.add(handle)
    try:
        for target in get_settings().brand_ig_targets():
            handle = normalize_username(target.get("account"))
            if handle:
                owned.add(handle)
    except Exception as e:  # settings should never break a scan
        logger.warning(f"Could not read env brand targets for owned-handle set: {e}")
    return owned


def _upsert_ambassador(
    db: Session,
    username: str,
    status: str,
    post: BrandPost,
    counts: Counter,
) -> None:
    """Create or promote one ambassador row from a welcome announcement."""
    now = datetime.now(tz=timezone.utc)
    existing = db.query(Ambassador).filter(Ambassador.ig_username == username).first()

    if existing is None:
        db.add(Ambassador(
            ig_username=username,
            status=status,
            source="welcome_post",
            welcome_post_id=post.ig_post_id,
            announced_at=post.posted_at,
        ))
        counts["created_confirmed" if status == "confirmed" else "created_candidates"] += 1
        return

    if existing.status == "removed":
        # Admin removal is final for ingest; only the admin page re-adds.
        counts["skipped_removed"] += 1
        return

    changed = False
    if existing.status == "candidate" and status == "confirmed":
        # A clean single-mention announcement settles an earlier ambiguous one.
        existing.status = "confirmed"
        counts["promoted"] += 1
        changed = True
    if not existing.welcome_post_id:
        existing.welcome_post_id = post.ig_post_id
        existing.announced_at = post.posted_at
        existing.source = existing.source or "welcome_post"
        changed = True
    if changed:
        existing.updated_at = now


def scan_welcome_posts(db: Session, accounts: tuple[str, ...] = ANNOUNCE_ACCOUNTS) -> dict:
    """Scan announce-account captions for welcome posts and upsert ambassadors.

    Exactly one external mention -> confirmed; several -> each becomes a
    candidate for the admin queue; zero -> logged, nothing created. Full
    rescan every run — upserts make it idempotent, and a night where the
    parser was broken self-heals on the next one.
    """
    counts: Counter = Counter()
    owned = owned_usernames(db)

    posts = (
        db.query(BrandPost)
        .filter(BrandPost.account.in_(accounts), BrandPost.caption.isnot(None))
        .order_by(BrandPost.posted_at.asc().nullslast())
        .all()
    )

    for post in posts:
        if not WELCOME_RE.search(post.caption or ""):
            continue
        counts["welcome_posts"] += 1
        mentions = [m for m in extract_mentions(post.caption) if m not in owned]

        if not mentions:
            counts["no_mention"] += 1
            logger.warning(
                f"Welcome post {post.ig_post_id} has no external @mention — "
                f"needs a manual add: {(post.caption or '')[:80]!r}"
            )
            continue

        status = "confirmed" if len(mentions) == 1 else "candidate"
        for username in mentions:
            _upsert_ambassador(db, username, status, post, counts)

    db.commit()
    if counts:
        logger.info(f"Welcome scan: {dict(counts)}")
    return dict(counts)


def attribute_posts(db: Session) -> int:
    """Stamp ambassador_id on unattributed network posts.

    Matches lowercased account_username against non-removed ambassadors.
    Already-attributed posts are left alone, so a handle rename never
    re-writes history. Returns the number of rows stamped.
    """
    registry = {
        a.ig_username: a.id
        for a in db.query(Ambassador)
        .filter(Ambassador.status != "removed", Ambassador.ig_username.isnot(None))
        .all()
    }
    if not registry:
        return 0

    stamped = 0
    for model in (NiltvNetworkPost,):
        rows = (
            db.query(model)
            .filter(model.ambassador_id.is_(None), model.account_username.isnot(None))
            .all()
        )
        for row in rows:
            ambassador_id = registry.get(normalize_username(row.account_username))
            if ambassador_id is not None:
                row.ambassador_id = ambassador_id
                stamped += 1

    db.commit()
    if stamped:
        logger.info(f"Attribution: stamped ambassador_id on {stamped} network posts")
    return stamped


# School names as they appear on the Campus Ambassadors sheet (free text,
# typed by the athletes) -> brand_accounts.campus keys. Lowercased substring
# match; only campuses that exist in the registry are ever assigned, so an
# entry here for a node that has no channel yet is inert until the channel
# is onboarded with that campus key.
CAMPUS_SCHOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "arizona-state": ("arizona state",),
    "baylor": ("baylor",),
    "duke": ("duke",),
    "mississippi-state": ("mississippi state",),
    "nc-state": ("nc state", "north carolina state"),
    "notre-dame": ("notre dame",),
    "stanford": ("stanford",),
    "syracuse": ("syracuse",),
    "texas-am": ("texas a&m", "texas university a&m", "texas a & m", "texas am"),
    "unc": ("unc chapel hill", "unc-chapel hill", "north carolina at chapel hill", "unc chapel-hill"),
    "vanderbilt": ("vanderbilt",),
}


def campus_from_school(school: str | None, known_campuses: set[str]) -> str | None:
    """Map a sheet-style school name onto one of OUR campus nodes, or None.
    'University of Louisville' -> None (no channel); 'Baylor University' -> 'baylor'."""
    text = (school or "").strip().lower()
    if not text:
        return None
    for campus, aliases in CAMPUS_SCHOOL_ALIASES.items():
        if campus in known_campuses and any(alias in text for alias in aliases):
            return campus
    return None


def infer_campuses(db: Session) -> int:
    """Fill in campus for ambassadors that lack one.

    First from their posts: the carrying channels live in collab_accounts (our
    account names) and map to brand_accounts.campus; most-frequent campus wins,
    alphabetical on ties for determinism. An ambassador with no carried posts
    (most of the roster: the sheet import fills `school` but only ~1 in 4 sits
    at a school with a channel) falls back to the school name via
    CAMPUS_SCHOOL_ALIASES. Rows with campus_source='manual' are never touched,
    and inference never overwrites an existing campus. Returns rows updated.
    """
    account_campus = {
        normalize_username(acct): campus
        for acct, campus in db.query(BrandAccount.account, BrandAccount.campus).all()
        if campus
    }
    if not account_campus:
        return 0
    known_campuses = set(account_campus.values())

    pending = (
        db.query(Ambassador)
        .filter(
            Ambassador.campus.is_(None),
            Ambassador.campus_source == "inferred",
            Ambassador.status != "removed",
        )
        .all()
    )
    if not pending:
        return 0

    now = datetime.now(tz=timezone.utc)
    updated = 0
    for ambassador in pending:
        votes: Counter = Counter()
        posts = (
            db.query(NiltvNetworkPost.collab_accounts)
            .filter(NiltvNetworkPost.ambassador_id == ambassador.id)
            .all()
        )
        for (collab_accounts,) in posts:
            for account in (collab_accounts or "").split(","):
                campus = account_campus.get(normalize_username(account))
                if campus:
                    votes[campus] += 1
        if votes:
            top_count = max(votes.values())
            campus = sorted(c for c, n in votes.items() if n == top_count)[0]
        else:
            campus = campus_from_school(ambassador.school, known_campuses)
        if not campus:
            continue
        ambassador.campus = campus
        ambassador.updated_at = now
        updated += 1

    db.commit()
    if updated:
        logger.info(f"Campus inference: assigned campus to {updated} ambassadors")
    return updated


def enrich_profiles(db: Session) -> int:
    """Business Discovery profile pull for confirmed ambassadors.

    Profile fields ONLY (include_media=False) — an ambassador's own post
    history is deliberately never copied; only collab-with-us content is
    tracked, and that arrives via the network pull. Athlete-linked
    ambassadors are skipped: their trendline already comes from the athlete
    pipeline. Returns the number of snapshots written.
    """
    from backend.sources.instagram import REQUEST_INTERVAL, fetch_ig_profile

    pulled_at = datetime.now(tz=timezone.utc)
    targets = (
        db.query(Ambassador)
        .filter(
            Ambassador.status == "confirmed",
            Ambassador.active == True,  # noqa: E712
            Ambassador.athlete_id.is_(None),
            Ambassador.ig_username.isnot(None),  # sheet-only rows have no handle yet
        )
        .order_by(Ambassador.ig_username)
        .all()
    )

    written = 0
    for i, ambassador in enumerate(targets):
        if (
            ambassador.ig_accessible is False
            and ambassador.ig_checked_at is not None
            and (pulled_at - ambassador.ig_checked_at) < timedelta(days=RECHECK_DAYS)
        ):
            continue

        if written > 0:
            time.sleep(random.uniform(*REQUEST_INTERVAL))

        profile = fetch_ig_profile(ambassador.ig_username, include_media=False)
        ambassador.ig_checked_at = pulled_at
        ambassador.ig_accessible = profile.is_accessible
        if profile.ig_user_id and not ambassador.ig_user_id:
            ambassador.ig_user_id = profile.ig_user_id
        # Refresh CDN-expiring assets every pull; fill display_name only when
        # empty (the sheet name is authoritative once imported).
        if profile.profile_picture_url:
            ambassador.profile_pic_url = profile.profile_picture_url
        if profile.website:
            ambassador.website = profile.website
        if profile.name and not ambassador.display_name:
            ambassador.display_name = profile.name
        if profile.error:
            logger.warning(f"Ambassador @{ambassador.ig_username}: {profile.error[:80]}")

        # Snapshot even on error — keeps the timeline consistent (same
        # convention as athlete_snapshots).
        db.add(AmbassadorSnapshot(
            ambassador_id=ambassador.id,
            pulled_at=pulled_at,
            followers=profile.followers,
            post_count=profile.post_count,
            bio=profile.bio,
        ))
        written += 1

    db.commit()
    if targets:
        logger.info(f"Ambassador enrichment: {written} snapshots for {len(targets)} confirmed")
    return written


# ── Safe entry points for the cron jobs ─────────────────────────────────────
# These never raise: ambassador bookkeeping must not break media ingestion.

def run_welcome_scan(db: Session) -> dict:
    """Welcome parser, called at the end of run_brand_ig."""
    try:
        return scan_welcome_posts(db)
    except Exception:
        logger.exception("Welcome scan failed (media ingest unaffected)")
        db.rollback()
        return {}


def run_ambassador_passes(db: Session) -> int:
    """Attribution + campus inference + cache, called after the network upsert."""
    try:
        stamped = attribute_posts(db)
        infer_campuses(db)
        from backend.jobs.precompute import precompute_ambassador_cache
        precompute_ambassador_cache(db)
        return stamped
    except Exception:
        logger.exception("Ambassador attribution failed (media ingest unaffected)")
        db.rollback()
        return 0


def run_ambassador_enrichment(db: Session) -> int:
    """Profile enrichment + cache, called at the end of run_instagram."""
    try:
        written = enrich_profiles(db)
        from backend.jobs.precompute import precompute_ambassador_cache
        precompute_ambassador_cache(db)
        return written
    except Exception:
        logger.exception("Ambassador enrichment failed (athlete ingest unaffected)")
        db.rollback()
        return 0
