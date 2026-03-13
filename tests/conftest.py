"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Minimal config that mirrors config/config.yaml (no credentials needed)
# ---------------------------------------------------------------------------

SAMPLE_CONFIG: dict = {
    "bigquery": {
        "project_id": "test-project",
        "dataset_id": "test_dataset",
        "location": "US",
        "tables": {
            "google_ads": "google_ads_performance",
            "meta_ads": "meta_ads_performance",
            "google_analytics": "ga4_performance",
            "linkedin_ads": "linkedin_ads_performance",
            "twitter_ads": "twitter_ads_performance",
            "unified": "unified_performance",
        },
    },
    "pipeline": {
        "lookback_days": 30,
        "batch_size": 1000,
        "retry_attempts": 3,
        "retry_delay_seconds": 5,
    },
    "google_ads": {"api_version": "v16"},
    "meta_ads": {"level": "ad"},
    "google_analytics": {},
    "linkedin_ads": {},
    "twitter_ads": {"granularity": "DAY"},
}

START_DATE = date(2024, 1, 1)
END_DATE = date(2024, 1, 7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_performance_df(platform: str, rows: int = 3) -> pd.DataFrame:
    """Return a minimal DataFrame that satisfies REQUIRED_COLUMNS."""
    return pd.DataFrame(
        {
            "date": [date(2024, 1, i + 1) for i in range(rows)],
            "platform": [platform] * rows,
            "campaign_id": [f"cid_{i}" for i in range(rows)],
            "campaign_name": [f"Campaign {i}" for i in range(rows)],
            "impressions": [1000 * (i + 1) for i in range(rows)],
            "clicks": [50 * (i + 1) for i in range(rows)],
            "spend": [25.0 * (i + 1) for i in range(rows)],
            "conversions": [5.0 * (i + 1) for i in range(rows)],
        }
    )


@pytest.fixture()
def sample_config() -> dict:
    return SAMPLE_CONFIG


@pytest.fixture()
def date_range():
    return START_DATE, END_DATE
