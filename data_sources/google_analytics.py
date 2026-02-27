"""Google Analytics 4 connector – pulls session & conversion data via the Data API."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseConnector


class GoogleAnalyticsConnector(BaseConnector):
    """
    Fetches GA4 performance data using the google-analytics-data client.

    Required env vars
    -----------------
    GA4_PROPERTY_ID                 (numeric property ID, e.g. 123456789)
    GOOGLE_APPLICATION_CREDENTIALS  (path to service account JSON)
    """

    PLATFORM = "google_analytics"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._property_id = os.environ["GA4_PROPERTY_ID"]
        self._client = self._build_client()

    # ------------------------------------------------------------------ #

    def _build_client(self):
        from google.analytics.data_v1beta import BetaAnalyticsDataClient  # type: ignore

        return BetaAnalyticsDataClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        from google.analytics.data_v1beta.types import (  # type: ignore
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
            OrderBy,
        )

        cfg = self.config.get("google_analytics", {})
        dimensions = cfg.get("dimensions", [
            "date", "sessionSource", "sessionMedium",
            "sessionCampaignName", "deviceCategory", "country",
        ])
        metrics = cfg.get("metrics", [
            "sessions", "totalUsers", "newUsers", "bounceRate",
            "averageSessionDuration", "screenPageViews", "conversions",
            "totalRevenue", "engagementRate",
        ])

        request = RunReportRequest(
            property=f"properties/{self._property_id}",
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )],
            order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
            limit=100_000,
        )

        response = self._client.run_report(request)

        dim_names = [h.name for h in response.dimension_headers]
        met_names = [h.name for h in response.metric_headers]

        rows: list[dict] = []
        for row in response.rows:
            dims = {dim_names[i]: v.value for i, v in enumerate(row.dimension_values)}
            mets = {met_names[i]: v.value for i, v in enumerate(row.metric_values)}

            rows.append({
                "date": dims.get("date"),
                "platform": self.PLATFORM,
                # GA4 has no campaign_id at session level; use source/medium
                "campaign_id": f"{dims.get('sessionSource','')}/{dims.get('sessionMedium','')}",
                "campaign_name": dims.get("sessionCampaignName", "(not set)"),
                "source": dims.get("sessionSource", ""),
                "medium": dims.get("sessionMedium", ""),
                "device_category": dims.get("deviceCategory", ""),
                "country": dims.get("country", ""),
                # required columns
                "impressions": 0,       # not available in GA4 session data
                "clicks": 0,
                "spend": 0.0,
                # analytics metrics
                "sessions": self._safe_int(mets.get("sessions", 0)),
                "total_users": self._safe_int(mets.get("totalUsers", 0)),
                "new_users": self._safe_int(mets.get("newUsers", 0)),
                "bounce_rate": self._safe_float(mets.get("bounceRate", 0)),
                "avg_session_duration": self._safe_float(
                    mets.get("averageSessionDuration", 0)
                ),
                "pageviews": self._safe_int(mets.get("screenPageViews", 0)),
                "conversions": self._safe_float(mets.get("conversions", 0)),
                "revenue": self._safe_float(mets.get("totalRevenue", 0)),
                "engagement_rate": self._safe_float(mets.get("engagementRate", 0)),
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return self._empty_frame()

        # GA4 returns date as YYYYMMDD string
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        return df

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self.REQUIRED_COLUMNS + [
            "source", "medium", "device_category", "country",
            "sessions", "total_users", "new_users", "bounce_rate",
            "avg_session_duration", "pageviews", "revenue", "engagement_rate",
        ])
