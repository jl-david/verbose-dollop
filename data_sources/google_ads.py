"""Google Ads connector – pulls campaign/ad-group performance via the Google Ads API."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseConnector


class GoogleAdsConnector(BaseConnector):
    """
    Fetches Google Ads performance data using the google-ads Python client.

    Required env vars
    -----------------
    GOOGLE_ADS_CLIENT_ID
    GOOGLE_ADS_CLIENT_SECRET
    GOOGLE_ADS_REFRESH_TOKEN
    GOOGLE_ADS_DEVELOPER_TOKEN
    GOOGLE_ADS_LOGIN_CUSTOMER_ID   (MCC account ID, no dashes)
    """

    PLATFORM = "google_ads"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._client = self._build_client()

    # ------------------------------------------------------------------ #

    def _build_client(self):
        from google.ads.googleads.client import GoogleAdsClient  # type: ignore

        credentials = {
            "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
            "use_proto_plus": True,
        }
        api_version = self.config.get("google_ads", {}).get("api_version", "v16")
        return GoogleAdsClient.load_from_dict(credentials, version=api_version)

    # ------------------------------------------------------------------ #

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        customer_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]
        ga_service = self._client.get_service("GoogleAdsService")

        query = f"""
            SELECT
              segments.date,
              campaign.id,
              campaign.name,
              campaign.status,
              ad_group.id,
              ad_group.name,
              segments.device,
              segments.ad_network_type,
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.conversions_value,
              metrics.view_through_conversions,
              metrics.ctr,
              metrics.average_cpc,
              metrics.average_cpm
            FROM campaign
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
              AND campaign.status != 'REMOVED'
        """

        response = ga_service.search_stream(customer_id=customer_id, query=query)

        rows: list[dict] = []
        for batch in response:
            for row in batch.results:
                rows.append({
                    "date": row.segments.date,
                    "platform": self.PLATFORM,
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "campaign_status": row.campaign.status.name,
                    "ad_group_id": str(row.ad_group.id),
                    "ad_group_name": row.ad_group.name,
                    "device": row.segments.device.name,
                    "network_type": row.segments.ad_network_type.name,
                    "impressions": self._safe_int(row.metrics.impressions),
                    "clicks": self._safe_int(row.metrics.clicks),
                    # cost_micros → dollars
                    "spend": round(self._safe_float(row.metrics.cost_micros) / 1_000_000, 4),
                    "conversions": self._safe_float(row.metrics.conversions),
                    "conversions_value": self._safe_float(row.metrics.conversions_value),
                    "view_through_conversions": self._safe_int(
                        row.metrics.view_through_conversions
                    ),
                    "ctr": self._safe_float(row.metrics.ctr),
                    "average_cpc": round(
                        self._safe_float(row.metrics.average_cpc) / 1_000_000, 4
                    ),
                    "average_cpm": round(
                        self._safe_float(row.metrics.average_cpm) / 1_000_000, 4
                    ),
                })

        df = pd.DataFrame(rows)
        if df.empty:
            return self._empty_frame()

        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def _empty_frame(self) -> pd.DataFrame:
        cols = self.REQUIRED_COLUMNS + [
            "campaign_status", "ad_group_id", "ad_group_name",
            "device", "network_type", "conversions_value",
            "view_through_conversions", "ctr", "average_cpc", "average_cpm",
        ]
        return pd.DataFrame(columns=cols)
