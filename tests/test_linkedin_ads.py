"""Tests for data_sources/linkedin_ads.py (LinkedInAdsConnector)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE


ENV_VARS = {
    "LINKEDIN_ACCESS_TOKEN": "li-access-token",
    "LINKEDIN_AD_ACCOUNT_ID": "98765432",
}

SAMPLE_CAMPAIGNS = [
    {"id": 111, "name": "Brand Awareness"},
    {"id": 222, "name": "Lead Generation"},
]

SAMPLE_STATS = [
    {
        "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}},
        "impressions": 5000,
        "clicks": 200,
        "costInLocalCurrency": 150.0,
        "externalWebsiteConversions": 10,
        "leads": 3,
        "videoViews": 50,
        "approximateUniqueImpressions": 4500,
    },
    {
        "dateRange": {"start": {"year": 2024, "month": 1, "day": 2}},
        "impressions": 6000,
        "clicks": 250,
        "costInLocalCurrency": 175.0,
        "externalWebsiteConversions": 12,
        "leads": 4,
        "videoViews": 60,
        "approximateUniqueImpressions": 5500,
    },
]


class TestLinkedInAdsConnector:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

    @pytest.fixture()
    def mock_requests(self):
        """Patch requests.get to return controlled responses."""
        with patch("data_sources.linkedin_ads.requests.get") as mock_get:
            def _side_effect(url, **kwargs):
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                if "adCampaignsV2" in url:
                    resp.json.return_value = {"elements": SAMPLE_CAMPAIGNS}
                else:
                    resp.json.return_value = {"elements": SAMPLE_STATS}
                return resp

            mock_get.side_effect = _side_effect
            yield mock_get

    def test_fetch_happy_path(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)

        assert isinstance(df, pd.DataFrame)
        # 2 campaigns × 2 stat rows each = 4
        assert len(df) == 4
        for col in ["date", "platform", "campaign_id", "campaign_name",
                    "impressions", "clicks", "spend", "conversions"]:
            assert col in df.columns

    def test_platform_label(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert (df["platform"] == "linkedin_ads").all()

    def test_date_parsed(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert isinstance(df["date"].iloc[0], date)

    def test_spend_mapped_from_cost_in_local_currency(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["spend"].iloc[0] == pytest.approx(150.0)

    def test_conversions_from_external_website_conversions(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["conversions"].iloc[0] == pytest.approx(10.0)

    def test_empty_campaigns_returns_empty_frame(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        def _no_campaigns(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"elements": []}
            return resp

        mock_requests.side_effect = _no_campaigns

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df.empty

    def test_empty_frame_has_required_columns(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector
        from data_sources.base import BaseConnector

        mock_requests.side_effect = lambda url, **kw: (
            MagicMock(raise_for_status=MagicMock(), json=MagicMock(return_value={"elements": []}))
        )

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        for col in BaseConnector.REQUIRED_COLUMNS:
            assert col in df.columns

    def test_parse_linkedin_date(self):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        date_range = {"start": {"year": 2024, "month": 3, "day": 5}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2024-03-05"

    def test_parse_linkedin_date_missing_start(self):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        result = LinkedInAdsConnector._parse_linkedin_date({})
        assert result == "1970-01-01"

    def test_api_http_error_propagates(self, mock_requests):
        """HTTP errors bubble up (possibly wrapped by tenacity)."""
        from data_sources.linkedin_ads import LinkedInAdsConnector
        from tenacity import RetryError

        mock_requests.side_effect = RuntimeError("connection refused")

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        with pytest.raises((RuntimeError, RetryError)):
            connector.fetch(START_DATE, END_DATE)

    def test_additional_columns_present(self, mock_requests):
        from data_sources.linkedin_ads import LinkedInAdsConnector

        connector = LinkedInAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        for col in ["leads", "video_views", "unique_impressions"]:
            assert col in df.columns
