#!/usr/bin/env python3
"""
Import NILTV network posts into the niltv_network_posts table — the ONE table
that holds every Instagram post the network touches, whichever feed saw it.

`upsert_posts` is the single choke point every writer goes through:

  source     job / path                              brings
  ---------  --------------------------------------  --------------------------------
  graph      run_niltv_network (nightly Graph API)   views, likes, comments (+ shares/
                                                     saves/reach on owned posts)
  export     Meta Business Suite CSV (Admin upload)  views, likes, shares, comments,
                                                     saves, reach, follows
  bd         run_manual_channels (Business Discovery) likes, comments
  public     grid snapshot CSV (manual channels)    likes, comments, public play count

The rules that keep one truth per post:

* One row per post. post_id is the Graph media id; a provisional key (the
  public media key a grid snapshot carries) is matched by permalink and re-keyed
  when the Graph id arrives (`_match_by_permalink`).
* One post_type vocabulary: REELS / IMAGE / CAROUSEL_ALBUM / VIDEO
  (`normalize_post_type`). A more specific label may upgrade a generic one
  (FEED -> IMAGE), never the reverse.
* Views are ranked by source (`VIEWS_RANK`): graph > export > public. A write
  lands only when its rank is at least the rank that last wrote the row, so a
  public count fills posts no other feed covers but never replaces Graph or export
  numbers, and a fresh export replaces public counts. `views_source` records
  who wrote the value. Likes/comments are the same public count from every
  source (latest wins); shares/saves/reach/follows only come from exports.
* Channel tags (collab_accounts, OUR registry keys) only ever grow. Besides the
  `--account` stamp, the owner handle and the co-author handles on a CSV row are
  mapped through brand_accounts so a manual channel's collaborators are kept.

CSV format matches the Meta Business Suite export:
  Post ID, Account ID, Account username, Account name, Description,
  Duration (sec), Publish time, Permalink, Post type, Data comment,
  Date, Views, Likes, Shares, Comments, Saves, Reach, Follows

Usage:
    python -m backend.jobs.import_niltv_network data/niltv_network.csv
    python -m backend.jobs.import_niltv_network data/trueblue_grid.csv --account truebluetv --source public
"""

import argparse
import csv
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import BrandAccount, NiltvNetworkPost, NiltvNetworkPostSnapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Source precedence ──────────────────────────────────────────────────────────
SOURCE_GRAPH = "graph"
SOURCE_EXPORT = "export"
SOURCE_BD = "bd"
SOURCE_PUBLIC = "public"   # public play count from a grid snapshot CSV
SOURCES = (SOURCE_GRAPH, SOURCE_EXPORT, SOURCE_BD, SOURCE_PUBLIC)

# Only `views` needs ranking: it is the one metric whose definition differs by
# source (Graph/insights views vs Business Suite Views vs the public play count).
VIEWS_RANK = {SOURCE_GRAPH: 3, SOURCE_EXPORT: 2, SOURCE_BD: 1, SOURCE_PUBLIC: 1, None: 0}

# ── post_type vocabulary ───────────────────────────────────────────────────────
POST_TYPE_REELS = "REELS"
POST_TYPE_IMAGE = "IMAGE"
POST_TYPE_CAROUSEL = "CAROUSEL_ALBUM"
POST_TYPE_VIDEO = "VIDEO"
CANONICAL_POST_TYPES = {POST_TYPE_REELS, POST_TYPE_IMAGE, POST_TYPE_CAROUSEL, POST_TYPE_VIDEO}
# Legacy Graph label for "not a reel" — carousels and images collapsed together.
POST_TYPE_FEED = "FEED"

_POST_TYPE_ALIASES = {
    "reels": POST_TYPE_REELS, "reel": POST_TYPE_REELS, "ig reel": POST_TYPE_REELS,
    "ig reels": POST_TYPE_REELS, "clips": POST_TYPE_REELS,
    "image": POST_TYPE_IMAGE, "ig image": POST_TYPE_IMAGE, "photo": POST_TYPE_IMAGE,
    "carousel_album": POST_TYPE_CAROUSEL, "carousel": POST_TYPE_CAROUSEL,
    "ig carousel": POST_TYPE_CAROUSEL, "album": POST_TYPE_CAROUSEL,
    "video": POST_TYPE_VIDEO, "ig video": POST_TYPE_VIDEO,
    "feed": POST_TYPE_FEED,
}


