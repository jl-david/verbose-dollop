"""Base class for all data source connectors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


class BaseConnector(ABC):
    """
    Abstract base class for all Looker Studio data source connectors.

    Every subclass must implement `fetch()`, which returns a normalised
    pandas DataFrame with at minimum the columns defined in `REQUIRED_COLUMNS`.
    """

    # Columns every connector must return so the pipeline can build the
    # unified_performance table without special-casing each source.
    REQUIRED_COLUMNS: list[str] = [
        "date",
        "platform",
        "campaign_id",
        "campaign_name",
        "impressions",
        "clicks",
        "spend",
        "conversions",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._log = structlog.get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    def fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        """
        Fetch data for the given date range.

        Returns a DataFrame containing at least REQUIRED_COLUMNS.
        """
        self._log.info(
            "fetching data",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        df = self._fetch(start_date, end_date)
        self._validate(df)
        return df

    def fetch_last_n_days(self, n: int = 30) -> pd.DataFrame:
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=n - 1)
        return self.fetch(start, end)

    # ------------------------------------------------------------------ #
    #  Subclass hooks                                                      #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _fetch(self, start_date: date, end_date: date) -> pd.DataFrame:
        """Fetch raw data and return a normalised DataFrame."""

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _validate(self, df: pd.DataFrame) -> None:
        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                f"{self.__class__.__name__} is missing required columns: {missing}"
            )

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
