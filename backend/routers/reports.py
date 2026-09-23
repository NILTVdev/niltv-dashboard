"""Generate a plain-text executive summary report for copy-pasting."""

import logging
from datetime import datetime, timedelta, timezone
from calendar import monthrange

from fastapi import APIRouter, Depends
from sqlalchemy import func as sqlfunc, text
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import (
    NiltvNetworkPost, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])

# The TrueBlueTV weekly/monthly reports read the shared network table filtered on
# the truebluetv channel tag (migration 026 merged trueblue_network_posts into it).
TB_TAG = "truebluetv"
TB = NiltvNetworkPost.collab_accounts.contains(TB_TAG)

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _fmt(n: int) -> str:
    """Format a number with commas: 1234567 → '1,234,567'."""
    return f"{n:,}"


def _pct_change(current: int, previous: int) -> str:
    if previous == 0:
        return "+∞%" if current > 0 else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def _week_bounds(date: datetime):
    """Return (monday, sunday) for the ISO week containing `date`."""
    d = date.date() if isinstance(date, datetime) else date
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


# ── helpers ───────────────────────────────────────────────


def _social_stats(db: Session, now: datetime):
    """Compute social (TrueBlue Network) stats."""
    # All-time
    alltime = db.query(
        sqlfunc.count(NiltvNetworkPost.id),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.projected_reach), 0),
        sqlfunc.min(NiltvNetworkPost.publish_time),
    ).filter(TB).one()

    alltime_posts = int(alltime[0])
    alltime_views = int(alltime[1])
    alltime_reach = int(alltime[2]) + int(alltime[3])
    earliest = alltime[4]

    # Monthly helper
    def _month_agg(year: int, month: int):
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        last_day = monthrange(year, month)[1]
        end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        row = db.query(
            sqlfunc.count(NiltvNetworkPost.id),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.projected_reach), 0),
        ).filter(
            TB,
            NiltvNetworkPost.publish_time >= first,
            NiltvNetworkPost.publish_time <= end,
        ).one()
        return {
            "posts": int(row[0]),
            "views": int(row[1]),
            "reach": int(row[2]) + int(row[3]),
        }

    # Weekly helper
    def _week_agg(start, end):
        s = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
        e = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
        row = db.query(
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0),
        ).filter(
            TB,
            NiltvNetworkPost.publish_time >= s,
            NiltvNetworkPost.publish_time <= e,
        ).one()
        return int(row[0])

    cur_year, cur_month = now.year, now.month

    # Current month
    cur_m = _month_agg(cur_year, cur_month)

    # Previous month
    prev_dt = (datetime(cur_year, cur_month, 1) - timedelta(days=1))
    prev_m = _month_agg(prev_dt.year, prev_dt.month)

    # Current week & previous week
    cur_mon, cur_sun = _week_bounds(now)
    prev_mon = cur_mon - timedelta(days=7)
    prev_sun = cur_sun - timedelta(days=7)
    cur_week_views = _week_agg(cur_mon, cur_sun)
    prev_week_views = _week_agg(prev_mon, prev_sun)

    return {
        "earliest": earliest,
        "alltime_posts": alltime_posts,
        "alltime_views": alltime_views,
        "alltime_reach": alltime_reach,
        "cur_month": cur_m,
        "prev_month": prev_m,
        "cur_month_name": MONTH_NAMES[cur_month],
        "prev_month_name": MONTH_NAMES[prev_dt.month],
        "cur_week_views": cur_week_views,
        "prev_week_views": prev_week_views,
    }


def _gsc_stats(db: Session, now: datetime):
    """Compute GSC stats."""
    cur_year, cur_month = now.year, now.month

    def _month_gsc(year: int, month: int):
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        last_day = monthrange(year, month)[1]
        end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        row = db.query(
            sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.clicks), 0),
            sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.impressions), 0),
            sqlfunc.coalesce(sqlfunc.avg(GSCDailyTotal.ctr), 0),
            sqlfunc.coalesce(sqlfunc.avg(GSCDailyTotal.position), 0),
        ).filter(
            GSCDailyTotal.date >= first,
            GSCDailyTotal.date <= end,
        ).one()
        return {
            "clicks": int(row[0]),
            "impressions": int(row[1]),
            "avg_ctr": float(row[2]),
            "avg_position": float(row[3]),
        }

    def _week_gsc(start, end):
        s = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
        e = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
        row = db.query(
            sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.clicks), 0),
            sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.impressions), 0),
        ).filter(
            GSCDailyTotal.date >= s,
            GSCDailyTotal.date <= e,
        ).one()
        return {"clicks": int(row[0]), "impressions": int(row[1])}

    cur_m = _month_gsc(cur_year, cur_month)

    prev_dt = datetime(cur_year, cur_month, 1) - timedelta(days=1)
    prev_m = _month_gsc(prev_dt.year, prev_dt.month)

    cur_mon, cur_sun = _week_bounds(now)
    prev_mon = cur_mon - timedelta(days=7)
    prev_sun = cur_sun - timedelta(days=7)
    cur_w = _week_gsc(cur_mon, cur_sun)
    prev_w = _week_gsc(prev_mon, prev_sun)

    return {
        "cur_month": cur_m,
        "prev_month": prev_m,
        "cur_month_name": MONTH_NAMES[cur_month],
        "prev_month_name": MONTH_NAMES[prev_dt.month],
        "cur_week": cur_w,
        "prev_week": prev_w,
    }


