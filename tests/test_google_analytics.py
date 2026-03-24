"""Tests for data_sources/google_analytics.py (GoogleAnalyticsConnector)."""

from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE


ENV_VARS = {
    "GA4_PROPERTY_ID": "123456789",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/fake_sa.json",
}


# ---------------------------------------------------------------------------
# Helpers to mock the google.analytics.data_v1beta.types namespace
# ---------------------------------------------------------------------------

def _make_google_analytics_modules():
    """Return a dict of fake module stubs for google-analytics-data."""
    # We need: google, google.analytics, google.analytics.data_v1beta,
    #          google.analytics.data_v1beta.types

    google_mod = ModuleType("google")
    analytics_mod = ModuleType("google.analytics")
    data_v1beta_mod = ModuleType("google.analytics.data_v1beta")
    types_mod = ModuleType("google.analytics.data_v1beta.types")

    # Provide simple identity-ish classes for the types used in _fetch
    for name in ("DateRange", "Dimension", "Metric", "RunReportRequest", "OrderBy"):
        setattr(types_mod, name, MagicMock(name=name))

    client_mod = ModuleType("google.analytics.data_v1beta")
    client_mod.BetaAnalyticsDataClient = MagicMock(name="BetaAnalyticsDataClient")

    google_mod.analytics = analytics_mod
    analytics_mod.data_v1beta = data_v1beta_mod
    data_v1beta_mod.types = types_mod

    return {
        "google": google_mod,
        "google.analytics": analytics_mod,
        "google.analytics.data_v1beta": data_v1beta_mod,
        "google.analytics.data_v1beta.types": types_mod,
    }


def _make_ga4_response(rows_data: list[dict]) -> MagicMock:
    """Build a fake GA4 RunReportResponse."""
    response = MagicMock()

    dimension_names = [
        "date", "sessionSource", "sessionMedium",
        "sessionCampaignName", "deviceCategory", "country",
    ]
    metric_names = [
        "sessions", "totalUsers", "newUsers", "bounceRate",
        "averageSessionDuration", "screenPageViews", "conversions",
        "totalRevenue", "engagementRate",
    ]

    response.dimension_headers = [MagicMock() for _ in dimension_names]
    response.metric_headers = [MagicMock() for _ in metric_names]

    for i, n in enumerate(dimension_names):
        response.dimension_headers[i].name = n
    for i, n in enumerate(metric_names):
        response.metric_headers[i].name = n

    fake_rows = []
    for row_dict in rows_data:
        row = MagicMock()
        row.dimension_values = [
            MagicMock(value=str(row_dict.get(k, ""))) for k in dimension_names
        ]
        row.metric_values = [
            MagicMock(value=str(row_dict.get(k, "0"))) for k in metric_names
        ]
        fake_rows.append(row)

    response.rows = fake_rows
    return response


SAMPLE_ROW = {
    "date": "20240101",
    "sessionSource": "google",
    "sessionMedium": "cpc",
    "sessionCampaignName": "spring_sale",
    "deviceCategory": "mobile",
    "country": "US",
    "sessions": "500",
    "totalUsers": "450",
    "newUsers": "200",
    "bounceRate": "0.45",
    "averageSessionDuration": "120.5",
    "screenPageViews": "1500",
    "conversions": "25.0",
    "totalRevenue": "500.0",
    "engagementRate": "0.75",
}


class TestGoogleAnalyticsConnector:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

    @pytest.fixture(autouse=True)
    def _mock_google_modules(self):
        """Inject fake google-analytics-data stubs into sys.modules."""
        stubs = _make_google_analytics_modules()
        with patch.dict(sys.modules, stubs):
            yield stubs

    @pytest.fixture()
    def mock_ga4_client(self):
        with patch(
            "data_sources.google_analytics.GoogleAnalyticsConnector._build_client"
        ) as m:
            mock_client = MagicMock()
            m.return_value = mock_client
            yield mock_client

    def test_fetch_happy_path(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([SAMPLE_ROW, SAMPLE_ROW])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        for col in ["date", "platform", "campaign_id", "campaign_name",
                    "impressions", "clicks", "spend", "conversions"]:
            assert col in df.columns

    def test_platform_label(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([SAMPLE_ROW])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert (df["platform"] == "google_analytics").all()

    def test_date_parsed_from_yyyymmdd(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([{**SAMPLE_ROW, "date": "20240115"}])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["date"].iloc[0] == date(2024, 1, 15)

    def test_campaign_id_source_medium(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([SAMPLE_ROW])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["campaign_id"].iloc[0] == "google/cpc"

    def test_impressions_clicks_spend_are_zero(self, mock_ga4_client):
        """GA4 does not expose paid media impressions/clicks/spend."""
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([SAMPLE_ROW])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["impressions"].iloc[0] == 0
        assert df["clicks"].iloc[0] == 0
        assert df["spend"].iloc[0] == pytest.approx(0.0)

    def test_empty_response_returns_empty_frame(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df.empty

    def test_empty_frame_has_required_columns(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector
        from data_sources.base import BaseConnector

        response = _make_ga4_response([])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        for col in BaseConnector.REQUIRED_COLUMNS:
            assert col in df.columns

    def test_api_error_propagates(self, mock_ga4_client):
        """Persistent errors bubble up (possibly via tenacity RetryError)."""
        from data_sources.google_analytics import GoogleAnalyticsConnector
        from tenacity import RetryError

        mock_ga4_client.run_report.side_effect = RuntimeError("internal error")

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        with pytest.raises((RuntimeError, RetryError)):
            connector.fetch(START_DATE, END_DATE)

    def test_conversions_numeric(self, mock_ga4_client):
        from data_sources.google_analytics import GoogleAnalyticsConnector

        response = _make_ga4_response([{**SAMPLE_ROW, "conversions": "42.5"}])
        mock_ga4_client.run_report.return_value = response

        connector = GoogleAnalyticsConnector(SAMPLE_CONFIG)
        df = connector.fetch(START_DATE, END_DATE)
        assert df["conversions"].iloc[0] == pytest.approx(42.5)
