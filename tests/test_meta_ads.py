"""Tests for data_sources/meta_ads.py (MetaAdsConnector)."""

from __future__ import annotations

import sys
from datetime import date
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE


ENV_VARS = {
    "META_APP_ID": "app-id-123",
    "META_APP_SECRET": "app-secret-abc",
    "META_ACCESS_TOKEN": "access-token-xyz",
    "META_AD_ACCOUNT_ID": "act_987654321",
}


# ---------------------------------------------------------------------------
# Stub the facebook_business SDK modules
# ---------------------------------------------------------------------------

def _make_facebook_modules():
    fb_mod = ModuleType("facebook_business")
    api_mod = ModuleType("facebook_business.api")
    adobjects_mod = ModuleType("facebook_business.adobjects")
    adaccount_mod = ModuleType("facebook_business.adobjects.adaccount")
    adsinsights_mod = ModuleType("facebook_business.adobjects.adsinsights")

    # FacebookAdsApi stub
    fake_api = MagicMock(name="FacebookAdsApi")
    api_mod.FacebookAdsApi = fake_api

    # AdAccount stub
    fake_ad_account_cls = MagicMock(name="AdAccount")
    adaccount_mod.AdAccount = fake_ad_account_cls

    # AdsInsights stub
    fake_ads_insights_cls = MagicMock(name="AdsInsights")
    adsinsights_mod.AdsInsights = fake_ads_insights_cls

    fb_mod.api = api_mod
    fb_mod.adobjects = adobjects_mod
    adobjects_mod.adaccount = adaccount_mod
    adobjects_mod.adsinsights = adsinsights_mod

    return {
        "facebook_business": fb_mod,
        "facebook_business.api": api_mod,
        "facebook_business.adobjects": adobjects_mod,
        "facebook_business.adobjects.adaccount": adaccount_mod,
        "facebook_business.adobjects.adsinsights": adsinsights_mod,
    }


def _make_insight(
    date_start="2024-01-01",
    campaign_id="cid_1",
    campaign_name="Campaign 1",
    adset_id="asid_1",
    adset_name="AdSet 1",
    ad_id="aid_1",
    ad_name="Ad 1",
    impressions="1000",
    clicks="50",
    spend="25.0",
    reach="900",
    frequency="1.1",
    cpm="25.0",
    cpc="0.5",
    ctr="5.0",
    actions=None,
    action_values=None,
) -> MagicMock:
    insight = MagicMock()
    data = {
        "date_start": date_start,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "adset_id": adset_id,
        "adset_name": adset_name,
        "ad_id": ad_id,
        "ad_name": ad_name,
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "reach": reach,
        "frequency": frequency,
        "cpm": cpm,
        "cpc": cpc,
        "ctr": ctr,
        "actions": actions or [],
        "action_values": action_values or [],
    }
    insight.get = lambda key, default=None: data.get(key, default)
    return insight


class TestMetaAdsConnector:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        for k, v in ENV_VARS.items():
            monkeypatch.setenv(k, v)

    @pytest.fixture(autouse=True)
    def _mock_facebook_modules(self):
        stubs = _make_facebook_modules()
        with patch.dict(sys.modules, stubs):
            yield stubs

    @pytest.fixture()
    def mock_meta_client(self, _mock_facebook_modules):
        with patch(
            "data_sources.meta_ads.MetaAdsConnector._init_sdk"
        ):
            yield _mock_facebook_modules

    def _connector(self):
        from data_sources.meta_ads import MetaAdsConnector
        with patch("data_sources.meta_ads.MetaAdsConnector._init_sdk"):
            return MetaAdsConnector(SAMPLE_CONFIG)

    def _set_insights(self, mock_modules, insights):
        """Configure the AdAccount mock to return the given insights."""
        adaccount_cls = mock_modules["facebook_business.adobjects.adaccount"].AdAccount
        adaccount_instance = adaccount_cls.return_value
        adaccount_instance.get_insights.return_value = insights

    def test_fetch_happy_path(self, mock_meta_client):
        self._set_insights(mock_meta_client, [_make_insight(), _make_insight("2024-01-02")])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        for col in ["date", "platform", "campaign_id", "campaign_name",
                    "impressions", "clicks", "spend", "conversions"]:
            assert col in df.columns

    def test_platform_label(self, mock_meta_client):
        self._set_insights(mock_meta_client, [_make_insight()])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert (df["platform"] == "meta_ads").all()

    def test_spend_is_float(self, mock_meta_client):
        self._set_insights(mock_meta_client, [_make_insight(spend="42.5")])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert df["spend"].iloc[0] == pytest.approx(42.5)

    def test_conversions_from_purchase_actions(self, mock_meta_client):
        actions = [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
            {"action_type": "link_click", "value": "10"},
        ]
        insight = _make_insight(actions=actions)
        self._set_insights(mock_meta_client, [insight])

        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert df["conversions"].iloc[0] == pytest.approx(3.0)

    def test_empty_response_returns_empty_frame(self, mock_meta_client):
        self._set_insights(mock_meta_client, [])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert df.empty

    def test_empty_frame_has_required_columns(self, mock_meta_client):
        from data_sources.base import BaseConnector
        self._set_insights(mock_meta_client, [])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        for col in BaseConnector.REQUIRED_COLUMNS:
            assert col in df.columns

    def test_action_columns_filled_with_zeros(self, mock_meta_client):
        """Missing action types in a row should be filled with 0."""
        insight1 = _make_insight(
            "2024-01-01",
            actions=[{"action_type": "link_click", "value": "5"}],
        )
        insight2 = _make_insight(
            "2024-01-02",
            actions=[{"action_type": "video_view", "value": "10"}],
        )
        self._set_insights(mock_meta_client, [insight1, insight2])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)

        # Both action columns should exist and be filled
        assert "action_link_click" in df.columns
        assert "action_video_view" in df.columns
        assert df["action_link_click"].isna().sum() == 0
        assert df["action_video_view"].isna().sum() == 0

    def test_date_parsed_to_date_objects(self, mock_meta_client):
        self._set_insights(mock_meta_client, [_make_insight("2024-01-05")])
        connector = self._connector()
        df = connector.fetch(START_DATE, END_DATE)
        assert isinstance(df["date"].iloc[0], date)
        assert df["date"].iloc[0] == date(2024, 1, 5)