def normalize_post_type(raw: str | None, media_type: str | None = None) -> str | None:
    """Map any feed's label onto the canonical vocabulary.

    `raw` is the primary label (Graph media_product_type, Business Suite
    "Post type", snapshot label); `media_type` is the Graph media_type used to
    split the generic FEED label into IMAGE / CAROUSEL_ALBUM / VIDEO.
    Unknown labels pass through untouched so nothing is silently lost.
    """
    label = (raw or "").strip().lower()
    mapped = _POST_TYPE_ALIASES.get(label)
    if mapped is None and label:
        return raw.strip()
    if mapped in (POST_TYPE_FEED, None) and media_type:
        fine = _POST_TYPE_ALIASES.get(media_type.strip().lower())
        if fine in CANONICAL_POST_TYPES:
            return fine
    return mapped


def _post_type_upgrade(current: str | None, incoming: str | None) -> str | None:
    """A specific label replaces nothing/FEED/an unknown label; a specific
    label never replaces another specific label (first Graph sighting wins)."""
    if incoming not in CANONICAL_POST_TYPES:
        return current if current else incoming
    if current in CANONICAL_POST_TYPES:
        return current
    return incoming


MUTABLE_FIELDS = ["views", "likes", "shares", "comments", "saves", "reach", "follows", "projected_reach"]


def _get_reach_views_ratio(db: Session) -> float | None:
    from sqlalchemy import text
    row = db.execute(text(
        "SELECT AVG(reach::float / NULLIF(views, 0)) AS ratio "
        "FROM niltv_network_posts "
        "WHERE reach IS NOT NULL AND reach > 0 AND views > 0"
    )).fetchone()
    return float(row.ratio) if row and row.ratio is not None else None


def _compute_projected_reach(reach: int | None, views: int | None, ratio: float | None) -> int | None:
    if reach and reach > 0:
        return None
    if views and views > 0 and ratio:
        return round(views * ratio)
    return None


def _parse_int(val: str) -> int | None:
    if not val or val.strip() == "":
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


