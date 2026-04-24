"""Tests for connector-specific pure helper functions."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from data_sources.linkedin_ads import LinkedInAdsConnector
from data_sources.twitter_ads import _to_utc_iso, _bucket_to_date


# ---------------------------------------------------------------------------
# LinkedIn: _parse_linkedin_date
# ---------------------------------------------------------------------------

class TestParseLinkedInDate:
    def test_standard_date(self):
        date_range = {"start": {"year": 2024, "month": 3, "day": 15}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2024-03-15"

    def test_zero_padded_month_and_day(self):
        date_range = {"start": {"year": 2024, "month": 1, "day": 5}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2024-01-05"

    def test_empty_dict_returns_epoch(self):
        result = LinkedInAdsConnector._parse_linkedin_date({})
        assert result == "1970-01-01"

    def test_missing_start_key_returns_epoch(self):
        result = LinkedInAdsConnector._parse_linkedin_date({"end": {"year": 2024}})
        assert result == "1970-01-01"

    def test_partial_start_uses_defaults(self):
        date_range = {"start": {"year": 2024}}  # month and day missing
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2024-01-01"

    def test_end_of_year(self):
        date_range = {"start": {"year": 2023, "month": 12, "day": 31}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2023-12-31"

    def test_leap_day(self):
        date_range = {"start": {"year": 2024, "month": 2, "day": 29}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert result == "2024-02-29"

    def test_return_type_is_string(self):
        date_range = {"start": {"year": 2024, "month": 6, "day": 10}}
        result = LinkedInAdsConnector._parse_linkedin_date(date_range)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Twitter: _to_utc_iso
# ---------------------------------------------------------------------------

class TestToUtcIso:
    def test_basic_date(self):
        d = date(2024, 1, 15)
        result = _to_utc_iso(d)
        assert "2024-01-15" in result

    def test_result_has_utc_offset(self):
        d = date(2024, 6, 1)
        result = _to_utc_iso(d)
        assert "+00:00" in result or "Z" in result or "UTC" in result

    def test_midnight_time(self):
        d = date(2024, 3, 10)
        result = _to_utc_iso(d)
        # Should start at midnight (T00:00:00)
        assert "T00:00:00" in result

    def test_return_type_is_string(self):
        result = _to_utc_iso(date(2024, 1, 1))
        assert isinstance(result, str)

    def test_year_boundary(self):
        d = date(2023, 12, 31)
        result = _to_utc_iso(d)
        assert "2023-12-31" in result

    def test_first_day_of_year(self):
        d = date(2024, 1, 1)
        result = _to_utc_iso(d)
        assert "2024-01-01" in result


# ---------------------------------------------------------------------------
# Twitter: _bucket_to_date
# ---------------------------------------------------------------------------

class TestBucketToDate:
    def test_bucket_zero_is_start_date(self):
        start = date(2024, 1, 10)
        result = _bucket_to_date(start, 0)
        assert result == start

    def test_bucket_one_is_next_day(self):
        start = date(2024, 1, 10)
        result = _bucket_to_date(start, 1)
        assert result == date(2024, 1, 11)

    def test_large_bucket_index(self):
        start = date(2024, 1, 1)
        result = _bucket_to_date(start, 30)
        assert result == date(2024, 1, 31)

    def test_crosses_month_boundary(self):
        start = date(2024, 1, 30)
        result = _bucket_to_date(start, 2)
        assert result == date(2024, 2, 1)

    def test_crosses_year_boundary(self):
        start = date(2023, 12, 30)
        result = _bucket_to_date(start, 2)
        assert result == date(2024, 1, 1)

    def test_return_type_is_date(self):
        result = _bucket_to_date(date(2024, 6, 1), 5)
        assert isinstance(result, date)
