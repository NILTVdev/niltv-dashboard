"""
Content library router: /api/library

The NIL TV app's hourly ingest labels every clip (sport, school, content
types, categories, sponsor, athletes, keywords, summary, QC state) and POSTs a
full snapshot here (/sync). Staff search and filter it on the Library page; each
clip that came from Instagram is joined to niltv_network_posts on its media id
for views, likes, comments, shares and saves. When the network pull has no row
for it, brand_posts (the owned brand accounts' own pull) is used instead; a
network row always wins. A number the dashboard has not pulled stays null,
never 0.

Access: general may GET (backend/accounts.py); demo may not (per-clip data);
POST /sync is admin or service caller only (the app's ingest Lambda sends the
key with no account header).
"""

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend import athlete_directory as directory
from backend.auth import require_api_key
from backend.database import SessionLocal, get_db
from backend.models import LibraryItem, LibrarySyncRun

router = APIRouter(dependencies=[Depends(require_api_key)])

MAX_ITEMS = 5000
_UPSERT_CHUNK = 500
READY = "ready"


# ── Sync contract ─────────────────────────────────────────────────────────────

def strip_nul(v):
    """Drop NUL characters from every string in v (nested lists and dicts too).
    JSON allows a \\u0000 escape but Postgres text cannot store it, and one bad caption
    must not fail the whole snapshot."""
    if isinstance(v, str):
        return v.replace("\x00", "")
    if isinstance(v, list):
        return [strip_nul(x) for x in v]
    if isinstance(v, dict):
        return {k: strip_nul(x) for k, x in v.items()}
    return v


class SyncAthlete(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)
    id: Optional[str] = None
    name: Optional[str] = None
    handle: Optional[str] = None


_LIST_FIELDS = ("keywords", "content_types", "categories", "tags", "athletes", "unresolved_handles")


