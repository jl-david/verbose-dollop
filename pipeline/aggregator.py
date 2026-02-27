"""
DataAggregator
==============
Orchestrates all connectors, merges their DataFrames, and hands the
result to a loader (BigQuery by default).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import structlog

from data_sources import (
    GoogleAdsConnector,
    MetaAdsConnector,
    GoogleAnalyticsConnector,
    LinkedInAdsConnector,
    TwitterAdsConnector,
)
from .bigquery_loader import BigQueryLoader

logger = structlog.get_logger(__name__)

# Columns used to build the unified view – must be present in every connector output
UNIFIED_COLS = [
    "date", "platform", "campaign_id", "campaign_name",
    "impressions", "clicks", "spend", "conversions",
]


class DataAggregator:
    """
    Fetches data from all configured platforms and loads it into BigQuery.

    Parameters
    ----------
    config : dict
        Parsed config.yaml contents.
    platforms : list[str] | None
        If provided, only these platforms will run.
        Valid values: google_ads, meta_ads, google_analytics,
                      linkedin_ads, twitter_ads
    """

    ALL_PLATFORMS = [
        "google_ads",
        "meta_ads",
        "google_analytics",
        "linkedin_ads",
        "twitter_ads",
    ]

    def __init__(
        self,
        config: dict[str, Any],
        platforms: list[str] | None = None,
    ) -> None:
        self.config = config
        self.platforms = platforms or self.ALL_PLATFORMS
        self._loader = BigQueryLoader(config)

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    def run(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        lookback_days: int | None = None,
    ) -> None:
        """
        Fetch data from all active platforms and load it into BigQuery.
        """
        lookback = (
            lookback_days
            or self.config.get("pipeline", {}).get("lookback_days", 30)
        )
        end = end_date or (date.today() - timedelta(days=1))
        start = start_date or (end - timedelta(days=lookback - 1))

        logger.info("pipeline started", start=start.isoformat(), end=end.isoformat())

        platform_dfs: dict[str, pd.DataFrame] = {}

        for platform in self.platforms:
            connector = self._get_connector(platform)
            if connector is None:
                logger.warning("connector not found, skipping", platform=platform)
                continue
            try:
                df = connector.fetch(start, end)
                platform_dfs[platform] = df
                logger.info(
                    "fetched rows",
                    platform=platform,
                    rows=len(df),
                )
            except Exception as exc:
                logger.error("fetch failed", platform=platform, error=str(exc))

        if not platform_dfs:
            logger.warning("no data fetched from any platform")
            return

        # Load individual platform tables
        bq_tables = self.config.get("bigquery", {}).get("tables", {})
        for platform, df in platform_dfs.items():
            table = bq_tables.get(platform, f"{platform}_performance")
            self._loader.load(df, table)

        # Build and load unified view
        unified_df = self._build_unified(platform_dfs)
        self._loader.load(unified_df, bq_tables.get("unified", "unified_performance"))

        logger.info(
            "pipeline finished",
            total_rows=sum(len(d) for d in platform_dfs.values()),
            unified_rows=len(unified_df),
        )

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_connector(self, platform: str):
        mapping = {
            "google_ads": GoogleAdsConnector,
            "meta_ads": MetaAdsConnector,
            "google_analytics": GoogleAnalyticsConnector,
            "linkedin_ads": LinkedInAdsConnector,
            "twitter_ads": TwitterAdsConnector,
        }
        cls = mapping.get(platform)
        if cls is None:
            return None
        try:
            return cls(self.config)
        except Exception as exc:
            logger.error(
                "connector init failed", platform=platform, error=str(exc)
            )
            return None

    @staticmethod
    def _build_unified(platform_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Concatenates all platform DataFrames keeping only the shared columns,
        so Looker Studio always has a single cross-platform table.
        """
        frames: list[pd.DataFrame] = []
        for df in platform_dfs.values():
            available = [c for c in UNIFIED_COLS if c in df.columns]
            frames.append(df[available].copy())

        if not frames:
            return pd.DataFrame(columns=UNIFIED_COLS)

        unified = pd.concat(frames, ignore_index=True)

        # Ensure all required columns exist (fill missing with defaults)
        for col in UNIFIED_COLS:
            if col not in unified.columns:
                unified[col] = None

        unified["date"] = pd.to_datetime(unified["date"]).dt.date
        unified.sort_values(["date", "platform", "campaign_name"], inplace=True)
        unified.reset_index(drop=True, inplace=True)

        # Derived KPI columns useful in Looker Studio
        unified["ctr"] = unified.apply(
            lambda r: round(r["clicks"] / r["impressions"], 4)
            if r["impressions"] > 0 else 0.0,
            axis=1,
        )
        unified["cpc"] = unified.apply(
            lambda r: round(r["spend"] / r["clicks"], 4)
            if r["clicks"] > 0 else 0.0,
            axis=1,
        )
        unified["cpa"] = unified.apply(
            lambda r: round(r["spend"] / r["conversions"], 4)
            if r["conversions"] > 0 else 0.0,
            axis=1,
        )

        return unified