def _build_report(social, gsc, now: datetime) -> str:
    """Build the plain-text report string."""
    today_str = now.strftime("%B %d, %Y")
    lines: list[str] = []

    # ── Header ──
    lines.append(f"TrueBlue TV — Performance Report (as of {today_str})")
    lines.append("=" * 60)

    # ── Social: All-Time ──
    earliest = social["earliest"]
    start_label = earliest.strftime("%b %Y") if earliest else "N/A"
    lines.append("")
    lines.append(f"SOCIAL MEDIA — ALL-TIME ({start_label} – {now.strftime('%b %d, %Y')})")
    lines.append(f"  Total Posts: {_fmt(social['alltime_posts'])}")
    lines.append(f"  Total Views: {_fmt(social['alltime_views'])}")
    lines.append(f"  Projected Reach: ~{_fmt(social['alltime_reach'])} unique accounts")

    # ── Social: Previous Month ──
    prev = social["prev_month"]
    lines.append("")
    lines.append(f"{social['prev_month_name'].upper()} {now.year if now.month > 1 else now.year - 1} — FULL MONTH")
    lines.append(f"  Total Views: {_fmt(prev['views'])}")
    lines.append(f"  Projected Reach: ~{_fmt(prev['reach'])} unique accounts")
    lines.append(f"  Posts: {_fmt(prev['posts'])}")

    # ── Social: Current Month ──
    cur = social["cur_month"]
    lines.append("")
    lines.append(f"{social['cur_month_name'].upper()} {now.year} — MONTH TO DATE (through {today_str})")
    lines.append(f"  Total Views: {_fmt(cur['views'])}")
    lines.append(f"  Projected Reach: ~{_fmt(cur['reach'])} unique accounts")
    lines.append(f"  Posts: {_fmt(cur['posts'])}")
    lines.append(f"  Month-over-Month Views: {_pct_change(cur['views'], prev['views'])}")

    # Week-over-week
    lines.append(f"  Week-over-Week Views: {_pct_change(social['cur_week_views'], social['prev_week_views'])} "
                 f"({_fmt(social['cur_week_views'])} vs {_fmt(social['prev_week_views'])})")

    # ── GSC ──
    lines.append("")
    lines.append("=" * 60)
    lines.append("WEB SEARCH (Google Search Console)")
    lines.append("=" * 60)

    gsc_cur = gsc["cur_month"]
    gsc_prev = gsc["prev_month"]
    gsc_cw = gsc["cur_week"]
    gsc_pw = gsc["prev_week"]

    lines.append("")
    lines.append(f"{gsc['cur_month_name'].upper()} {now.year} — MONTH TO DATE")
    lines.append(f"  Impressions: {_fmt(gsc_cur['impressions'])}")
    lines.append(f"  Clicks: {_fmt(gsc_cur['clicks'])}")
    lines.append(f"  Avg CTR: {gsc_cur['avg_ctr']:.1%}")
    lines.append(f"  Avg Position: {gsc_cur['avg_position']:.1f}")

    lines.append("")
    lines.append(f"{gsc['prev_month_name'].upper()} {now.year if now.month > 1 else now.year - 1} — FULL MONTH")
    lines.append(f"  Impressions: {_fmt(gsc_prev['impressions'])}")
    lines.append(f"  Clicks: {_fmt(gsc_prev['clicks'])}")

    lines.append("")
    lines.append("COMPARISONS")
    lines.append(f"  Month-over-Month Impressions: {_pct_change(gsc_cur['impressions'], gsc_prev['impressions'])}")
    lines.append(f"  Month-over-Month Clicks: {_pct_change(gsc_cur['clicks'], gsc_prev['clicks'])}")
    lines.append(f"  Week-over-Week Impressions: {_pct_change(gsc_cw['impressions'], gsc_pw['impressions'])} "
                 f"({_fmt(gsc_cw['impressions'])} vs {_fmt(gsc_pw['impressions'])})")
    lines.append(f"  Week-over-Week Clicks: {_pct_change(gsc_cw['clicks'], gsc_pw['clicks'])} "
                 f"({_fmt(gsc_cw['clicks'])} vs {_fmt(gsc_pw['clicks'])})")

    return "\n".join(lines)


