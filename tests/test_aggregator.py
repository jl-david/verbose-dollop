"""Tests for pipeline/aggregator.py – DataAggregator."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.aggregator import DataAggregator, UNIFIED_COLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_platform_df(
    platform: str,
    n_rows: int = 2,
    impressions: int = 1000,
    clicks: int = 100,
    spend: float = 50.0,
    conversions: float = 10.0,
) -> pd.DataFrame:
    rows = []
    for i in range(n_rows):
        rows.append({
            "date": date(2024, 1, i + 1),
            "platform": platform,
            "campaign_id": f"c{i}",
            "campaign_name": f"Campaign {i}",
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conversions,
        })
    return pd.DataFrame(rows)


def _make_config(**overrides) -> dict:
    cfg: dict = {
        "bigquery": {
            "project_id": "test-project",
            "dataset_id": "test_dataset",
            "tables": {},
        },
        "pipeline": {"lookback_days": 30},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# DataAggregator._build_unified
# ---------------------------------------------------------------------------

class TestBuildUnified:
    def test_basic_concatenation(self):
        dfs = {
            "google_ads": _make_platform_df("google_ads"),
            "meta_ads": _make_platform_df("meta_ads"),
        }
        result = DataAggregator._build_unified(dfs)
        assert len(result) == 4  # 2 rows × 2 platforms
        assert set(result["platform"].unique()) == {"google_ads", "meta_ads"}

    def test_all_unified_cols_present(self):
        dfs = {"google_ads": _make_platform_df("google_ads")}
        result = DataAggregator._build_unified(dfs)
        for col in UNIFIED_COLS:
            assert col in result.columns

    def test_kpi_ctr_computed_correctly(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 200,
            "clicks": 10,
            "spend": 100.0,
            "conversions": 5.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["ctr"] == round(10 / 200, 4)

    def test_kpi_cpc_computed_correctly(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 200,
            "clicks": 10,
            "spend": 100.0,
            "conversions": 5.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["cpc"] == round(100.0 / 10, 4)

    def test_kpi_cpa_computed_correctly(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 200,
            "clicks": 10,
            "spend": 100.0,
            "conversions": 5.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["cpa"] == round(100.0 / 5.0, 4)

    def test_zero_impressions_gives_zero_ctr(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 0,
            "clicks": 0,
            "spend": 0.0,
            "conversions": 0.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["ctr"] == 0.0

    def test_zero_clicks_gives_zero_cpc(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 1000,
            "clicks": 0,
            "spend": 50.0,
            "conversions": 0.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["cpc"] == 0.0

    def test_zero_conversions_gives_zero_cpa(self):
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 1000,
            "clicks": 100,
            "spend": 50.0,
            "conversions": 0.0,
        }])
        result = DataAggregator._build_unified({"p": df})
        assert result.iloc[0]["cpa"] == 0.0

    def test_empty_dict_returns_empty_dataframe(self):
        result = DataAggregator._build_unified({})
        assert isinstance(result, pd.DataFrame)
        assert result.empty
        assert list(result.columns) == UNIFIED_COLS

    def test_dataframe_sorted_by_date_platform_campaign(self):
        rows = [
            {"date": date(2024, 1, 2), "platform": "b", "campaign_id": "c1",
             "campaign_name": "Z", "impressions": 10, "clicks": 1, "spend": 1.0, "conversions": 0.0},
            {"date": date(2024, 1, 1), "platform": "a", "campaign_id": "c2",
             "campaign_name": "A", "impressions": 10, "clicks": 1, "spend": 1.0, "conversions": 0.0},
        ]
        df = pd.DataFrame(rows)
        result = DataAggregator._build_unified({"mixed": df})
        assert result.iloc[0]["date"] == date(2024, 1, 1)
        assert result.iloc[1]["date"] == date(2024, 1, 2)

    def test_missing_numeric_cols_filled_with_zero(self):
        # DataFrame missing columns that are in UNIFIED_COLS after concat
        df = pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "p",
            "campaign_id": "c1",
            "campaign_name": "C",
            "impressions": 100,
            "clicks": 5,
            "spend": 10.0,
            # 'conversions' is missing
        }])
        # _build_unified should fill 'conversions' with 0 and not crash
        result = DataAggregator._build_unified({"p": df})
        assert "conversions" in result.columns
        assert result.iloc[0]["conversions"] == 0

    def test_multiple_platforms_have_correct_row_counts(self):
        dfs = {
            "google_ads": _make_platform_df("google_ads", n_rows=3),
            "meta_ads": _make_platform_df("meta_ads", n_rows=1),
            "linkedin_ads": _make_platform_df("linkedin_ads", n_rows=2),
        }
        result = DataAggregator._build_unified(dfs)
        assert len(result) == 6


# ---------------------------------------------------------------------------
# DataAggregator._get_connector
# ---------------------------------------------------------------------------

class TestGetConnector:
    def test_unknown_platform_returns_none(self):
        with patch("pipeline.aggregator.BigQueryLoader"):
            agg = DataAggregator(_make_config())
        result = agg._get_connector("nonexistent_platform")
        assert result is None

    def test_known_platform_returns_connector_or_none_on_error(self):
        with patch("pipeline.aggregator.BigQueryLoader"):
            agg = DataAggregator(_make_config())
        # If instantiation fails (missing env vars), it returns None, not raises
        result = agg._get_connector("google_ads")
        # Either None (failed init) or a connector instance – no exception
        assert result is None or hasattr(result, "fetch")


# ---------------------------------------------------------------------------
# DataAggregator.__init__
# ---------------------------------------------------------------------------

class TestDataAggregatorInit:
    def test_default_platforms_is_all(self):
        with patch("pipeline.aggregator.BigQueryLoader"):
            agg = DataAggregator(_make_config())
        assert agg.platforms == DataAggregator.ALL_PLATFORMS

    def test_custom_platforms_subset(self):
        with patch("pipeline.aggregator.BigQueryLoader"):
            agg = DataAggregator(_make_config(), platforms=["google_ads", "meta_ads"])
        assert agg.platforms == ["google_ads", "meta_ads"]

    def test_all_platforms_constant(self):
        expected = [
            "google_ads", "meta_ads", "google_analytics",
            "linkedin_ads", "twitter_ads",
        ]
        assert DataAggregator.ALL_PLATFORMS == expected


# ---------------------------------------------------------------------------
# DataAggregator.run
# ---------------------------------------------------------------------------

class TestDataAggregatorRun:
    def _make_mock_connector(self, platform: str) -> MagicMock:
        connector = MagicMock()
        connector.fetch.return_value = _make_platform_df(platform)
        return connector

    def test_run_calls_loader_for_each_platform(self):
        cfg = _make_config()
        mock_loader = MagicMock()

        with patch("pipeline.aggregator.BigQueryLoader", return_value=mock_loader):
            agg = DataAggregator(cfg, platforms=["google_ads", "meta_ads"])

        mock_ga = self._make_mock_connector("google_ads")
        mock_meta = self._make_mock_connector("meta_ads")

        def side_effect(platform):
            return {"google_ads": mock_ga, "meta_ads": mock_meta}.get(platform)

        agg._get_connector = side_effect

        agg.run(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))

        # loader.load called for each platform + unified
        assert mock_loader.load.call_count == 3

    def test_run_no_data_skips_loader(self):
        cfg = _make_config()
        mock_loader = MagicMock()

        with patch("pipeline.aggregator.BigQueryLoader", return_value=mock_loader):
            agg = DataAggregator(cfg, platforms=["google_ads"])

        agg._get_connector = lambda p: None  # all connectors fail

        agg.run(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))

        mock_loader.load.assert_not_called()

    def test_run_uses_default_lookback_when_no_dates_given(self):
        cfg = _make_config()
        cfg["pipeline"]["lookback_days"] = 7
        mock_loader = MagicMock()

        with patch("pipeline.aggregator.BigQueryLoader", return_value=mock_loader):
            agg = DataAggregator(cfg, platforms=["google_ads"])

        mock_connector = self._make_mock_connector("google_ads")
        agg._get_connector = lambda p: mock_connector

        agg.run()

        call_args = mock_connector.fetch.call_args[0]
        start, end = call_args[0], call_args[1]
        assert (end - start).days == 6  # 7 days inclusive

    def test_run_connector_fetch_exception_does_not_crash_pipeline(self):
        cfg = _make_config()
        mock_loader = MagicMock()

        with patch("pipeline.aggregator.BigQueryLoader", return_value=mock_loader):
            agg = DataAggregator(cfg, platforms=["google_ads", "meta_ads"])

        crashing_connector = MagicMock()
        crashing_connector.fetch.side_effect = RuntimeError("API down")
        ok_connector = self._make_mock_connector("meta_ads")

        def side_effect(platform):
            return {"google_ads": crashing_connector, "meta_ads": ok_connector}.get(platform)

        agg._get_connector = side_effect
        # Should not raise
        agg.run(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))

    def test_run_uses_explicit_dates(self):
        cfg = _make_config()
        mock_loader = MagicMock()

        with patch("pipeline.aggregator.BigQueryLoader", return_value=mock_loader):
            agg = DataAggregator(cfg, platforms=["google_ads"])

        mock_connector = self._make_mock_connector("google_ads")
        agg._get_connector = lambda p: mock_connector

        start = date(2024, 3, 1)
        end = date(2024, 3, 15)
        agg.run(start_date=start, end_date=end)

        call_args = mock_connector.fetch.call_args[0]
        assert call_args[0] == start
        assert call_args[1] == end
