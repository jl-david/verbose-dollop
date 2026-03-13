"""Tests for pipeline/aggregator.py (DataAggregator)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, START_DATE, END_DATE, make_performance_df
from pipeline.aggregator import DataAggregator, UNIFIED_COLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loader_mock():
    """Return a mock BigQueryLoader."""
    loader = MagicMock()
    loader.load = MagicMock()
    return loader


def _patch_aggregator(connectors: dict, loader=None):
    """
    Context manager that patches DataAggregator._get_connector and
    DataAggregator's internal _loader.
    """
    if loader is None:
        loader = _make_loader_mock()

    agg = DataAggregator.__new__(DataAggregator)
    agg.config = SAMPLE_CONFIG
    agg.platforms = DataAggregator.ALL_PLATFORMS
    agg._loader = loader
    agg._get_connector = lambda platform: connectors.get(platform)
    return agg


# ---------------------------------------------------------------------------
# Tests: _build_unified
# ---------------------------------------------------------------------------

class TestBuildUnified:
    def test_concatenates_all_platforms(self):
        dfs = {
            "google_ads": make_performance_df("google_ads", rows=3),
            "meta_ads": make_performance_df("meta_ads", rows=2),
        }
        result = DataAggregator._build_unified(dfs)
        assert len(result) == 5

    def test_output_has_unified_columns(self):
        dfs = {"google_ads": make_performance_df("google_ads")}
        result = DataAggregator._build_unified(dfs)
        for col in UNIFIED_COLS:
            assert col in result.columns

    def test_derived_kpi_columns_present(self):
        dfs = {"google_ads": make_performance_df("google_ads")}
        result = DataAggregator._build_unified(dfs)
        for col in ["ctr", "cpc", "cpa"]:
            assert col in result.columns

    def test_ctr_calculation(self):
        df = make_performance_df("test")
        df["impressions"] = 1000
        df["clicks"] = 50
        result = DataAggregator._build_unified({"test": df})
        assert result["ctr"].iloc[0] == pytest.approx(0.05)

    def test_ctr_zero_when_no_impressions(self):
        df = make_performance_df("test")
        df["impressions"] = 0
        result = DataAggregator._build_unified({"test": df})
        assert result["ctr"].iloc[0] == 0.0

    def test_cpc_calculation(self):
        df = make_performance_df("test")
        df["clicks"] = 100
        df["spend"] = 50.0
        result = DataAggregator._build_unified({"test": df})
        assert result["cpc"].iloc[0] == pytest.approx(0.5)

    def test_cpc_zero_when_no_clicks(self):
        df = make_performance_df("test")
        df["clicks"] = 0
        result = DataAggregator._build_unified({"test": df})
        assert result["cpc"].iloc[0] == 0.0

    def test_cpa_calculation(self):
        df = make_performance_df("test")
        df["conversions"] = 10.0
        df["spend"] = 100.0
        result = DataAggregator._build_unified({"test": df})
        assert result["cpa"].iloc[0] == pytest.approx(10.0)

    def test_cpa_zero_when_no_conversions(self):
        df = make_performance_df("test")
        df["conversions"] = 0.0
        result = DataAggregator._build_unified({"test": df})
        assert result["cpa"].iloc[0] == 0.0

    def test_empty_dict_returns_empty_frame(self):
        result = DataAggregator._build_unified({})
        assert result.empty
        for col in UNIFIED_COLS:
            assert col in result.columns

    def test_result_sorted_by_date_platform_campaign(self):
        df1 = make_performance_df("a_platform", rows=2)
        df1["date"] = [date(2024, 1, 2), date(2024, 1, 1)]
        df2 = make_performance_df("b_platform", rows=1)
        df2["date"] = [date(2024, 1, 1)]
        result = DataAggregator._build_unified({"a": df1, "b": df2})
        dates = result["date"].tolist()
        assert dates == sorted(dates)

    def test_extra_platform_columns_dropped_in_unified(self):
        """Columns not in UNIFIED_COLS must not appear in the unified frame."""
        df = make_performance_df("google_ads")
        df["ad_group_id"] = "ag_1"   # extra column
        result = DataAggregator._build_unified({"google_ads": df})
        assert "ad_group_id" not in result.columns


# ---------------------------------------------------------------------------
# Tests: run()
# ---------------------------------------------------------------------------

class TestDataAggregatorRun:
    def test_run_fetches_all_platforms(self):
        mock_connectors = {
            p: MagicMock(fetch=MagicMock(return_value=make_performance_df(p)))
            for p in DataAggregator.ALL_PLATFORMS
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)

        agg.run(start_date=START_DATE, end_date=END_DATE)

        for p, connector in mock_connectors.items():
            connector.fetch.assert_called_once_with(START_DATE, END_DATE)

    def test_run_loads_each_platform_table(self):
        mock_connectors = {
            p: MagicMock(fetch=MagicMock(return_value=make_performance_df(p)))
            for p in DataAggregator.ALL_PLATFORMS
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)

        agg.run(start_date=START_DATE, end_date=END_DATE)

        # Each platform + unified → ALL_PLATFORMS + 1 load calls
        expected_calls = len(DataAggregator.ALL_PLATFORMS) + 1
        assert loader.load.call_count == expected_calls

    def test_run_loads_unified_table(self):
        mock_connectors = {
            p: MagicMock(fetch=MagicMock(return_value=make_performance_df(p)))
            for p in DataAggregator.ALL_PLATFORMS
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)

        agg.run(start_date=START_DATE, end_date=END_DATE)

        call_args = [c[0][1] for c in loader.load.call_args_list]
        assert "unified_performance" in call_args

    def test_run_skips_unavailable_connector(self):
        """If _get_connector returns None, that platform is skipped."""
        mock_connectors = {
            "google_ads": MagicMock(fetch=MagicMock(return_value=make_performance_df("google_ads")))
            # other platforms return None implicitly
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)
        agg.platforms = ["google_ads", "meta_ads"]  # meta_ads has no connector

        agg.run(start_date=START_DATE, end_date=END_DATE)

        # Only google_ads + unified loaded
        assert loader.load.call_count == 2

    def test_run_skips_platform_on_fetch_error(self):
        """If fetch() raises, the platform is skipped but others continue."""
        mock_connectors = {
            "google_ads": MagicMock(
                fetch=MagicMock(side_effect=RuntimeError("API down"))
            ),
            "meta_ads": MagicMock(
                fetch=MagicMock(return_value=make_performance_df("meta_ads"))
            ),
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)
        agg.platforms = ["google_ads", "meta_ads"]

        agg.run(start_date=START_DATE, end_date=END_DATE)

        # meta_ads + unified loaded (google_ads failed)
        assert loader.load.call_count == 2

    def test_run_uses_lookback_days_default(self):
        """When start/end are omitted, look-back is derived from config."""
        config = {**SAMPLE_CONFIG, "pipeline": {"lookback_days": 7}}
        fetch_calls = []

        class _RecordingConnector:
            def fetch(self, start_date, end_date):
                fetch_calls.append((start_date, end_date))
                return make_performance_df("google_ads")

        loader = _make_loader_mock()
        agg = DataAggregator.__new__(DataAggregator)
        agg.config = config
        agg.platforms = ["google_ads"]
        agg._loader = loader
        agg._get_connector = lambda p: _RecordingConnector()

        agg.run()  # no explicit dates

        start, end = fetch_calls[0]
        assert (end - start).days == 6  # 7-day window

    def test_run_no_data_does_not_call_loader(self):
        """If all platforms fail, loader.load is never called."""
        mock_connectors = {
            "google_ads": MagicMock(fetch=MagicMock(side_effect=RuntimeError("down")))
        }
        loader = _make_loader_mock()
        agg = _patch_aggregator(mock_connectors, loader)
        agg.platforms = ["google_ads"]

        agg.run(start_date=START_DATE, end_date=END_DATE)

        loader.load.assert_not_called()

    def test_all_platforms_listed(self):
        assert set(DataAggregator.ALL_PLATFORMS) == {
            "google_ads", "meta_ads", "google_analytics",
            "linkedin_ads", "twitter_ads",
        }