@router.get("/summary")
def generate_report(db: Session = Depends(get_db)):
    """Generate a structured performance summary report."""
    now = datetime.now(tz=timezone.utc)
    social = _social_stats(db, now)
    gsc = _gsc_stats(db, now)
    report = _build_report(social, gsc, now)

    earliest = social["earliest"]
    return {
        "report": report,
        "date": now.strftime("%B %d, %Y"),
        "social": {
            "start_label": earliest.strftime("%b %Y") if earliest else "N/A",
            "alltime_posts": social["alltime_posts"],
            "alltime_views": social["alltime_views"],
            "alltime_reach": social["alltime_reach"],
            "cur_month_name": social["cur_month_name"],
            "prev_month_name": social["prev_month_name"],
            "cur_month": social["cur_month"],
            "prev_month": social["prev_month"],
            "cur_week_views": social["cur_week_views"],
            "prev_week_views": social["prev_week_views"],
        },
        "gsc": {
            "cur_month_name": gsc["cur_month_name"],
            "prev_month_name": gsc["prev_month_name"],
            "cur_month": gsc["cur_month"],
            "prev_month": gsc["prev_month"],
            "cur_week": gsc["cur_week"],
            "prev_week": gsc["prev_week"],
        },
    }


# ── Monthly Report ────────────────────────────────────────


def _month_range(year: int, month: int):
    """Return (first, last) datetimes for a given month."""
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return first, end


def _monthly_top_posts(db: Session, year: int, month: int):
    """Top 5 posts by views and top 5 by engagement for a given month."""
    first, end = _month_range(year, month)

    base = db.query(NiltvNetworkPost).filter(
        TB,
        NiltvNetworkPost.publish_time >= first,
        NiltvNetworkPost.publish_time <= end,
    )

    def _serialize(p):
        return {
            "id": p.id,
            "account_username": p.account_username,
            "account_name": p.account_name,
            "description": (p.description or "")[:120],
            "post_type": p.post_type,
            "permalink": p.permalink,
            "publish_time": p.publish_time.isoformat() if p.publish_time else None,
            "views": p.views or 0,
            "likes": p.likes or 0,
            "comments": p.comments or 0,
            "shares": p.shares or 0,
            "saves": p.saves or 0,
            "reach": p.reach or 0,
            "engagement": (p.likes or 0) + (p.comments or 0) + (p.shares or 0) + (p.saves or 0),
        }

    top_views = (
        base.order_by(NiltvNetworkPost.views.desc().nullslast())
        .limit(5)
        .all()
    )

    top_engagement = (
        base.order_by(
            (
                sqlfunc.coalesce(NiltvNetworkPost.likes, 0)
                + sqlfunc.coalesce(NiltvNetworkPost.comments, 0)
                + sqlfunc.coalesce(NiltvNetworkPost.shares, 0)
                + sqlfunc.coalesce(NiltvNetworkPost.saves, 0)
            ).desc()
        )
        .limit(5)
        .all()
    )

    return {
        "top_by_views": [_serialize(p) for p in top_views],
        "top_by_engagement": [_serialize(p) for p in top_engagement],
    }


def _monthly_gsc_highlights(db: Session, year: int, month: int):
    """Top pages by impressions for a given month."""
    first, end = _month_range(year, month)

    # Top pages sorted by impressions
    page_rows = (
        db.query(
            GSCPageSnapshot.page,
            sqlfunc.sum(GSCPageSnapshot.clicks).label("clicks"),
            sqlfunc.sum(GSCPageSnapshot.impressions).label("impressions"),
            sqlfunc.avg(GSCPageSnapshot.ctr).label("avg_ctr"),
            sqlfunc.avg(GSCPageSnapshot.position).label("avg_position"),
        )
        .filter(GSCPageSnapshot.date >= first, GSCPageSnapshot.date <= end)
        .group_by(GSCPageSnapshot.page)
        .order_by(sqlfunc.sum(GSCPageSnapshot.impressions).desc())
        .limit(10)
        .all()
    )

    return {
        "top_pages": [
            {
                "page": r.page,
                "clicks": int(r.clicks or 0),
                "impressions": int(r.impressions or 0),
                "avg_ctr": float(r.avg_ctr or 0),
                "avg_position": round(float(r.avg_position or 0), 1),
            }
            for r in page_rows
        ],
    }


