"""Tests for pipeline/bigquery_loader.py (BigQueryLoader)."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

from tests.conftest import SAMPLE_CONFIG, make_performance_df


# ---------------------------------------------------------------------------
# Stub the google-cloud-bigquery modules (not installed in test env)
# ---------------------------------------------------------------------------

def _make_bq_modules():
    """Return minimal stubs for google-cloud-bigquery imports."""
    google_mod = sys.modules.get("google") or ModuleType("google")
    cloud_mod = ModuleType("google.cloud")
    bq_mod = ModuleType("google.cloud.bigquery")
    api_core_mod = ModuleType("google.api_core")
    exceptions_mod = ModuleType("google.api_core.exceptions")

    # BigQuery stubs
    mock_client_cls = MagicMock(name="Client")
    mock_dataset_ref_cls = MagicMock(name="DatasetReference")
    mock_dataset_cls = MagicMock(name="Dataset")
    mock_schema_field_cls = MagicMock(name="SchemaField")
    mock_load_job_config_cls = MagicMock(name="LoadJobConfig")

    class _WriteDisposition:
        WRITE_TRUNCATE = "WRITE_TRUNCATE"
        WRITE_APPEND = "WRITE_APPEND"

    bq_mod.Client = mock_client_cls
    bq_mod.DatasetReference = mock_dataset_ref_cls
    bq_mod.Dataset = mock_dataset_cls
    bq_mod.SchemaField = mock_schema_field_cls
    bq_mod.LoadJobConfig = mock_load_job_config_cls
    bq_mod.WriteDisposition = _WriteDisposition

    # Exceptions stubs
    class _Conflict(Exception):
        pass

    class _NotFound(Exception):
        pass

    exceptions_mod.Conflict = _Conflict
    exceptions_mod.NotFound = _NotFound

    google_mod.cloud = cloud_mod
    cloud_mod.bigquery = bq_mod
    google_mod.api_core = api_core_mod
    api_core_mod.exceptions = exceptions_mod

    stubs = {
        "google": google_mod,
        "google.cloud": cloud_mod,
        "google.cloud.bigquery": bq_mod,
        "google.api_core": api_core_mod,
        "google.api_core.exceptions": exceptions_mod,
    }
    return stubs, {
        "Client": mock_client_cls,
        "DatasetReference": mock_dataset_ref_cls,
        "Dataset": mock_dataset_cls,
        "SchemaField": mock_schema_field_cls,
        "LoadJobConfig": mock_load_job_config_cls,
        "WriteDisposition": _WriteDisposition,
        "Conflict": _Conflict,
        "NotFound": _NotFound,
    }


# ---------------------------------------------------------------------------
# Helper: create a loader with a fully mocked BQ client
# ---------------------------------------------------------------------------

def _make_loader(bq_stubs):
    """Return a BigQueryLoader with the BQ client mocked out."""
    from pipeline.bigquery_loader import BigQueryLoader

    loader = BigQueryLoader.__new__(BigQueryLoader)
    loader.project_id = "test-project"
    loader.dataset_id = "test_dataset"
    loader.location = "US"
    loader._client = MagicMock(name="bq_client")

    # By default, make get_table succeed (table exists)
    loader._client.get_table.return_value = MagicMock()
    # load_table_from_dataframe returns a job that completes
    mock_job = MagicMock()
    mock_job.result.return_value = None
    loader._client.load_table_from_dataframe.return_value = mock_job
    # query for deduplication also completes
    mock_query = MagicMock()
    mock_query.result.return_value = None
    loader._client.query.return_value = mock_query

    return loader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBigQueryLoader:
    @pytest.fixture(autouse=True)
    def _mock_bq(self):
        stubs, helpers = _make_bq_modules()
        with patch.dict(sys.modules, stubs):
            self._bq = helpers
            yield

    @pytest.fixture()
    def loader(self):
        return _make_loader(self._bq)

    def test_load_calls_load_table_from_dataframe(self, loader):
        df = make_performance_df("google_ads")
        loader.load(df, "google_ads_performance")
        loader._client.load_table_from_dataframe.assert_called_once()

    def test_load_skips_empty_dataframe(self, loader):
        df = pd.DataFrame()
        loader.load(df, "google_ads_performance")
        loader._client.load_table_from_dataframe.assert_not_called()

    def test_load_calls_deduplication_query(self, loader):
        df = make_performance_df("google_ads")
        loader.load(df, "google_ads_performance")
        loader._client.query.assert_called_once()

    def test_load_uses_correct_table_id(self, loader):
        df = make_performance_df("meta_ads")
        loader.load(df, "meta_ads_performance")
        call_args = loader._client.load_table_from_dataframe.call_args
        # second positional arg is the full table id
        full_table_id = call_args[0][1]
        assert full_table_id == "test-project.test_dataset.meta_ads_performance"

    def test_date_column_converted_to_string(self, loader):
        """date objects must be converted to strings before loading."""
        from datetime import date

        df = make_performance_df("google_ads")
        assert isinstance(df["date"].iloc[0], date)

        loader.load(df, "google_ads_performance")

        # Check the DataFrame passed to load_table_from_dataframe has str dates
        call_args = loader._client.load_table_from_dataframe.call_args
        loaded_df = call_args[0][0]
        assert isinstance(loaded_df["date"].iloc[0], str)

    def test_merge_keys_present_triggers_dedup(self, loader):
        df = make_performance_df("google_ads")
        loader.load(df, "google_ads_performance")

        sql = loader._client.query.call_args[0][0]
        assert "ROW_NUMBER" in sql
        assert "PARTITION BY" in sql

    def test_write_truncate_for_new_table(self, loader):
        # Simulate table not found → _table_is_new returns True
        loader._client.get_table.side_effect = self._bq["NotFound"]("table not found")

        df = make_performance_df("google_ads")
        loader.load(df, "new_table")

        # The LoadJobConfig constructor should have been called with WRITE_TRUNCATE
        load_job_config_cls = self._bq["LoadJobConfig"]
        kwargs = load_job_config_cls.call_args[1]
        assert kwargs["write_disposition"] == "WRITE_TRUNCATE"

    def test_write_append_for_existing_table(self, loader):
        # get_table succeeds → table exists → _table_is_new returns False
        loader._client.get_table.return_value = MagicMock()

        df = make_performance_df("google_ads")
        loader.load(df, "existing_table")

        load_job_config_cls = self._bq["LoadJobConfig"]
        kwargs = load_job_config_cls.call_args[1]
        assert kwargs["write_disposition"] == "WRITE_APPEND"

    def test_ensure_dataset_handles_conflict(self, loader):
        """If dataset already exists, Conflict is silently ignored."""
        loader._client.create_dataset.side_effect = self._bq["Conflict"]("already exists")

        df = make_performance_df("google_ads")
        # Should not raise
        loader.load(df, "google_ads_performance")


class TestBigQueryLoaderInferSchema:
    @pytest.fixture(autouse=True)
    def _mock_bq(self):
        stubs, helpers = _make_bq_modules()
        with patch.dict(sys.modules, stubs):
            self._bq = helpers
            yield

    def test_infer_schema_date_column_is_date_type(self):
        from pipeline.bigquery_loader import BigQueryLoader

        df = make_performance_df("test")
        df["date"] = df["date"].astype(str)

        schema_field_cls = self._bq["SchemaField"]
        schema_field_cls.reset_mock()

        BigQueryLoader._infer_schema(df)

        # Verify SchemaField was called with ("date", "DATE") for the date column
        call_kwargs = {c[0][0]: c[0][1] for c in schema_field_cls.call_args_list}
        assert call_kwargs.get("date") == "DATE"

    def test_infer_schema_numeric_columns(self):
        from pipeline.bigquery_loader import BigQueryLoader

        df = make_performance_df("test")
        df["date"] = df["date"].astype(str)

        schema_field_cls = self._bq["SchemaField"]
        schema_field_cls.reset_mock()

        BigQueryLoader._infer_schema(df)

        call_kwargs = {c[0][0]: c[0][1] for c in schema_field_cls.call_args_list}
        # impressions/clicks are int → INT64
        assert call_kwargs.get("impressions") == "INT64"
        # spend is float → FLOAT64
        assert call_kwargs.get("spend") == "FLOAT64"
