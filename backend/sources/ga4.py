"""
Google Analytics 4 Data API client.

Uses the google-analytics-data Python client with a service account
to pull daily aggregate metrics (sessions, users, pageviews, bounce rate,
engagement rate) broken down by source/medium.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Dimension, Metric,
)
from google.oauth2 import service_account

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


@dataclass
class GA4Row:
    date: date
    sessions: int
    total_users: int
    pageviews: int
    bounce_rate: float
    engagement_rate: float
    source: Optional[str]
    medium: Optional[str]


def fetch_ga4_daily(
    start_date: str, end_date: str, property_id: Optional[str] = None
) -> list[GA4Row]:
    """
    Fetch GA4 metrics for the given date range.

    start_date / end_date: "YYYY-MM-DD" strings.
    property_id: GA4 property (e.g. "properties/123"); defaults to the primary
        site's configured property.
    Returns one GA4Row per (date, source, medium) combination.
    """
    prop = property_id or settings.ga4_property_id
    credentials = service_account.Credentials.from_service_account_file(
        settings.ga4_credentials_json, scopes=SCOPES
    )
    client = BetaAnalyticsDataClient(credentials=credentials)

    request = RunReportRequest(
        property=prop,
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[
            Dimension(name="date"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="screenPageViews"),
            Metric(name="bounceRate"),
            Metric(name="engagementRate"),
        ],
    )

    response = client.run_report(request)
    rows: list[GA4Row] = []
    for row in response.rows:
        d = row.dimension_values
        m = row.metric_values
        rows.append(GA4Row(
            date=datetime.strptime(d[0].value, "%Y%m%d").date(),
            sessions=int(m[0].value),
            total_users=int(m[1].value),
            pageviews=int(m[2].value),
            bounce_rate=float(m[3].value),
            engagement_rate=float(m[4].value),
            source=d[1].value if d[1].value != "(not set)" else None,
            medium=d[2].value if d[2].value != "(not set)" else None,
        ))

    logger.info(f"GA4: fetched {len(rows)} rows for {start_date} to {end_date}")
    return rows
