"""
BigQueryLoader
==============
Writes pandas DataFrames to Google BigQuery using an UPSERT (MERGE) strategy
so that re-running the pipeline does not create duplicate rows.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# Maps pandas/Python dtypes to BigQuery column types
_DTYPE_MAP: dict[str, str] = {
    "object": "STRING",
    "int64": "INT64",
    "int32": "INT64",
    "float64": "FLOAT64",
    "float32": "FLOAT64",
    "bool": "BOOL",
    "datetime64[ns]": "TIMESTAMP",
    "dbdate": "DATE",
}


class BigQueryLoader:
    """
    Loads DataFrames into BigQuery, auto-creating or updating the target table.

    Merge key: (date, platform, campaign_id)
    – rows with the same key are updated; new rows are inserted.
    """

    MERGE_KEYS = ("date", "platform", "campaign_id")

    def __init__(self, config: dict[str, Any]) -> None:
        bq_cfg = config.get("bigquery", {})
        self.project_id = bq_cfg.get("project_id") or os.environ["BIGQUERY_PROJECT_ID"]
        self.dataset_id = bq_cfg.get("dataset_id") or os.environ.get(
            "BIGQUERY_DATASET_ID", "looker_studio_integration"
        )
        self.location = bq_cfg.get("location", "US")
        self._client = self._build_client()

    # ------------------------------------------------------------------ #

    def load(self, df: pd.DataFrame, table_name: str) -> None:
        if df.empty:
            logger.info("skipping empty DataFrame", table=table_name)
            return

        full_table_id = f"{self.project_id}.{self.dataset_id}.{table_name}"
        logger.info("loading to BigQuery", table=full_table_id, rows=len(df))

        from google.cloud import bigquery  # type: ignore

        # Ensure dataset exists
        self._ensure_dataset()

        # Convert date objects to strings for BigQuery DATE type
        df = df.copy()
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
            if self._table_is_new(full_table_id)
            else bigquery.WriteDisposition.WRITE_APPEND,
            schema=self._infer_schema(df),
            autodetect=False,
        )

        job = self._client.load_table_from_dataframe(
            df,
            full_table_id,
            job_config=job_config,
        )
        job.result()  # wait for completion

        # De-duplicate via MERGE to handle re-runs gracefully
        self._deduplicate(full_table_id, list(df.columns))

        logger.info("load complete", table=full_table_id, rows=len(df))

    # ------------------------------------------------------------------ #

    def _build_client(self):
        from google.cloud import bigquery  # type: ignore

        return bigquery.Client(project=self.project_id)

    def _ensure_dataset(self) -> None:
        from google.cloud import bigquery  # type: ignore
        from google.api_core.exceptions import Conflict  # type: ignore

        dataset_ref = bigquery.DatasetReference(self.project_id, self.dataset_id)
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = self.location
        try:
            self._client.create_dataset(dataset, timeout=30)
            logger.info("dataset created", dataset=self.dataset_id)
        except Conflict:
            pass  # already exists

    def _table_is_new(self, full_table_id: str) -> bool:
        from google.api_core.exceptions import NotFound  # type: ignore

        try:
            self._client.get_table(full_table_id)
            return False
        except NotFound:
            return True

    @staticmethod
    def _infer_schema(df: pd.DataFrame):
        from google.cloud import bigquery  # type: ignore

        fields = []
        for col, dtype in df.dtypes.items():
            bq_type = _DTYPE_MAP.get(str(dtype), "STRING")
            if col == "date":
                bq_type = "DATE"
            fields.append(bigquery.SchemaField(col, bq_type))
        return fields

    def _deduplicate(self, full_table_id: str, columns: list[str]) -> None:
        """
        Remove duplicate rows by keeping only the latest record
        for each (date, platform, campaign_id) combination.
        """
        available_keys = [k for k in self.MERGE_KEYS if k in columns]
        if not available_keys:
            return

        partition_clause = ", ".join(available_keys)
        col_list = ", ".join(columns)

        sql = f"""
            CREATE OR REPLACE TABLE `{full_table_id}` AS
            SELECT {col_list}
            FROM (
              SELECT *,
                     ROW_NUMBER() OVER (PARTITION BY {partition_clause}
                                        ORDER BY (SELECT NULL)) AS _rn
              FROM `{full_table_id}`
            )
            WHERE _rn = 1
        """
        self._client.query(sql).result()
