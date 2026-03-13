"""Tests for data_sources/base.py (BaseConnector)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from data_sources.base import BaseConnector
from tests.conftest import SAMPLE_CONFIG, make_performance_df


# ---------------------------------------------------------------------------
# Concrete subclass used only in tests
# ---------------------------------------------------------------------------

class _FakeConnector(BaseConnector):
    """Minimal concrete connector for testing BaseConnector behaviour."""

    def __init__(self, config, return_df=None, raise_on_fetch=None):
        super().__init__(config)
        self._return_df = return_df if return_df is not None else make_performance_df("test")
        self._raise_on_fetch = raise_on_fetch

    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self._return_df


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_numeric_string(self):
        assert BaseConnector._safe_float("3.14") == pytest.approx(3.14)

    def test_integer(self):
        assert BaseConnector._safe_float(42) == pytest.approx(42.0)

    def test_float(self):
        assert BaseConnector._safe_float(1.5) == pytest.approx(1.5)

    def test_none_returns_default(self):
        assert BaseConnector._safe_float(None) == 0.0

    def test_non_numeric_string_returns_default(self):
        assert BaseConnector._safe_float("abc") == 0.0

    def test_custom_default(self):
        assert BaseConnector._safe_float(None, default=-1.0) == -1.0


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_numeric_string(self):
        assert BaseConnector._safe_int("7") == 7

    def test_float_truncates(self):
        assert BaseConnector._safe_int(3.9) == 3

    def test_none_returns_default(self):
        assert BaseConnector._safe_int(None) == 0

    def test_non_numeric_string_returns_default(self):
        assert BaseConnector._safe_int("xyz") == 0

    def test_custom_default(self):
        assert BaseConnector._safe_int(None, default=99) == 99


# ---------------------------------------------------------------------------
# _validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_all_required_columns_present(self):
        connector = _FakeConnector(SAMPLE_CONFIG)
        df = make_performance_df("test")
        # Should not raise
        connector._validate(df)

    def test_missing_column_raises(self):
        connector = _FakeConnector(SAMPLE_CONFIG)
        df = make_performance_df("test").drop(columns=["spend"])
        with pytest.raises(ValueError, match="missing required columns"):
            connector._validate(df)

    def test_multiple_missing_columns_listed(self):
        connector = _FakeConnector(SAMPLE_CONFIG)
        df = make_performance_df("test").drop(columns=["spend", "clicks"])
        with pytest.raises(ValueError) as exc_info:
            connector._validate(df)
        msg = str(exc_info.value)
        assert "spend" in msg
        assert "clicks" in msg


# ---------------------------------------------------------------------------
# fetch / fetch_last_n_days
# ---------------------------------------------------------------------------

class TestFetch:
    def test_fetch_returns_dataframe(self):
        connector = _FakeConnector(SAMPLE_CONFIG)
        df = connector.fetch(date(2024, 1, 1), date(2024, 1, 7))
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_fetch_calls_validate(self):
        """Fetch should raise if _fetch returns a DF with missing columns."""
        bad_df = pd.DataFrame({"date": [date(2024, 1, 1)]})
        connector = _FakeConnector(SAMPLE_CONFIG, return_df=bad_df)
        with pytest.raises(ValueError, match="missing required columns"):
            connector.fetch(date(2024, 1, 1), date(2024, 1, 1))

    def test_fetch_propagates_exception(self):
        connector = _FakeConnector(
            SAMPLE_CONFIG, raise_on_fetch=RuntimeError("API down")
        )
        with pytest.raises(RuntimeError, match="API down"):
            connector.fetch(date(2024, 1, 1), date(2024, 1, 1))

    def test_fetch_last_n_days_date_range(self, monkeypatch):
        calls = []

        class _Recorder(_FakeConnector):
            def _fetch(self, start_date, end_date):
                calls.append((start_date, end_date))
                return make_performance_df("test")

        fixed_today = date(2024, 3, 15)
        monkeypatch.setattr(
            "data_sources.base.date",
            type("_FakeDate", (), {"today": staticmethod(lambda: fixed_today)}),
        )

        connector = _Recorder(SAMPLE_CONFIG)
        connector.fetch_last_n_days(n=7)

        start, end = calls[0]
        assert end == fixed_today - timedelta(days=1)
        assert start == end - timedelta(days=6)
