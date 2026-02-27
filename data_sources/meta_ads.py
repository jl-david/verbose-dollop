"""Meta Ads connector – pulls Facebook & Instagram ad performance via the Marketing API."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseConnector


class MetaAdsConnector(BaseConnector):
    """
    Fetches Meta (Facebook / Instagram) Ads performance using the
    facebook-business SDK.

    Required env vars
    -----------------
    META_APP_ID
    META_APP_SECRET
    META_ACCESS_TOKEN       (long-lived system-user token)
    META_AD_ACCOUNT_ID      (act_XXXXXXXXX)
    """

    PLATFORM = "meta_ads"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._init_sdk()

    # ------------------------------------------------------------------ #

    def _init_sdk(self) -> None:
        from facebook_business.api import FacebookAdsApi  # type: ignore

        FacebookAdsApi.init(
            app_id=os.environ["META_APP_ID"],
            app_secret=os.environ["META_APP_SECRET"],
            access_token=os.environ["META_ACCESS_TOKEN"],
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        from facebook_business.adobjects.adaccount import AdAccount  # type: ignore
        from facebook_business.adobjects.adsinsights import AdsInsights  # type: ignore

        cfg = self.config.get("meta_ads", {})
        fields = cfg.get("fields", [
            "date_start", "campaign_id", "campaign_name",
            "adset_id", "adset_name", "ad_id", "ad_name",
            "impressions", "clicks", "spend", "reach", "frequency",
            "actions", "action_values", "cost_per_action_type",
            "cpm", "cpc", "ctr",
        ])

        params = {
            "time_range": {
                "since": start_date.isoformat(),
                "until": end_date.isoformat(),
            },
            "level": cfg.get("level", "ad"),
            "time_increment": 1,          # daily breakdown
            "limit": 500,
        }

        account = AdAccount(os.environ["META_AD_ACCOUNT_ID"])
        insights = account.get_insights(fields=fields, params=params)

        rows: list[dict] = []
        for insight in insights:
            row = {
                "date": insight.get("date_start"),
                "platform": self.PLATFORM,
                "campaign_id": insight.get("campaign_id", ""),
                "campaign_name": insight.get("campaign_name", ""),
                "adset_id": insight.get("adset_id", ""),
                "adset_name": insight.get("adset_name", ""),
                "ad_id": insight.get("ad_id", ""),
                "ad_name": insight.get("ad_name", ""),
                "impressions": self._safe_int(insight.get("impressions", 0)),
                "clicks": self._safe_int(insight.get("clicks", 0)),
                "spend": self._safe_float(insight.get("spend", 0)),
                "reach": self._safe_int(insight.get("reach", 0)),
                "frequency": self._safe_float(insight.get("frequency", 0)),
                "cpm": self._safe_float(insight.get("cpm", 0)),
                "cpc": self._safe_float(insight.get("cpc", 0)),
                "ctr": self._safe_float(insight.get("ctr", 0)),
            }

            # Unpack 'actions' list into named conversion keys
            conversions = 0.0
            revenue = 0.0
            for action in insight.get("actions", []):
                action_type = action.get("action_type", "")
                value = self._safe_float(action.get("value", 0))
                row[f"action_{action_type}"] = value
                if "purchase" in action_type:
                    conversions += value

            for av in insight.get("action_values", []):
                action_type = av.get("action_type", "")
                value = self._safe_float(av.get("value", 0))
                row[f"action_value_{action_type}"] = value
                if "purchase" in action_type:
                    revenue += value

            row["conversions"] = conversions
            row["conversions_value"] = revenue
            rows.append(row)

        df = pd.DataFrame(rows)
        if df.empty:
            return self._empty_frame()

        df["date"] = pd.to_datetime(df["date"]).dt.date
        # Fill any missing action columns with 0
        action_cols = [c for c in df.columns if c.startswith("action_")]
        df[action_cols] = df[action_cols].fillna(0)
        return df

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self.REQUIRED_COLUMNS + [
            "adset_id", "adset_name", "ad_id", "ad_name",
            "reach", "frequency", "cpm", "cpc", "ctr", "conversions_value",
        ])