class SyncItem(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)
    content_id: str = Field(min_length=1)
    ig_post_id: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    title: str
    caption: Optional[str] = None
    summary: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    sport: Optional[str] = None
    school: Optional[str] = None
    content_type: Optional[str] = None
    content_types: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    sponsor: Optional[str] = None
    # Content API tagging (migration 037). Optional, so an older app build
    # that does not send them still syncs.
    tags: list[str] = Field(default_factory=list)
    asset_type: Optional[str] = None
    series_id: Optional[str] = None
    series_name: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    athletes: list[SyncAthlete] = Field(default_factory=list)
    unresolved_handles: list[str] = Field(default_factory=list)
    status: str
    qc_state: Optional[str] = None
    poster_url: Optional[str] = None
    video_url: Optional[str] = None
    duration_sec: Optional[float] = None
    posted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _strip_nul(cls, v):
        return strip_nul(v)

    # The contract sends [] for empty lists; a null is read as [] rather than
    # refusing the whole snapshot over one field.
    @field_validator(*_LIST_FIELDS, mode="before")
    @classmethod
    def _null_list(cls, v):
        return [] if v is None else v

    @field_validator("ig_post_id", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class SyncBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str
    stage: Literal["dev", "prod"]
    generated_at: datetime
    full: bool
    items: list[SyncItem]


def _row(item: SyncItem, stage: str) -> dict:
    d = item.model_dump()
    d["stage"] = stage
    d["removed"] = False
    return d


def _validation_message(e: ValidationError) -> str:
    parts = []
    for err in e.errors(include_url=False)[:5]:
        loc = ".".join(str(x) for x in err["loc"])
        parts.append(f"{loc}: {err['msg']}" if loc else err["msg"])
    more = e.error_count() - len(parts)
    return "; ".join(parts) + (f" (and {more} more)" if more > 0 else "")


def _record_refusal(stage: Any, received: int, error: str) -> None:
    """A refused sync still shows on the status line. Own session: the request's
    session may be mid-rollback."""
    db = SessionLocal()
    try:
        db.add(LibrarySyncRun(stage=stage if stage in ("dev", "prod") else None,
                              received=received, ok=False, error=error[:2000]))
        db.commit()
    finally:
        db.close()


@router.post("/sync")
async def sync_library(request: Request, db: Session = Depends(get_db)):
    """Full or partial snapshot from the app's ingest. Upserts by content_id in
    one transaction. With full=true, rows previously synced from the same stage
    that are missing from items are marked removed. 200 {received, upserted,
    removed}; 400 on an invalid body; 413 over MAX_ITEMS items. Idempotent."""
    try:
        payload = json.loads(await request.body() or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        _record_refusal(None, 0, "invalid JSON")
        raise HTTPException(status_code=400, detail="invalid JSON")
    stage = payload.get("stage") if isinstance(payload, dict) else None
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list) and len(items) > MAX_ITEMS:
        _record_refusal(stage, len(items), f"too many items ({len(items)} > {MAX_ITEMS})")
        raise HTTPException(status_code=413, detail=f"at most {MAX_ITEMS} items per sync")
    try:
        body = SyncBody.model_validate(payload)
    except ValidationError as e:
        msg = _validation_message(e)
        _record_refusal(stage, len(items) if isinstance(items, list) else 0, msg)
        raise HTTPException(status_code=400, detail=msg)

    # Last copy of a repeated content_id wins (one statement cannot upsert a key twice).
    rows = list({it.content_id: _row(it, body.stage) for it in body.items}.values())
    table = LibraryItem.__table__
    try:
        for i in range(0, len(rows), _UPSERT_CHUNK):
            stmt = insert(table).values(rows[i:i + _UPSERT_CHUNK])
            updates = {k: stmt.excluded[k] for k in rows[0] if k != "content_id"}
            updates["last_synced_at"] = func.now()
            db.execute(stmt.on_conflict_do_update(index_elements=["content_id"], set_=updates))
        removed = 0
        if body.full:
            removed = db.execute(text("""
                UPDATE library_items SET removed = TRUE, last_synced_at = NOW()
                WHERE stage = :stage AND NOT removed AND NOT (content_id = ANY(:ids))
            """), {"stage": body.stage, "ids": [r["content_id"] for r in rows]}).rowcount
        db.add(LibrarySyncRun(stage=body.stage, generated_at=body.generated_at,
                              received=len(body.items), upserted=len(rows),
                              removed=removed, ok=True))
        db.commit()
    except Exception as e:
        db.rollback()
        _record_refusal(body.stage, len(body.items), f"database error: {type(e).__name__}")
        raise
    return {"received": len(body.items), "upserted": len(rows), "removed": removed}


# ── Read side ─────────────────────────────────────────────────────────────────

class Performance(BaseModel):
    matched: bool                   # an Instagram post row was found for ig_post_id
    # Which pull the numbers came from: 'network' (niltv_network_posts) or
    # 'brand' (brand_posts, used only when the network pull has no row).
    source: Optional[Literal["network", "brand"]] = None
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    reach: Optional[int] = None
    interactions: Optional[int] = None  # likes + comments + shares + saves that are known
    permalink: Optional[str] = None


class Athlete(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    handle: Optional[str] = None
    # The Athletes page key (/athletes/{key}) of the person with this
    # Instagram handle, when the athlete directory has one.
    directory_key: Optional[str] = None


class LibraryItemOut(BaseModel):
    content_id: str
    stage: str
    ig_post_id: Optional[str]
    channel_id: Optional[str]
    channel_name: Optional[str]
    title: str
    caption: Optional[str]
    summary: Optional[str]
    keywords: list[str]
    sport: Optional[str]
    school: Optional[str]
    content_type: Optional[str]
    content_types: list[str]
    categories: list[str]
    sponsor: Optional[str]
    tags: list[str] = []
    asset_type: Optional[str] = None
    series_id: Optional[str] = None
    series_name: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    athletes: list[Athlete]
    unresolved_handles: list[str]
    status: str
    qc_state: Optional[str]
    poster_url: Optional[str]
    video_url: Optional[str]
    duration_sec: Optional[float]
    posted_at: Optional[datetime]
    updated_at: Optional[datetime]
    removed: bool
    first_seen_at: datetime
    last_synced_at: datetime
    performance: Performance


class LibraryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[LibraryItemOut]


_ITEM_COLUMNS = ", ".join(f"li.{c}" for c in (
    "content_id", "stage", "ig_post_id", "channel_id", "channel_name", "title", "caption",
    "summary", "keywords", "sport", "school", "content_type", "content_types", "categories",
    "sponsor", "tags", "asset_type", "series_id", "series_name", "season", "episode",
    "athletes", "unresolved_handles", "status", "qc_state", "poster_url",
    "video_url", "duration_sec", "posted_at", "updated_at", "removed", "first_seen_at",
    "last_synced_at"))

# Numbers come from the network pull when it has the post, else from the brand
# account pull. The brand join only runs when no network row matched, so a
# network row always wins (even where its own value is null) and COALESCE
# never mixes the two sources.
_METRICS = {
    "views": "COALESCE(p.views, b.views)",
    "likes": "COALESCE(p.likes, b.like_count)",
    "comments": "COALESCE(p.comments, b.comment_count)",
    "shares": "COALESCE(p.shares, b.shares)",
    "saves": "COALESCE(p.saves, b.saves)",
    "reach": "COALESCE(p.reach, b.reach)",
    "permalink": "COALESCE(p.permalink, b.permalink)",
}
_COUNTED = [_METRICS[k] for k in ("likes", "comments", "shares", "saves")]
# Null when no post row matched or it carries no interaction counts at all.
_INTERACTIONS = (f"CASE WHEN {' AND '.join(f'{c} IS NULL' for c in _COUNTED)} THEN NULL "
                 f"ELSE {' + '.join(f'COALESCE({c}, 0)' for c in _COUNTED)} END")

_FIELDS = (f"{_ITEM_COLUMNS}, (p.id IS NOT NULL OR b.id IS NOT NULL) AS perf_matched, "
           "CASE WHEN p.id IS NOT NULL THEN 'network' WHEN b.id IS NOT NULL THEN 'brand' END AS perf_source, "
           + ", ".join(f"{expr} AS perf_{name}" for name, expr in _METRICS.items())
           + f", {_INTERACTIONS} AS perf_interactions")
_FROM = """FROM library_items li
    LEFT JOIN niltv_network_posts p ON p.post_id = li.ig_post_id
    LEFT JOIN brand_posts b ON p.id IS NULL AND b.ig_post_id = li.ig_post_id"""


def _item(row) -> LibraryItemOut:
    m = dict(row._mapping)
    perf = {k[5:]: m.pop(k) for k in list(m) if k.startswith("perf_")}
    m.pop("rank", None)
    return LibraryItemOut(**m, performance=Performance(**perf))


def link_athletes(db: Session, items: list[LibraryItemOut]) -> list[LibraryItemOut]:
    """Set directory_key on each tagged athlete whose handle belongs to a
    person in the athlete directory (built once per process, cached)."""
    if not any(a.handle for it in items for a in it.athletes):
        return items
    keys = directory.keys_by_handle(directory.build_directory(db))
    for it in items:
        for a in it.athletes:
            h = directory.normalize_handle(a.handle)
            a.directory_key = keys.get(h) if h else None
    return items


CLIPS_LIMIT = 24

# A clip features a handle when an athlete tagged on it, or a handle the app
# could not match to one of its athletes, is that handle.
_FEATURES_HANDLES = """(
    EXISTS (SELECT 1 FROM jsonb_array_elements(li.athletes) a
            WHERE lower(ltrim(a->>'handle', '@')) = ANY(:handles))
    OR EXISTS (SELECT 1 FROM unnest(li.unresolved_handles) u
               WHERE lower(ltrim(u, '@')) = ANY(:handles)))"""


def clips_for_handles(db: Session, handles: list[str], limit: int = CLIPS_LIMIT) -> tuple[int, list[LibraryItemOut]]:
    """Library clips (not removed) featuring any of these normalized
    Instagram handles, newest first: (total, first ``limit``)."""
    if not handles:
        return 0, []
    params = {"handles": list(handles), "limit": limit}
    where = f"WHERE NOT li.removed AND {_FEATURES_HANDLES}"
    total = db.execute(text(f"SELECT COUNT(*) FROM library_items li {where}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT {_FIELDS} {_FROM} {where}
        ORDER BY li.posted_at DESC NULLS LAST, li.content_id LIMIT :limit
    """), params).fetchall()
    return total, [_item(r) for r in rows]


_WEBSEARCH_OPERATORS = re.compile(r'"|(?:^|\s)-\S|\bor\b', re.IGNORECASE)


def prefix_tsquery(q: str) -> Optional[str]:
    """'Duke basketb' -> 'duke:* & basketb:*' for to_tsquery('simple', ...), so a
    partly typed word still matches. None when q has no word characters, or
    when q uses websearch syntax (-word, "phrase", or): the prefix form would
    drop the exclusion or phrase and widen the match."""
    if _WEBSEARCH_OPERATORS.search(q):
        return None
    words = re.findall(r"[^\W_]+", q.lower())
    return " & ".join(f"{w}:*" for w in words) if words else None


class Filters(BaseModel):
    q: Optional[str] = None
    sport: Optional[str] = None
    school: Optional[str] = None
    channel: Optional[str] = None
    content_type: Optional[str] = None
    category: Optional[str] = None
    sponsor: Optional[str] = None
    tag: Optional[str] = None
    series: Optional[str] = None
    asset_type: Optional[str] = None
    athlete: Optional[str] = None
    qc_state: Optional[str] = None
    needs_tagging: bool = False
    posted_from: Optional[date] = None
    posted_to: Optional[date] = None
    has_video: Optional[bool] = None
    include_removed: bool = False


def _filters_dep(
    q: Optional[str] = Query(None, max_length=200),
    sport: Optional[str] = None,
    school: Optional[str] = None,
    channel: Optional[str] = Query(None, description="channel id"),
    content_type: Optional[str] = None,
    category: Optional[str] = None,
    sponsor: Optional[str] = None,
    tag: Optional[str] = Query(None, description="staff tag"),
    series: Optional[str] = Query(None, description="series id"),
    asset_type: Optional[str] = Query(None, description="episode | clip | short"),
    athlete: Optional[str] = Query(None, description="athlete handle (with or without @) or athlete id"),
    qc_state: Optional[str] = None,
    needs_tagging: bool = Query(False, description="only clips whose QC state is not ready"),
    posted_from: Optional[date] = None,
    posted_to: Optional[date] = None,
    has_video: Optional[bool] = None,
    include_removed: bool = False,
) -> Filters:
    return Filters(q=(q or "").strip() or None, sport=sport, school=school, channel=channel,
                   content_type=content_type, category=category, sponsor=sponsor,
                   tag=tag, series=series, asset_type=asset_type, athlete=athlete, qc_state=qc_state, needs_tagging=needs_tagging,
                   posted_from=posted_from, posted_to=posted_to, has_video=has_video,
                   include_removed=include_removed)


def _where(f: Filters, skip: Optional[str] = None) -> tuple[str, dict]:
    """WHERE clause + params for the filters. ``skip`` leaves one facet's own
    filter out, so its counts show every value the other filters allow."""
    clauses, params = [], {}
    if not f.include_removed:
        clauses.append("NOT li.removed")
    if f.q:
        params["q"] = f.q
        match = "li.search @@ websearch_to_tsquery('english', :q)"
        pq = prefix_tsquery(f.q)
        if pq:
            params["pq"] = pq
            match = f"({match} OR li.search @@ to_tsquery('simple', :pq))"
        clauses.append(match)
    for name, col in (("sport", "li.sport"), ("school", "li.school"), ("channel", "li.channel_id"),
                      ("sponsor", "li.sponsor"), ("qc_state", "li.qc_state"),
                      ("series", "li.series_id"), ("asset_type", "COALESCE(li.asset_type, 'clip')")):
        val = getattr(f, name)
        if val is not None and name != skip:
            clauses.append(f"{col} = :{name}")
            params[name] = val
    if f.content_type is not None and skip != "content_type":
        clauses.append("(li.content_type = :content_type OR li.content_types @> ARRAY[:content_type]::text[])")
        params["content_type"] = f.content_type
    if f.category is not None and skip != "category":
        clauses.append("li.categories @> ARRAY[:category]::text[]")
        params["category"] = f.category
    if f.tag is not None and skip != "tag":
        clauses.append("li.tags @> ARRAY[:tag]::text[]")
        params["tag"] = f.tag
    if f.athlete and skip != "athlete":
        # The same rule as the athlete page's clip list (_FEATURES_HANDLES): a
        # tagged athlete, or a handle the app could not match, is theirs.
        clauses.append("""(EXISTS (SELECT 1 FROM jsonb_array_elements(li.athletes) a
                                   WHERE lower(ltrim(a->>'handle', '@')) = :athlete_handle
                                      OR a->>'id' = :athlete)
                           OR EXISTS (SELECT 1 FROM unnest(li.unresolved_handles) u
                                      WHERE lower(ltrim(u, '@')) = :athlete_handle))""")
        params["athlete"] = f.athlete.strip()
        params["athlete_handle"] = f.athlete.strip().lstrip("@").lower()
    if f.needs_tagging and skip != "qc_state":
        clauses.append(f"COALESCE(li.qc_state, '') <> '{READY}'")
    if f.posted_from:
        clauses.append("li.posted_at >= :posted_from")
        params["posted_from"] = f.posted_from
    if f.posted_to:
        clauses.append("li.posted_at < :posted_to_excl")
        params["posted_to_excl"] = f.posted_to + timedelta(days=1)
    if f.has_video is True:
        clauses.append("COALESCE(li.video_url, '') <> ''")
    elif f.has_video is False:
        clauses.append("COALESCE(li.video_url, '') = ''")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


Sort = Literal["relevance", "newest", "views", "engaged"]


@router.get("/", response_model=LibraryPage)
def list_library(
    f: Filters = Depends(_filters_dep),
    sort: Optional[Sort] = Query(None, description="relevance (default with q), newest (default), views, engaged"),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where, params = _where(f)
    sort = sort or ("relevance" if f.q else "newest")
    rank = "0"
    if f.q:
        rank = "ts_rank(li.search, websearch_to_tsquery('english', :q))"
        if "pq" in params:
            rank += " + ts_rank(li.search, to_tsquery('simple', :pq))"
    order = {
        "relevance": "rank DESC",
        "newest": "posted_at DESC NULLS LAST",
        "views": "perf_views DESC NULLS LAST",
        "engaged": "perf_interactions DESC NULLS LAST",
    }[sort]
    total = db.execute(text(f"SELECT COUNT(*) FROM library_items li {where}"), params).scalar()
    rows = db.execute(text(f"""
        SELECT * FROM (SELECT {rank} AS rank, {_FIELDS} {_FROM} {where}) AS x
        ORDER BY {order}, posted_at DESC NULLS LAST, content_id
        LIMIT :limit OFFSET :offset
    """), {**params, "limit": limit, "offset": offset}).fetchall()
    return LibraryPage(total=total, limit=limit, offset=offset,
                       items=link_athletes(db, [_item(r) for r in rows]))


class FacetValue(BaseModel):
    value: str
    label: str
    count: int


class Facets(BaseModel):
    sport: list[FacetValue]
    school: list[FacetValue]
    channel: list[FacetValue]
    content_type: list[FacetValue]
    category: list[FacetValue]
    sponsor: list[FacetValue]
    tag: list[FacetValue] = []
    series: list[FacetValue] = []        # value = series id, label = series name
    asset_type: list[FacetValue] = []
    qc_state: list[FacetValue]
    athlete: list[FacetValue] = []   # value = lowercase handle, label = name when the app sent one


# facet -> (value expression, label expression, FROM addition)
_FACETS = {
    "sport": ("li.sport", "li.sport", ""),
    "school": ("li.school", "li.school", ""),
    "channel": ("li.channel_id", "MAX(COALESCE(li.channel_name, li.channel_id))", ""),
    "content_type": ("ct.v", "ct.v",
                     """CROSS JOIN LATERAL unnest(CASE WHEN cardinality(li.content_types) > 0
                            THEN li.content_types ELSE ARRAY[li.content_type] END) AS ct(v)"""),
    "category": ("cat.v", "cat.v", "CROSS JOIN LATERAL unnest(li.categories) AS cat(v)"),
    "sponsor": ("li.sponsor", "li.sponsor", ""),
    "tag": ("tg.v", "tg.v", "CROSS JOIN LATERAL unnest(li.tags) AS tg(v)"),
    "series": ("li.series_id", "MAX(COALESCE(li.series_name, li.series_id))", ""),
    "asset_type": ("COALESCE(li.asset_type, 'clip')", "COALESCE(li.asset_type, 'clip')", ""),
    "qc_state": ("li.qc_state", "li.qc_state", ""),
    "athlete": ("lower(ltrim(ath.v->>'handle', '@'))",
                "MAX(COALESCE(NULLIF(ath.v->>'name', ''), '@' || ltrim(ath.v->>'handle', '@')))",
                "CROSS JOIN LATERAL jsonb_array_elements(li.athletes) AS ath(v)"),
}


@router.get("/facets", response_model=Facets)
def library_facets(f: Filters = Depends(_filters_dep), db: Session = Depends(get_db)):
    """Value counts for each filter, under the other current filters (a facet's
    own selection is left out so its other values stay pickable)."""
    out = {}
    for name, (value, label, join) in _FACETS.items():
        where, params = _where(f, skip=name)
        cond = f"{value} IS NOT NULL AND {value} <> ''"
        where = f"{where} AND {cond}" if where else f"WHERE {cond}"
        rows = db.execute(text(f"""
            SELECT {value} AS value, {label} AS label, COUNT(DISTINCT li.content_id) AS count
            FROM library_items li {join} {where}
            GROUP BY {value} ORDER BY count DESC, value LIMIT 200
        """), params).fetchall()
        out[name] = [FacetValue(value=r.value, label=r.label, count=r.count) for r in rows]
    return Facets(**out)


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    received_at: datetime
    stage: Optional[str]
    generated_at: Optional[datetime]
    received: int
    upserted: int
    removed: int
    ok: bool
    error: Optional[str]


class QcCount(BaseModel):
    qc_state: Optional[str]
    count: int


class LibraryStatus(BaseModel):
    last_run: Optional[SyncRunOut]
    last_ok_run: Optional[SyncRunOut]
    items: int                # live clips (not removed)
    removed: int
    needs_tagging: int        # live clips whose QC state is not ready
    by_qc_state: list[QcCount]


@router.get("/status", response_model=LibraryStatus)
def library_status(db: Session = Depends(get_db)):
    runs = db.query(LibrarySyncRun).order_by(LibrarySyncRun.received_at.desc(), LibrarySyncRun.id.desc())
    counts = db.execute(text(f"""
        SELECT COUNT(*) FILTER (WHERE NOT removed) AS items,
               COUNT(*) FILTER (WHERE removed) AS removed,
               COUNT(*) FILTER (WHERE NOT removed AND COALESCE(qc_state, '') <> '{READY}') AS needs_tagging
        FROM library_items
    """)).one()
    by_qc = db.execute(text("""
        SELECT qc_state, COUNT(*) AS count FROM library_items WHERE NOT removed
        GROUP BY qc_state ORDER BY count DESC, qc_state NULLS LAST
    """)).fetchall()
    return LibraryStatus(
        last_run=runs.first(),
        last_ok_run=runs.filter(LibrarySyncRun.ok.is_(True)).first(),
        items=counts.items, removed=counts.removed, needs_tagging=counts.needs_tagging,
        by_qc_state=[QcCount(qc_state=r.qc_state, count=r.count) for r in by_qc],
    )


@router.get("/{content_id}", response_model=LibraryItemOut)
def get_library_item(content_id: str, db: Session = Depends(get_db)):
    row = db.execute(text(f"SELECT {_FIELDS} {_FROM} WHERE li.content_id = :cid"), {"cid": content_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return link_athletes(db, [_item(row)])[0]