def _monthly_gsc_daily(db: Session, year: int, month: int):
    """Daily GSC clicks + impressions for charting."""
    first, end = _month_range(year, month)
    rows = (
        db.query(GSCDailyTotal.date, GSCDailyTotal.clicks, GSCDailyTotal.impressions)
        .filter(GSCDailyTotal.date >= first, GSCDailyTotal.date <= end)
        .order_by(GSCDailyTotal.date)
        .all()
    )
    return [
        {
            "date": r.date.strftime("%Y-%m-%d") if r.date else None,
            "clicks": int(r.clicks or 0),
            "impressions": int(r.impressions or 0),
        }
        for r in rows
    ]


def _monthly_social_daily(db: Session, year: int, month: int):
    """Daily social views + engagement aggregated by publish date for charting."""
    first, end = _month_range(year, month)
    rows = (
        db.query(
            sqlfunc.date_trunc("day", NiltvNetworkPost.publish_time).label("day"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0).label("views"),
            (
                sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0)
                + sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0)
                + sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0)
                + sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0)
            ).label("engagement"),
        )
        .filter(
            TB,
            NiltvNetworkPost.publish_time >= first,
            NiltvNetworkPost.publish_time <= end,
        )
        .group_by(sqlfunc.date_trunc("day", NiltvNetworkPost.publish_time))
        .order_by(sqlfunc.date_trunc("day", NiltvNetworkPost.publish_time))
        .all()
    )
    return [
        {
            "date": r.day.strftime("%Y-%m-%d") if r.day else None,
            "views": max(0, int(r.views)),
            "engagement": max(0, int(r.engagement)),
        }
        for r in rows
    ]


def _alltime_network_metrics(db: Session):
    """All-time network views + reach, one point per month (latest snapshot day)."""
    sql = text("""
        WITH posts AS (
            SELECT id FROM niltv_network_posts
            WHERE ',' || COALESCE(collab_accounts, '') || ',' LIKE :tag
        ),
        snapshot_dates AS (
            SELECT DISTINCT date_trunc('day', s.captured_at)::date AS dt
            FROM niltv_network_post_snapshots s
            JOIN posts p ON p.id = s.network_post_id
        ),
        daily AS (
            SELECT
                sd.dt                           AS date,
                SUM(ls.views)                   AS total_views,
                SUM(ls.reach)                   AS total_reach,
                SUM(ls.projected_reach)         AS total_projected_reach
            FROM snapshot_dates sd
            CROSS JOIN posts p
            LEFT JOIN LATERAL (
                SELECT s.views, s.reach, s.projected_reach
                FROM niltv_network_post_snapshots s
                WHERE s.network_post_id = p.id
                  AND s.captured_at < sd.dt + INTERVAL '1 day'
                ORDER BY s.captured_at DESC
                LIMIT 1
            ) ls ON true
            WHERE ls.views IS NOT NULL
            GROUP BY sd.dt
        ),
        monthly AS (
            SELECT
                date_trunc('month', date)::date AS month,
                MAX(date)                       AS latest_day
            FROM daily
            GROUP BY date_trunc('month', date)
        )
        SELECT d.date, d.total_views, d.total_reach, d.total_projected_reach
        FROM monthly m
        JOIN daily d ON d.date = m.latest_day
        ORDER BY d.date
    """)
    rows = db.execute(sql, {"tag": f"%,{TB_TAG},%"}).fetchall()
    return [
        {
            "date": r.date.isoformat() if r.date else None,
            "views": int(r.total_views or 0),
            "reach": int(r.total_reach or 0) + int(r.total_projected_reach or 0),
        }
        for r in rows
    ]


def _alltime_gsc_monthly(db: Session):
    """All-time GSC impressions aggregated per month (sum of daily)."""
    rows = (
        db.query(
            sqlfunc.date_trunc("month", GSCDailyTotal.date).label("month"),
            sqlfunc.sum(GSCDailyTotal.impressions).label("impressions"),
        )
        .group_by(sqlfunc.date_trunc("month", GSCDailyTotal.date))
        .order_by(sqlfunc.date_trunc("month", GSCDailyTotal.date))
        .all()
    )
    return [
        {
            "date": r.month.strftime("%Y-%m-%d") if r.month else None,
            "impressions": int(r.impressions or 0),
        }
        for r in rows
    ]


