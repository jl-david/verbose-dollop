"""Tests for data_sources/twitter_ads.py (TwitterAdsConnector)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE


ENV_VARS = {
    "TWITTER_CONSUMER_KEY": "consumer-key",
    "TWITTER_CONSUMER_SECRET": "consumer-secret",
    "TWITTER_ACCESS_TOKEN": "access-token",
    "TWITTER_ACCESS_TOKEN_SECRET": "access-token-secret",
    "TWITTER_AD_ACCOUNT_ID": "abc123def456ghi7",
}

SAMPLE_CAMPAIGNS = [
    {"id": "cid_aaa", "name": "Promo Campaign"},
    {"id": "cid_bbb", "name": "Brand Campaign"},
]

SAMPLE_METRICS = {
    "impressions": [10000, 12000, 11000],
    "engagements": [500, 600, 550],
    "clicks": [200, 250, 220],
    "spend": [5_000_000, 6_000_000, 5_500_000],  # micros
    "conversions": [10, 12, 11],
    "video_views": [100, 120, 110],
    "retweets": [20, 25, 22],
    "likes": [150, 180, 165],
    "replies": [30, 35, 32],
}


def _make_stats_response(campaign_id: str, metrics: dict) -> dict:
    return {
        "data": [
            {
                "id": campaign_id,
                "id_data": [
                    {"metrics": metrics}
                ],
            }
        ]
    }


class TestTwitterAdsConnector:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

    @pytest.fixture(autouse=True)
    def _mock_tweepy(self):
        """Stub tweepy and requests_oauthlib so we avoid real imports."""
        tweepy_mod = ModuleType("tweepy")
        tweepy_mod.OAuth1UserHandler = MagicMock(name="OAuth1UserHandler")
        tweepy_mod.API = MagicMock(name="API")

        oauthlib_mod = ModuleType("requests_oauthlib")
        oauthlib_mod.OAuth1 = MagicMock(name="OAuth1")

        with patch.dict(sys.modules, {
            "tweepy": tweepy_mod,
            "requests_oauthlib": oauthlib_mod,
        }):
            yield

    @pytest.fixture()
    def mock_requests(self):
        with patch("requests.get") as mock_get:
            def _side_effect(url, **kwargs):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                if "/campaigns" in url:
                    resp.json.return_value = {"data": SAMPLE_CAMPAIGNS}
                else:
                    # stats endpoint – use metrics for one campaign
                    campaign_id = kwargs.get("params", {}).get("entity_ids", "cid_aaa")
                    resp.json.return_value = _make_stats_response(campaign_id, SAMPLE_METRICS)
                return resp

            mock_get.side_effect = _side_effect
            yield mock_get

    def _connector(self):
        from data_sources.twitter_ads import TwitterAdsConnector
        with patch("data_sources.twitter_ads.TwitterAdsConnector._build_client"):
            return TwitterAdsConnector(SAMPLE_CONFIG)

    def test_fetch_happy_path(self, mock_requests):
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)

        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        for col in ["date", "platform", "campaign_id", "campaign_name",
                    "impressions", "clicks", "spend", "conversions"]:
            assert col in df.columns

    def test_platform_label(self, mock_requests):
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert (df["platform"] == "twitter_ads").all()

    def test_spend_converted_from_micros(self, mock_requests):
        """spend micros → dollars (divide by 1_000_000)."""
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        # First bucket, first campaign: 5_000_000 micros = 5.0
        first_row = df[df["campaign_id"] == "cid_aaa"].iloc[0]
        assert first_row["spend"] == pytest.approx(5.0)

    def test_date_increments_per_bucket(self, mock_requests):
        """Each bucket index maps to start_date + index days."""
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        dates_for_first = df[df["campaign_id"] == "cid_aaa"]["date"].tolist()
        for i, d in enumerate(dates_for_first):
            assert d == START_DATE + timedelta(days=i)

    def test_empty_campaigns_returns_empty_frame(self, mock_requests):
        from data_sources.twitter_ads import TwitterAdsConnector

        def _no_campaigns(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"data": []}
            return resp

        mock_requests.side_effect = _no_campaigns

        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert df.empty

    def test_empty_frame_has_required_columns(self, mock_requests):
        from data_sources.base import BaseConnector

        def _no_campaigns(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"data": []}
            return resp

        mock_requests.side_effect = _no_campaigns

        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        for col in BaseConnector.REQUIRED_COLUMNS:
            assert col in df.columns

    def test_additional_engagement_columns(self, mock_requests):
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        for col in ["engagements", "video_views", "retweets", "likes", "replies"]:
            assert col in df.columns

    def test_api_error_propagates(self, mock_requests):
        """Persistent errors bubble up (possibly wrapped by tenacity)."""
        from tenacity import RetryError

        mock_requests.side_effect = RuntimeError("timeout")

        connector = self._connector()
        with pytest.raises((RuntimeError, RetryError)):
            connector.fetch(START_DATE, END_DATE)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestTwitterHelpers:
    def test_to_utc_iso(self):
        from data_sources.twitter_ads import _to_utc_iso

        result = _to_utc_iso(date(2024, 3, 15))
        assert result.startswith("2024-03-15")
        assert "UTC" in result or "+00:00" in result

    def test_bucket_to_date(self):
        from data_sources.twitter_ads import _bucket_to_date

        start = date(2024, 1, 1)
        assert _bucket_to_date(start, 0) == date(2024, 1, 1)
        assert _bucket_to_date(start, 6) == date(2024, 1, 7)
        assert _bucket_to_date(start, 30) == date(2024, 1, 31)
