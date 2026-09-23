"""
Google Search Console API client.

Three separate pulls to avoid dimensional anonymization:
  1. Daily totals (date-only) — accurate aggregate clicks/impressions
  2. By query (date + query) — for top search queries
  3. By page (date + page) — for top performing pages

All calls filter to type=web to match the GSC web interface.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
ROW_LIMIT = 25000  # Max rows per API call


@dataclass
class GSCDailyTotal:
    """Accurate daily totals — no dimensional anonymization."""
    date: date
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCQueryRow:
    """Per-query metrics (may be anonymized for low-volume queries)."""
    date: date
    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCPageRow:
    """Per-page metrics (may be anonymized for low-volume pages)."""
    date: date
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float


def _build_service():
    creds_file = settings.gsc_credentials_json or settings.ga4_credentials_json
    credentials = service_account.Credentials.from_service_account_file(
        creds_file, scopes=SCOPES
    )
    return build("searchconsole", "v1", credentials=credentials)


def _paginated_query(service, site_url: str, body: dict) -> list[dict]:
    """Execute a GSC searchanalytics query with pagination."""
    all_rows: list[dict] = []
    start_row = 0

    while True:
        body["startRow"] = start_row
        body["rowLimit"] = ROW_LIMIT

        response = service.searchanalytics().query(
            siteUrl=site_url, body=body
        ).execute()

        rows = response.get("rows", [])
        if not rows:
            break

        all_rows.extend(rows)

        if len(rows) < ROW_LIMIT:
            break

        start_row += ROW_LIMIT
        logger.info(f"GSC: paginating, fetched {len(all_rows)} rows so far")

    return all_rows


def fetch_gsc_daily_totals(
    start_date: str, end_date: str, site_url: Optional[str] = None
) -> list[GSCDailyTotal]:
    """
    Fetch accurate daily totals (clicks, impressions, CTR, position).

    Uses only the "date" dimension — no query/page breakdown — so Google
    doesn't anonymize any data. This matches the GSC web UI totals.

    site_url defaults to the primary site's configured property.
    """
    service = _build_service()
    url = site_url or settings.gsc_site_url

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_totals: list[GSCDailyTotal] = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        body = {
            "startDate": day_str,
            "endDate": day_str,
            "dimensions": ["date"],
            "type": "web",
        }

        rows = _paginated_query(service, url, body)
        for row in rows:
            all_totals.append(GSCDailyTotal(
                date=datetime.strptime(row["keys"][0], "%Y-%m-%d").date(),
                clicks=int(row.get("clicks", 0)),
                impressions=int(row.get("impressions", 0)),
                ctr=float(row.get("ctr", 0.0)),
                position=float(row.get("position", 0.0)),
            ))

        current += timedelta(days=1)

    logger.info(f"GSC totals: {len(all_totals)} days for {start_date} to {end_date}")
    return all_totals


def fetch_gsc_by_query(
    start_date: str, end_date: str, site_url: Optional[str] = None
) -> list[GSCQueryRow]:
    """
    Fetch per-query metrics. Uses "date" + "query" dimensions.

    Some low-volume queries will be anonymized/dropped by Google — this is
    expected. Use daily totals for accurate aggregate numbers.
    """
    service = _build_service()
    url = site_url or settings.gsc_site_url

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_rows: list[GSCQueryRow] = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        body = {
            "startDate": day_str,
            "endDate": day_str,
            "dimensions": ["date", "query"],
            "type": "web",
        }

        rows = _paginated_query(service, url, body)
        for row in rows:
            keys = row["keys"]
            all_rows.append(GSCQueryRow(
                date=datetime.strptime(keys[0], "%Y-%m-%d").date(),
                query=keys[1],
                clicks=int(row.get("clicks", 0)),
                impressions=int(row.get("impressions", 0)),
                ctr=float(row.get("ctr", 0.0)),
                position=float(row.get("position", 0.0)),
            ))

        current += timedelta(days=1)

    logger.info(f"GSC queries: {len(all_rows)} rows for {start_date} to {end_date}")
    return all_rows


def fetch_gsc_by_page(
    start_date: str, end_date: str, site_url: Optional[str] = None
) -> list[GSCPageRow]:
    """
    Fetch per-page metrics. Uses "date" + "page" dimensions.

    Some low-volume pages will be anonymized/dropped by Google — this is
    expected. Use daily totals for accurate aggregate numbers.
    """
    service = _build_service()
    url = site_url or settings.gsc_site_url

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_rows: list[GSCPageRow] = []
    current = start
    while current <= end:
        day_str = current.isoformat()
        body = {
            "startDate": day_str,
            "endDate": day_str,
            "dimensions": ["date", "page"],
            "type": "web",
        }

        rows = _paginated_query(service, url, body)
        for row in rows:
            keys = row["keys"]
            all_rows.append(GSCPageRow(
                date=datetime.strptime(keys[0], "%Y-%m-%d").date(),
                page=keys[1],
                clicks=int(row.get("clicks", 0)),
                impressions=int(row.get("impressions", 0)),
                ctr=float(row.get("ctr", 0.0)),
                position=float(row.get("position", 0.0)),
            ))

        current += timedelta(days=1)

    logger.info(f"GSC pages: {len(all_rows)} rows for {start_date} to {end_date}")
    return all_rows
