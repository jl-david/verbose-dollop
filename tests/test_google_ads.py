"""Tests for data_sources/google_ads.py (GoogleAdsConnector)."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE


# ---------------------------------------------------------------------------
# Helpers: build minimal fake google-ads API response objects
# ---------------------------------------------------------------------------

def _make_row(
    date_str="2024-01-01",
    campaign_id=123,
    campaign_name="Test Campaign",
    impressions=1000,
    clicks=50,
    cost_micros=25_000_000,
    conversions=5.0,
    conversions_value=100.0,
    view_through_conversions=2,
    ctr=0.05,
    average_cpc=500_000,
    average_cpm=25_000,
    campaign_status="ENABLED",
    ad_group_id=456,
    ad_group_name="Test AdGroup",
    device="MOBILE",
    network_type="SEARCH",
):
    row = MagicMock()
    row.segments.date = date_str
    row.campaign.id = campaign_id
    row.campaign.name = campaign_name
    row.campaign.status.name = campaign_status
    row.ad_group.id = ad_group_id
    row.ad_group.name = ad_group_name
    row.segments.device.name = device
    row.segments.ad_network_type.name = network_type
    row.metrics.impressions = impressions
    row.metrics.clicks = clicks
    row.metrics.cost_micros = cost_micros
    row.metrics.conversions = conversions
    row.metrics.conversions_value = conversions_value
    row.metrics.view_through_conversions = view_through_conversions
    row.metrics.ctr = ctr
    row.metrics.average_cpc = average_cpc
    row.metrics.average_cpm = average_cpm
    return row


def _make_batch(rows):
    batch = MagicMock()
    batch.results = rows
    return batch


ENV_VARS = {
    "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
    "GOOGLE_ADS_CLIENT_ID": "client-id",
    "GOOGLE_ADS_CLIENT_SECRET": "client-secret",
    "GOOGLE_ADS_REFRESH_TOKEN": "refresh-token",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "1234567890",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoogleAdsConnector:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

    @pytest.fixture()
    def mock_ga_client(self):
        """Patch the GoogleAdsClient so no real network call is made."""
        with patch("data_sources.google_ads.GoogleAdsConnector._build_client") as m:
            mock_client = MagicMock()
            m.return_value = mock_client
            yield mock_client

    def _make_connector(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector
        return GoogleAdsConnector(SAMPLE_CONFIG)

    def test_fetch_happy_path(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        rows = [_make_row("2024-01-01"), _make_row("2024-01-02")]
        batch = _make_batch(rows)
        mock_ga_client.get_service.return_value.search_stream.return_value = [batch]

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        # Required columns all present
        for col in ["date", "platform", "campaign_id", "campaign_name",
                    "impressions", "clicks", "spend", "conversions"]:
            assert col in df.columns

    def test_fetch_platform_label(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        batch = _make_batch([_make_row()])
        mock_ga_client.get_service.return_value.search_stream.return_value = [batch]

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert (df["platform"] == "google_ads").all()

    def test_spend_converted_from_micros(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        batch = _make_batch([_make_row(cost_micros=10_000_000)])
        mock_ga_client.get_service.return_value.search_stream.return_value = [batch]

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["spend"].iloc[0] == pytest.approx(10.0)

    def test_empty_response_returns_empty_frame(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        mock_ga_client.get_service.return_value.search_stream.return_value = []

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_empty_frame_has_required_columns(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector
        from data_sources.base import BaseConnector

        mock_ga_client.get_service.return_value.search_stream.return_value = []

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        for col in BaseConnector.REQUIRED_COLUMNS:
            assert col in df.columns

    def test_api_error_propagates(self, mock_ga_client):
        """Persistent API errors bubble up (possibly wrapped by tenacity)."""
        from data_sources.google_ads import GoogleAdsConnector
        from tenacity import RetryError

        mock_ga_client.get_service.return_value.search_stream.side_effect = RuntimeError(
            "quota exceeded"
        )

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        with pytest.raises((RuntimeError, RetryError)):
            connector.fetch(START_DATE, END_DATE)

    def test_date_parsed_to_date_objects(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        batch = _make_batch([_make_row("2024-01-05")])
        mock_ga_client.get_service.return_value.search_stream.return_value = [batch]

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert isinstance(df["date"].iloc[0], date)
        assert df["date"].iloc[0] == date(2024, 1, 5)

    def test_multiple_batches_concatenated(self, mock_ga_client):
        from data_sources.google_ads import GoogleAdsConnector

        batch1 = _make_batch([_make_row("2024-01-01")])
        batch2 = _make_batch([_make_row("2024-01-02"), _make_row("2024-01-03")])
        mock_ga_client.get_service.return_value.search_stream.return_value = [batch1, batch2]

        connector = GoogleAdsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert len(df) == 3