def _parse_datetime(val: str) -> datetime | None:
    if not val or val.strip() == "":
        return None
    try:
        return datetime.strptime(val.strip(), "%m/%d/%Y %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _views_allowed(db_row: NiltvNetworkPost, source: str | None) -> bool:
    """May `source` write views on this row? Equal rank re-writes (a nightly
    Graph pull refreshing its own number); a lower rank only fills a hole."""
    if db_row.views is None:
        return True
    return VIEWS_RANK.get(source, 0) >= VIEWS_RANK.get(db_row.views_source, 0)


def _has_changes(db_row: NiltvNetworkPost, new_values: dict, source: str | None) -> bool:
    for field in MUTABLE_FIELDS:
        new_val = new_values.get(field)
        if new_val is None or getattr(db_row, field, None) == new_val:
            continue
        if field == "views" and not _views_allowed(db_row, source):
            continue
        return True
    return False


def _snapshot_from_db_row(db_row: NiltvNetworkPost, captured_at: datetime) -> NiltvNetworkPostSnapshot:
    return NiltvNetworkPostSnapshot(
        network_post_id=db_row.id,
        captured_at=captured_at,
        views=db_row.views,
        likes=db_row.likes,
        shares=db_row.shares,
        comments=db_row.comments,
        saves=db_row.saves,
        reach=db_row.reach,
        projected_reach=db_row.projected_reach,
        follows=db_row.follows,
    )


def _update_db_row(db_row: NiltvNetworkPost, new_values: dict, updated_at: datetime, source: str | None) -> None:
    for field in MUTABLE_FIELDS:
        new_val = new_values.get(field)
        if new_val is None:
            continue
        if field == "views":
            if not _views_allowed(db_row, source):
                continue
            db_row.views_source = source
        setattr(db_row, field, new_val)
    db_row.updated_at = updated_at


# Post metadata set on insert (post_type may later be upgraded, see _post_type_upgrade).
METADATA_FIELDS = [
    "account_username", "account_name", "description",
    "duration_sec", "publish_time", "permalink", "post_type",
    "media_url", "thumbnail_url", "collab_accounts",
]
# Per-post metrics that may change between pulls (None = leave existing value).
METRIC_FIELDS = ["views", "likes", "shares", "comments", "saves", "reach", "follows"]
# Media URLs refresh on every pull (IG CDN URLs expire within hours).
MEDIA_FIELDS = ["media_url", "thumbnail_url"]


def _split_tags(value: str | None) -> set[str]:
    return {a.strip() for a in (value or "").split(",") if a.strip()}


def _refresh_media_and_accounts(db_row: NiltvNetworkPost, r: dict) -> None:
    """Refresh short-lived media URLs, union collab_accounts, upgrade post_type."""
    for field in MEDIA_FIELDS:
        val = r.get(field)
        if val:
            setattr(db_row, field, val)
    new_accounts = _split_tags(r.get("collab_accounts"))
    if new_accounts:
        current = _split_tags(db_row.collab_accounts)
        merged = current | new_accounts
        if merged != current:
            db_row.collab_accounts = ",".join(sorted(merged))
    upgraded = _post_type_upgrade(db_row.post_type, r.get("post_type"))
    if upgraded != db_row.post_type:
        db_row.post_type = upgraded


# ── Handle -> registry key mapping (collaborator capture) ─────────────────────

def registry_handle_map(db: Session) -> dict[str, str]:
    """Lowercased IG handle -> brand_accounts.account for every registry row.
    The key itself is also accepted as a handle (they coincide for the Graph
    channels: @niltv, @dorecitytv, ...), so a missing username never hides a
    channel."""
    handles: dict[str, str] = {}
    for acct, username in db.query(BrandAccount.account, BrandAccount.username).all():
        if acct:
            handles[acct.strip().lower()] = acct
        if username:
            handles[username.strip().lower().lstrip("@")] = acct
    return handles


def _channel_tags_for_row(r: dict, handle_map: dict[str, str]) -> set[str]:
    """Registry keys for the row's owner and co-author handles (if any are ours)."""
    tags: set[str] = set()
    owner = (r.get("account_username") or "").strip().lower().lstrip("@")
    if owner and owner in handle_map:
        tags.add(handle_map[owner])
    for h in r.get("_coauthors") or []:
        key = handle_map.get((h or "").strip().lower().lstrip("@"))
        if key:
            tags.add(key)
    return tags


_SHORTCODE_RE = re.compile(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")


def _shortcode(permalink: str | None) -> str | None:
    m = _SHORTCODE_RE.search(permalink or "")
    return m.group(1) if m else None


def _is_graph_id(post_id: str | None) -> bool:
    """Instagram Graph API media id (17.../18..., 17 digits): the key the Graph
    pulls and Business Suite exports use. Anything else (e.g. the public media
    key a grid snapshot carries) is a provisional key."""
    pid = (post_id or "").strip()
    return pid.isdigit() and len(pid) == 17 and pid.startswith(("17", "18"))


def _match_by_permalink(db: Session, rows: list[dict], existing_map: dict) -> int:
    """Rows whose post_id is unknown may still be posts we hold under another
    key: a grid snapshot CSV (manual channels, e.g. truebluetv) only carries
    Instagram's public media key, while the Graph pull / Business Suite export
    bring the Graph id for the same permalink. Match on the permalink shortcode,
    adopt the stored key, and when the incoming key is the Graph id and the
    stored one is not, re-key the row (snapshots hang off the row id, so this is
    safe). Mutates `rows` (post_id) and `existing_map`; returns rows re-keyed."""
    by_sc: dict[str, list[dict]] = {}
    for r in rows:
        if r["post_id"] in existing_map:
            continue
        sc = _shortcode(r.get("permalink"))
        if sc:
            by_sc.setdefault(sc, []).append(r)
    if not by_sc:
        return 0
    found: dict[str, list[NiltvNetworkPost]] = {}
    scs = list(by_sc)
    for i in range(0, len(scs), 100):
        conds = [NiltvNetworkPost.permalink.like(f"%/{sc}/%") for sc in scs[i:i + 100]]
        for db_row in db.query(NiltvNetworkPost).filter(or_(*conds)).all():
            sc = _shortcode(db_row.permalink)
            if sc in by_sc:
                found.setdefault(sc, []).append(db_row)
    rekeyed = 0
    for sc, incoming in by_sc.items():
        cands = found.get(sc)
        if not cands:
            continue
        for r in incoming:
            exact = [d for d in cands if d.post_id == r["post_id"]]
            if exact:
                target = exact[0]
            elif _is_graph_id(r["post_id"]) and not any(_is_graph_id(d.post_id) for d in cands):
                target = cands[0]
                logger.info(f"re-keying {target.post_id} -> {r['post_id']} ({sc})")
                target.post_id = r["post_id"]
                rekeyed += 1
            else:
                target = next((d for d in cands if _is_graph_id(d.post_id)), cands[0])
                r["post_id"] = target.post_id
            existing_map[r["post_id"]] = target
    if rekeyed:
        db.flush()
    return rekeyed


def upsert_posts(
    db: Session,
    rows: list[dict],
    captured_at: datetime | None = None,
    source: str | None = None,
) -> tuple[int, int]:
    """Upsert normalized network post dicts. Returns (inserted, updated).

    Each row is a dict with `post_id`, the METADATA_FIELDS, the METRIC_FIELDS
    and optionally `_coauthors` (IG handles) and `_source` (overrides `source`
    per row). Metrics that are None are left untouched on existing rows — so an
    API pull (views/likes/comments) and a CSV upload (shares/saves/reach) can
    write to the same post without clobbering each other; views additionally
    obey VIEWS_RANK. One snapshot per post per UTC day. Unknown post_ids are
    matched by permalink before inserting so the same post never lands twice.
    """
    if captured_at is None:
        captured_at = datetime.now(tz=timezone.utc)
    if source is not None and source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")

    rows = [r for r in rows if r.get("post_id")]
    handle_map = registry_handle_map(db)
    for r in rows:
        r["post_type"] = normalize_post_type(r.get("post_type"), r.get("_media_type"))
        tags = _split_tags(r.get("collab_accounts")) | _channel_tags_for_row(r, handle_map)
        r["collab_accounts"] = ",".join(sorted(tags)) if tags else None

    post_ids = [r["post_id"] for r in rows]
    existing_rows = (
        db.query(NiltvNetworkPost)
        .filter(NiltvNetworkPost.post_id.in_(post_ids))
        .all()
    )
    existing_map = {row.post_id: row for row in existing_rows}
    rekeyed = _match_by_permalink(db, rows, existing_map)
    existing_rows = list({id(r): r for r in existing_map.values()}.values())

    today_start = captured_at.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    already_snapped_today = set()
    if existing_rows:
        existing_ids = [r.id for r in existing_rows]
        snapped = (
            db.query(NiltvNetworkPostSnapshot.network_post_id)
            .filter(
                NiltvNetworkPostSnapshot.network_post_id.in_(existing_ids),
                NiltvNetworkPostSnapshot.captured_at >= today_start,
                NiltvNetworkPostSnapshot.captured_at < today_end,
            )
            .distinct()
            .all()
        )
        already_snapped_today = {r[0] for r in snapped}

    ratio = _get_reach_views_ratio(db)

    inserted = 0
    updated = 0
    views_held = 0

    for r in rows:
        post_id = r["post_id"]
        row_source = r.get("_source") or source
        new_values = {f: r.get(f) for f in METRIC_FIELDS}
        db_row = existing_map.get(post_id)

        if db_row is None:
            new_values["projected_reach"] = _compute_projected_reach(
                new_values.get("reach"), new_values.get("views"), ratio
            )
            new_post = NiltvNetworkPost(
                post_id=post_id,
                **{f: r.get(f) for f in METADATA_FIELDS},
                **new_values,
            )
            if new_values.get("views") is not None:
                new_post.views_source = row_source
            db.add(new_post)
            db.flush()
            db.add(_snapshot_from_db_row(new_post, captured_at))
            existing_map[post_id] = new_post
            inserted += 1
        else:
            if new_values.get("views") is not None and not _views_allowed(db_row, row_source):
                views_held += 1
            new_values["projected_reach"] = _compute_projected_reach(
                new_values.get("reach") or db_row.reach,
                (new_values.get("views") if _views_allowed(db_row, row_source) else None) or db_row.views,
                ratio,
            )
            _refresh_media_and_accounts(db_row, r)
            if _has_changes(db_row, new_values, row_source):
                _update_db_row(db_row, new_values, captured_at, row_source)
                updated += 1
            if db_row.id not in already_snapped_today:
                db.add(_snapshot_from_db_row(db_row, captured_at))
                already_snapped_today.add(db_row.id)

    db.commit()
    unchanged = len(rows) - inserted - updated
    logger.info(f"Done ({source or 'mixed'}): {inserted} inserted, {updated} updated, {unchanged} unchanged"
                + (f", {rekeyed} re-keyed by permalink" if rekeyed else "")
                + (f", {views_held} views kept from a higher-ranked source" if views_held else ""))
    return inserted, updated


# ── CSV path (Business Suite export / grid snapshot CSV) ───────────────────────────

_COAUTHOR_RE = re.compile(r"co-authors?:\s*([^;|]+)", re.IGNORECASE)
PUBLIC_COMMENT_MARK = "public grid snapshot"


def _coauthors_from_comment(comment: str | None) -> list[str]:
    m = _COAUTHOR_RE.search(comment or "")
    if not m:
        return []
    return [h.strip().lstrip("@") for h in m.group(1).split(",") if h.strip()]


def detect_csv_source(comment: str | None) -> str:
    """A grid snapshot stamps its rows' Data comment; anything else is a Business
    Suite export."""
    return SOURCE_PUBLIC if PUBLIC_COMMENT_MARK in (comment or "").lower() else SOURCE_EXPORT


def _csv_row_to_dict(r: dict, account: str | None = None, source: str | None = None) -> dict:
    """Map a Meta Business Suite CSV export row to the normalized upsert dict.
    `account` (a brand_accounts.account key) is stamped as collab_accounts;
    None leaves attribution to the owner/co-author handles."""
    comment = r.get("Data comment", "")
    return {
        "post_id": r.get("Post ID", "").strip(),
        "collab_accounts": account,
        "account_username": r.get("Account username", "").strip() or None,
        "account_name": r.get("Account name", "").strip() or None,
        "description": r.get("Description", "").strip() or None,
        "duration_sec": _parse_int(r.get("Duration (sec)", "")),
        "publish_time": _parse_datetime(r.get("Publish time", "")),
        "permalink": r.get("Permalink", "").strip() or None,
        "post_type": r.get("Post type", "").strip() or None,
        "views": _parse_int(r.get("Views", "")),
        "likes": _parse_int(r.get("Likes", "")),
        "shares": _parse_int(r.get("Shares", "")),
        "comments": _parse_int(r.get("Comments", "")),
        "saves": _parse_int(r.get("Saves", "")),
        "reach": _parse_int(r.get("Reach", "")),
        "follows": _parse_int(r.get("Follows", "")),
        "_coauthors": _coauthors_from_comment(comment),
        "_source": source or detect_csv_source(comment),
    }


def import_csv(
    db: Session,
    csv_path: str,
    captured_at: datetime | None = None,
    account: str | None = None,
    source: str | None = None,
) -> tuple[int, int]:
    """Import/update network posts from a CSV. Returns (inserted, updated).
    `account` tags every row to that channel; `source` forces the provenance
    (default: detected per row from the Data comment)."""
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = [_csv_row_to_dict(r, account, source) for r in csv.DictReader(f) if r.get("Post ID")]

    logger.info(f"Read {len(rows)} rows from {csv_path} (account={account or '-'}, source={source or 'auto'})")
    return upsert_posts(db, rows, captured_at)


def main():
    parser = argparse.ArgumentParser(description="Import network posts from a Business Suite-layout CSV")
    parser.add_argument("csv_file", type=str, help="Path to Meta Business Suite CSV export (or grid snapshot CSV)")
    parser.add_argument("--account", default=None,
                        help="registry account to stamp on every row's collab_accounts "
                             "(manual channels, e.g. truebluetv)")
    parser.add_argument("--source", default=None, choices=[SOURCE_EXPORT, SOURCE_PUBLIC],
                        help="force the provenance; default detects snapshot rows by their Data comment")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        inserted, updated = import_csv(db, args.csv_file, account=args.account, source=args.source)
        logger.info(f"Total: {inserted} inserted, {updated} updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
