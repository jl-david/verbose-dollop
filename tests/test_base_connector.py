"""Tests for data_sources/base.py – BaseConnector."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_sources.base import BaseConnector


# ---------------------------------------------------------------------------
# Concrete stub so we can instantiate the abstract class
# ---------------------------------------------------------------------------

class _StubConnector(BaseConnector):
    """Minimal concrete implementation for testing the base class."""

    def __init__(self, config: dict, fetch_df: pd.DataFrame | None = None) -> None:
        super().__init__(config)
        self._fetch_df = fetch_df if fetch_df is not None else self._make_valid_df()

    @staticmethod
    def _make_valid_df() -> pd.DataFrame:
        return pd.DataFrame([{
            "date": date(2024, 1, 1),
            "platform": "stub",
            "campaign_id": "c1",
            "campaign_name": "Test Campaign",
            "impressions": 1000,
            "clicks": 50,
            "spend": 100.0,
            "conversions": 5.0,
        }])

    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        return self._fetch_df


CONFIG = {}


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_integer_input(self):
        assert BaseConnector._safe_float(42) == 42.0

    def test_float_input(self):
        assert BaseConnector._safe_float(3.14) == pytest.approx(3.14)

    def test_string_number(self):
        assert BaseConnector._safe_float("2.5") == 2.5

    def test_none_returns_default(self):
        assert BaseConnector._safe_float(None) == 0.0

    def test_non_numeric_string_returns_default(self):
        assert BaseConnector._safe_float("abc") == 0.0

    def test_custom_default(self):
        assert BaseConnector._safe_float("bad", default=-1.0) == -1.0

    def test_empty_string_returns_default(self):
        assert BaseConnector._safe_float("") == 0.0

    def test_zero(self):
        assert BaseConnector._safe_float(0) == 0.0

    def test_negative_value(self):
        assert BaseConnector._safe_float(-5.5) == -5.5


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_integer_input(self):
        assert BaseConnector._safe_int(100) == 100

    def test_string_number(self):
        assert BaseConnector._safe_int("99") == 99

    def test_float_truncates(self):
        assert BaseConnector._safe_int(3.9) == 3

    def test_none_returns_default(self):
        assert BaseConnector._safe_int(None) == 0

    def test_non_numeric_string_returns_default(self):
        assert BaseConnector._safe_int("abc") == 0

    def test_custom_default(self):
        assert BaseConnector._safe_int("bad", default=-1) == -1

    def test_zero(self):
        assert BaseConnector._safe_int(0) == 0

    def test_negative_value(self):
        assert BaseConnector._safe_int(-7) == -7


# ---------------------------------------------------------------------------
# _validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_valid_dataframe_passes(self):
        connector = _StubConnector(CONFIG)
        # Should not raise
        connector._validate(_StubConnector._make_valid_df())

    def test_missing_single_column_raises(self):
        connector = _StubConnector(CONFIG)
        df = _StubConnector._make_valid_df().drop(columns=["impressions"])
        with pytest.raises(ValueError, match="impressions"):
            connector._validate(df)

    def test_missing_multiple_columns_raises(self):
        connector = _StubConnector(CONFIG)
        df = _StubConnector._make_valid_df().drop(columns=["clicks", "spend"])
        with pytest.raises(ValueError, match="_StubConnector"):
            connector._validate(df)

    def test_empty_dataframe_with_all_required_columns_passes(self):
        connector = _StubConnector(CONFIG)
        df = pd.DataFrame(columns=BaseConnector.REQUIRED_COLUMNS)
        connector._validate(df)

    def test_extra_columns_do_not_cause_failure(self):
        connector = _StubConnector(CONFIG)
        df = _StubConnector._make_valid_df()
        df["extra_col"] = "extra"
        connector._validate(df)  # Should not raise


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

class TestFetch:
    def test_fetch_calls_internal_fetch_and_validate(self):
        connector = _StubConnector(CONFIG)
        start = date(2024, 1, 1)
        end = date(2024, 1, 31)
        result = connector.fetch(start, end)

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert "date" in result.columns

    def test_fetch_raises_if_df_is_invalid(self):
        bad_df = pd.DataFrame([{"only_col": 1}])
        connector = _StubConnector(CONFIG, fetch_df=bad_df)
        with pytest.raises(ValueError):
            connector.fetch(date(2024, 1, 1), date(2024, 1, 31))

    def test_fetch_returns_dataframe_from_internal_fetch(self):
        valid_df = _StubConnector._make_valid_df()
        valid_df["impressions"] = 999
        connector = _StubConnector(CONFIG, fetch_df=valid_df)
        result = connector.fetch(date(2024, 1, 1), date(2024, 1, 31))
        assert result.iloc[0]["impressions"] == 999


# ---------------------------------------------------------------------------
# fetch_last_n_days
# ---------------------------------------------------------------------------

class TestFetchLastNDays:
    def test_default_30_days(self):
        connector = _StubConnector(CONFIG)
        with patch.object(connector, "fetch", wraps=connector.fetch) as mock_fetch:
            connector.fetch_last_n_days(30)
            args = mock_fetch.call_args[0]
            start, end = args[0], args[1]
            assert (end - start).days == 29  # 30 days inclusive

    def test_custom_n_days(self):
        connector = _StubConnector(CONFIG)
        with patch.object(connector, "fetch", wraps=connector.fetch) as mock_fetch:
            connector.fetch_last_n_days(7)
            args = mock_fetch.call_args[0]
            start, end = args[0], args[1]
            assert (end - start).days == 6  # 7 days inclusive

    def test_end_is_yesterday(self):
        connector = _StubConnector(CONFIG)
        from datetime import date as _date
        import datetime

        today = _date.today()
        yesterday = today - datetime.timedelta(days=1)

        with patch.object(connector, "fetch", wraps=connector.fetch) as mock_fetch:
            connector.fetch_last_n_days(1)
            args = mock_fetch.call_args[0]
            end = args[1]
            assert end == yesterday
