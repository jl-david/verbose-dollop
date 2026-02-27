"""Twitter / X Ads connector – pulls campaign stats via the Twitter Ads API."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseConnector


class TwitterAdsConnector(BaseConnector):
    """
    Fetches Twitter/X Ads performance using the tweepy Twitter Ads API wrapper.

    Required env vars
    -----------------
    TWITTER_CONSUMER_KEY
    TWITTER_CONSUMER_SECRET
    TWITTER_ACCESS_TOKEN
    TWITTER_ACCESS_TOKEN_SECRET
    TWITTER_AD_ACCOUNT_ID           (18-char alphanumeric)
    """

    PLATFORM = "twitter_ads"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._account_id = os.environ["TWITTER_AD_ACCOUNT_ID"]
        self._client = self._build_client()

    # ------------------------------------------------------------------ #

    def _build_client(self):
        import tweepy  # type: ignore

        auth = tweepy.OAuth1UserHandler(
            consumer_key=os.environ["TWITTER_CONSUMER_KEY"],
            consumer_secret=os.environ["TWITTER_CONSUMER_SECRET"],
            access_token=os.environ["TWITTER_ACCESS_TOKEN"],
            access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        )
        return tweepy.API(auth)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        """
        Uses the Twitter Ads API v12 async stats endpoint.
        Falls back to the tweepy models when available.
        """
        import requests
        from requests_oauthlib import OAuth1  # type: ignore

        auth = OAuth1(
            os.environ["TWITTER_CONSUMER_KEY"],
            os.environ["TWITTER_CONSUMER_SECRET"],
            os.environ["TWITTER_ACCESS_TOKEN"],
            os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
        )

        base = "https://ads-api.twitter.com/12"
        account_id = self._account_id

        # 1 – list campaigns
        campaigns_resp = requests.get(
            f"{base}/accounts/{account_id}/campaigns",
            auth=auth,
            params={"count": 200, "with_deleted": False},
            timeout=30,
        )
        campaigns_resp.raise_for_status()
        campaigns = campaigns_resp.json().get("data", [])

        cfg = self.config.get("twitter_ads", {})
        metrics = cfg.get("metrics", [
            "impressions", "engagements", "clicks", "spend",
            "conversions", "video_views", "retweets", "likes", "replies",
        ])

        rows: list[dict] = []

        for campaign in campaigns:
            campaign_id = campaign["id"]
            campaign_name = campaign.get("name", "")

            # 2 – request stats (sync endpoint for simplicity)
            stats_resp = requests.get(
                f"{base}/stats/accounts/{account_id}",
                auth=auth,
                params={
                    "entity": "CAMPAIGN",
                    "entity_ids": campaign_id,
                    "start_time": _to_utc_iso(start_date),
                    "end_time": _to_utc_iso(end_date),
                    "granularity": cfg.get("granularity", "DAY"),
                    "metric_groups": "ENGAGEMENT,BILLING,VIDEO",
                    "placement": "ALL_ON_TWITTER",
                },
                timeout=60,
            )
            stats_resp.raise_for_status()
            data = stats_resp.json().get("data", [])

            for entity_data in data:
                for i, time_series in enumerate(
                    entity_data.get("id_data", [{}])[0].get("metrics", {}).get(
                        "impressions", [[]]
                    )
                ):
                    # Build a row per time-series bucket
                    m = {}
                    for metric in metrics:
                        series = (
                            entity_data.get("id_data", [{}])[0]
                            .get("metrics", {})
                            .get(metric, [])
                        )
                        m[metric] = self._safe_float(series[i] if i < len(series) else 0)

                    day = _bucket_to_date(start_date, i)
                    rows.append({
                        "date": day,
                        "platform": self.PLATFORM,
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "impressions": self._safe_int(m.get("impressions", 0)),
                        "clicks": self._safe_int(m.get("clicks", 0)),
                        "spend": round(m.get("spend", 0) / 1_000_000, 4),  # micros
                        "conversions": m.get("conversions", 0),
                        "engagements": self._safe_int(m.get("engagements", 0)),
                        "video_views": self._safe_int(m.get("video_views", 0)),
                        "retweets": self._safe_int(m.get("retweets", 0)),
                        "likes": self._safe_int(m.get("likes", 0)),
                        "replies": self._safe_int(m.get("replies", 0)),
                    })

        df = pd.DataFrame(rows)
        if df.empty:
            return self._empty_frame()

        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self.REQUIRED_COLUMNS + [
            "engagements", "video_views", "retweets", "likes", "replies",
        ])


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_utc_iso(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


def _bucket_to_date(start: date, bucket_index: int) -> date:
    from datetime import timedelta
    return start + timedelta(days=bucket_index)
