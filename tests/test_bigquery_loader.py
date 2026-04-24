"""Tests for pipeline/bigquery_loader.py – BigQueryLoader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import os

import pandas as pd
import pytest

# We patch google.cloud.bigquery before importing BigQueryLoader so the import
# succeeds even without the real library installed.
import sys
import types

# Minimal mock for google.cloud.bigquery
_bq_mock = types.ModuleType("google.cloud.bigquery")
_bq_mock.Client = MagicMock()
_bq_mock.SchemaField = MagicMock(side_effect=lambda name, bq_type: (name, bq_type))
_bq_mock.Dataset = MagicMock()
_bq_mock.DatasetReference = MagicMock()
_bq_mock.LoadJobConfig = MagicMock()

class _WriteDisposition:
    WRITE_TRUNCATE = "WRITE_TRUNCATE"
    WRITE_APPEND = "WRITE_APPEND"

_bq_mock.WriteDisposition = _WriteDisposition()

_google_mock = types.ModuleType("google")
_google_cloud_mock = types.ModuleType("google.cloud")
_google_api_core_mock = types.ModuleType("google.api_core")
_google_api_core_exceptions_mock = types.ModuleType("google.api_core.exceptions")
_google_api_core_exceptions_mock.Conflict = Exception
_google_api_core_exceptions_mock.NotFound = Exception

sys.modules.setdefault("google", _google_mock)
sys.modules.setdefault("google.cloud", _google_cloud_mock)
sys.modules.setdefault("google.cloud.bigquery", _bq_mock)
sys.modules.setdefault("google.api_core", _google_api_core_mock)
sys.modules.setdefault("google.api_core.exceptions", _google_api_core_exceptions_mock)
_google_cloud_mock.bigquery = _bq_mock

from pipeline.bigquery_loader import BigQueryLoader, _DTYPE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(project_id: str = "proj", dataset_id: str = "ds") -> dict:
    return {
        "bigquery": {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "location": "US",
        }
    }


def _make_loader(project_id: str = "proj", dataset_id: str = "ds") -> BigQueryLoader:
    with patch("pipeline.bigquery_loader.BigQueryLoader._build_client", return_value=MagicMock()):
        return BigQueryLoader(_make_config(project_id, dataset_id))


def _make_df(n: int = 2) -> pd.DataFrame:
    import datetime
    rows = []
    for i in range(n):
        rows.append({
            "date": datetime.date(2024, 1, i + 1),
            "platform": "google_ads",
            "campaign_id": f"c{i}",
            "campaign_name": f"Campaign {i}",
            "impressions": 1000 + i,
            "clicks": 100 + i,
            "spend": 50.0 + i,
            "conversions": 5.0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _infer_schema
# ---------------------------------------------------------------------------

class TestInferSchema:
    def test_date_column_gets_date_type(self):
        df = pd.DataFrame({"date": ["2024-01-01"], "value": [1]})
        schema = BigQueryLoader._infer_schema(df)
        # Find the date field
        date_field = next((f for f in schema if f[0] == "date"), None)
        assert date_field is not None
        assert date_field[1] == "DATE"

    def test_int64_column_maps_to_int64(self):
        df = pd.DataFrame({"clicks": pd.array([100], dtype="int64")})
        schema = BigQueryLoader._infer_schema(df)
        clicks_field = next((f for f in schema if f[0] == "clicks"), None)
        assert clicks_field is not None
        assert clicks_field[1] == "INT64"

    def test_float64_column_maps_to_float64(self):
        df = pd.DataFrame({"spend": pd.array([50.0], dtype="float64")})
        schema = BigQueryLoader._infer_schema(df)
        spend_field = next((f for f in schema if f[0] == "spend"), None)
        assert spend_field is not None
        assert spend_field[1] == "FLOAT64"

    def test_object_column_maps_to_string(self):
        df = pd.DataFrame({"name": ["campaign_a"]})
        schema = BigQueryLoader._infer_schema(df)
        name_field = next((f for f in schema if f[0] == "name"), None)
        assert name_field is not None
        assert name_field[1] == "STRING"

    def test_bool_column_maps_to_bool(self):
        df = pd.DataFrame({"active": pd.array([True], dtype="bool")})
        schema = BigQueryLoader._infer_schema(df)
        active_field = next((f for f in schema if f[0] == "active"), None)
        assert active_field is not None
        assert active_field[1] == "BOOL"

    def test_unknown_dtype_defaults_to_string(self):
        df = pd.DataFrame({"mixed": pd.Categorical(["a", "b"])})
        schema = BigQueryLoader._infer_schema(df)
        mixed_field = next((f for f in schema if f[0] == "mixed"), None)
        assert mixed_field is not None
        assert mixed_field[1] == "STRING"


# ---------------------------------------------------------------------------
# _DTYPE_MAP
# ---------------------------------------------------------------------------

class TestDtypeMap:
    def test_all_expected_types_present(self):
        for key in ["object", "int64", "float64", "bool", "datetime64[ns]"]:
            assert key in _DTYPE_MAP


# ---------------------------------------------------------------------------
# load – skip empty
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_skips_empty_dataframe(self):
        loader = _make_loader()
        loader.load(pd.DataFrame(), "some_table")
        loader._client.load_table_from_dataframe.assert_not_called()

    def test_load_calls_client_for_non_empty_dataframe(self):
        loader = _make_loader()
        df = _make_df(2)

        mock_job = MagicMock()
        loader._client.load_table_from_dataframe.return_value = mock_job
        loader._client.get_table.side_effect = _google_api_core_exceptions_mock.NotFound

        with patch.object(loader, "_ensure_dataset"):
            with patch.object(loader, "_deduplicate"):
                loader.load(df, "test_table")

        loader._client.load_table_from_dataframe.assert_called_once()

    def test_load_converts_date_column_to_string(self):
        import datetime
        import pandas as pd
        loader = _make_loader()
        df = _make_df(1)

        captured_df = {}

        def capture_load(df_arg, *args, **kwargs):
            captured_df["df"] = df_arg
            mock_job = MagicMock()
            return mock_job

        loader._client.load_table_from_dataframe.side_effect = capture_load
        loader._client.get_table.side_effect = _google_api_core_exceptions_mock.NotFound

        with patch.object(loader, "_ensure_dataset"):
            with patch.object(loader, "_deduplicate"):
                loader.load(df, "test_table")

        # date column should be converted to string (may be object or StringDtype)
        assert pd.api.types.is_string_dtype(captured_df["df"]["date"])


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_builds_correct_sql_with_all_merge_keys(self):
        loader = _make_loader()
        mock_query = MagicMock()
        loader._client.query = mock_query

        columns = ["date", "platform", "campaign_id", "clicks", "spend"]
        loader._deduplicate("proj.ds.test_table", columns)

        sql_called = mock_query.call_args[0][0]
        assert "PARTITION BY date, platform, campaign_id" in sql_called
        assert "proj.ds.test_table" in sql_called

    def test_skips_missing_merge_keys(self):
        loader = _make_loader()
        mock_query = MagicMock()
        loader._client.query = mock_query

        # Only 'date' is an available merge key
        columns = ["date", "clicks", "spend"]
        loader._deduplicate("proj.ds.test_table", columns)

        sql_called = mock_query.call_args[0][0]
        assert "PARTITION BY date" in sql_called
        assert "platform" not in sql_called

    def test_no_merge_keys_skips_dedup(self):
        loader = _make_loader()
        loader._client.query = MagicMock()

        columns = ["clicks", "spend"]  # No MERGE_KEYS present
        loader._deduplicate("proj.ds.test_table", columns)

        loader._client.query.assert_not_called()

    def test_col_list_includes_all_columns(self):
        loader = _make_loader()
        mock_query = MagicMock()
        loader._client.query = mock_query

        columns = ["date", "platform", "campaign_id", "clicks", "spend"]
        loader._deduplicate("proj.ds.test_table", columns)

        sql_called = mock_query.call_args[0][0]
        for col in columns:
            assert col in sql_called


# ---------------------------------------------------------------------------
# BigQueryLoader.__init__
# ---------------------------------------------------------------------------

class TestBigQueryLoaderInit:
    def test_reads_project_from_config(self):
        loader = _make_loader(project_id="my-project")
        assert loader.project_id == "my-project"

    def test_reads_dataset_from_config(self):
        loader = _make_loader(dataset_id="my_dataset")
        assert loader.dataset_id == "my_dataset"

    def test_reads_project_from_env_when_not_in_config(self, monkeypatch):
        monkeypatch.setenv("BIGQUERY_PROJECT_ID", "env-project")
        with patch("pipeline.bigquery_loader.BigQueryLoader._build_client", return_value=MagicMock()):
            loader = BigQueryLoader({"bigquery": {}})
        assert loader.project_id == "env-project"

    def test_default_location_is_us(self):
        loader = _make_loader()
        assert loader.location == "US"

    def test_merge_keys_constant(self):
        assert BigQueryLoader.MERGE_KEYS == ("date", "platform", "campaign_id")