def _alltime_stats(db: Session):
    """All-time social + GSC stats."""
    social = db.query(
        sqlfunc.count(NiltvNetworkPost.id),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.projected_reach), 0),
        sqlfunc.count(sqlfunc.distinct(NiltvNetworkPost.account_username)),
    ).filter(TB).one()

    gsc = db.query(
        sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.impressions), 0),
    ).one()

    return {
        "social": {
            "total_posts": int(social[0]),
            "total_views": int(social[1]),
            "total_likes": int(social[2]),
            "total_comments": int(social[3]),
            "total_shares": int(social[4]),
            "total_saves": int(social[5]),
            "total_reach": int(social[6]) + int(social[7]),
            "unique_accounts": int(social[8]),
        },
        "gsc": {
            "total_impressions": int(gsc[0]),
        },
    }


def _monthly_summary_stats(db: Session, year: int, month: int):
    """Aggregate social + GSC stats for the month."""
    first, end = _month_range(year, month)

    # Social
    social = db.query(
        sqlfunc.count(NiltvNetworkPost.id),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.reach), 0),
        sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.projected_reach), 0),
        sqlfunc.count(sqlfunc.distinct(NiltvNetworkPost.account_username)),
    ).filter(
        TB,
        NiltvNetworkPost.publish_time >= first,
        NiltvNetworkPost.publish_time <= end,
    ).one()

    # GSC
    gsc = db.query(
        sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.clicks), 0),
        sqlfunc.coalesce(sqlfunc.sum(GSCDailyTotal.impressions), 0),
        sqlfunc.coalesce(sqlfunc.avg(GSCDailyTotal.ctr), 0),
        sqlfunc.coalesce(sqlfunc.avg(GSCDailyTotal.position), 0),
    ).filter(
        GSCDailyTotal.date >= first,
        GSCDailyTotal.date <= end,
    ).one()

    return {
        "social": {
            "total_posts": int(social[0]),
            "total_views": int(social[1]),
            "total_likes": int(social[2]),
            "total_comments": int(social[3]),
            "total_shares": int(social[4]),
            "total_saves": int(social[5]),
            "total_reach": int(social[6]) + int(social[7]),
            "unique_accounts": int(social[8]),
        },
        "gsc": {
            "total_clicks": int(gsc[0]),
            "total_impressions": int(gsc[1]),
            "avg_ctr": float(gsc[2]),
            "avg_position": round(float(gsc[3]), 1),
        },
    }


@router.get("/monthly")
def monthly_report(
    year: int = 0,
    month: int = 0,
    db: Session = Depends(get_db),
):
    """Generate a structured monthly report with top posts and GSC highlights."""
    now = datetime.now(tz=timezone.utc)
    if year == 0 or month == 0:
        # Default to previous month if we're in the first week, otherwise current month
        if now.day <= 7:
            prev = datetime(now.year, now.month, 1) - timedelta(days=1)
            year, month = prev.year, prev.month
        else:
            year, month = now.year, now.month

    month_name = MONTH_NAMES[month]
    stats = _monthly_summary_stats(db, year, month)
    alltime = _alltime_stats(db)
    alltime_gsc_daily = _alltime_gsc_monthly(db)
    alltime_network = _alltime_network_metrics(db)
    top_posts = _monthly_top_posts(db, year, month)
    gsc_highlights = _monthly_gsc_highlights(db, year, month)
    gsc_daily = _monthly_gsc_daily(db, year, month)
    social_daily = _monthly_social_daily(db, year, month)

    # Previous month stats for MoM comparison
    prev_dt = datetime(year, month, 1) - timedelta(days=1)
    prev_stats = _monthly_summary_stats(db, prev_dt.year, prev_dt.month)
    prev_month_name = MONTH_NAMES[prev_dt.month]

    return {
        "year": year,
        "month": month,
        "month_name": month_name,
        "stats": stats,
        "alltime": alltime,
        "alltime_gsc_daily": alltime_gsc_daily,
        "alltime_network": alltime_network,
        "prev_stats": prev_stats,
        "prev_month_name": prev_month_name,
        "top_posts": top_posts,
        "gsc": gsc_highlights,
        "gsc_daily": gsc_daily,
        "social_daily": social_daily,
    }
