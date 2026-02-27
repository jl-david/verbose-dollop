"""LinkedIn Ads connector – pulls campaign analytics via the LinkedIn Marketing API."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import requests
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseConnector


class LinkedInAdsConnector(BaseConnector):
    """
    Fetches LinkedIn Ads performance using the LinkedIn Marketing API v2.

    Required env vars
    -----------------
    LINKEDIN_ACCESS_TOKEN
    LINKEDIN_AD_ACCOUNT_ID   (numeric sponsor account ID)
    """

    PLATFORM = "linkedin_ads"
    BASE_URL = "https://api.linkedin.com/v2"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._token = os.environ["LINKEDIN_ACCESS_TOKEN"]
        self._account_id = os.environ["LINKEDIN_AD_ACCOUNT_ID"]
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        # Step 1 – get all campaigns for the account
        campaigns = self._get_campaigns()

        rows: list[dict] = []
        for campaign in campaigns:
            campaign_id = str(campaign["id"])
            campaign_name = campaign.get("name", "")
            stats = self._get_campaign_analytics(campaign_id, start_date, end_date)
            for stat in stats:
                date_str = self._parse_linkedin_date(stat.get("dateRange", {}))
                rows.append({
                    "date": date_str,
                    "platform": self.PLATFORM,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                    "impressions": self._safe_int(stat.get("impressions", 0)),
                    "clicks": self._safe_int(stat.get("clicks", 0)),
                    "spend": self._safe_float(
                        stat.get("costInLocalCurrency", 0)
                    ),
                    "conversions": self._safe_float(
                        stat.get("externalWebsiteConversions", 0)
                    ),
                    "leads": self._safe_int(stat.get("leads", 0)),
                    "video_views": self._safe_int(stat.get("videoViews", 0)),
                    "unique_impressions": self._safe_int(
                        stat.get("approximateUniqueImpressions", 0)
                    ),
                })

        df = pd.DataFrame(rows)
        if df.empty:
            return self._empty_frame()

        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # ------------------------------------------------------------------ #

    def _get_campaigns(self) -> list[dict]:
        url = f"{self.BASE_URL}/adCampaignsV2"
        params = {
            "q": "search",
            "search.account.values[0]": f"urn:li:sponsoredAccount:{self._account_id}",
            "count": 200,
        }
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("elements", [])

    def _get_campaign_analytics(
        self,
        campaign_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        url = f"{self.BASE_URL}/adAnalyticsV2"
        params = {
            "q": "analytics",
            "pivot": "CAMPAIGN",
            "dateRange.start.day": start_date.day,
            "dateRange.start.month": start_date.month,
            "dateRange.start.year": start_date.year,
            "dateRange.end.day": end_date.day,
            "dateRange.end.month": end_date.month,
            "dateRange.end.year": end_date.year,
            "timeGranularity": "DAILY",
            "campaigns[0]": f"urn:li:sponsoredCampaign:{campaign_id}",
            "fields": (
                "dateRange,impressions,clicks,costInLocalCurrency,"
                "leads,externalWebsiteConversions,videoViews,"
                "approximateUniqueImpressions"
            ),
        }
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json().get("elements", [])

    @staticmethod
    def _parse_linkedin_date(date_range: dict) -> str:
        """Convert LinkedIn dateRange dict to ISO date string."""
        start = date_range.get("start", {})
        y = start.get("year", 1970)
        m = start.get("month", 1)
        d = start.get("day", 1)
        return f"{y:04d}-{m:02d}-{d:02d}"

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self.REQUIRED_COLUMNS + [
            "leads", "video_views", "unique_impressions",
        ])
