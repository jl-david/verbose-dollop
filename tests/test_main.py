"""Tests for main.py – load_config, parse_args, and run_scheduled cron parsing."""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_main_module():
    """Import main without triggering load_dotenv side-effects at module level."""
    import importlib
    # patch load_dotenv and DataAggregator before importing
    with patch("dotenv.load_dotenv"):
        import main
        importlib.reload(main)
    return main


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_yaml_and_returns_dict(self, monkeypatch):
        yaml_content = (
            "bigquery:\n"
            "  project_id: my-project\n"
            "  dataset_id: my_dataset\n"
            "pipeline:\n"
            "  lookback_days: 30\n"
        )
        with patch("dotenv.load_dotenv"):
            import main

        import io
        with patch("builtins.open", return_value=io.StringIO(yaml_content)):
            result = main.load_config()

        assert result["bigquery"]["project_id"] == "my-project"
        assert result["pipeline"]["lookback_days"] == 30

    def test_substitutes_env_vars(self, monkeypatch):
        yaml_content = "project_id: ${MY_PROJECT_VAR}\n"
        monkeypatch.setenv("MY_PROJECT_VAR", "substituted-value")

        with patch("dotenv.load_dotenv"):
            import main

        with patch("builtins.open", return_value=io.StringIO(yaml_content)):
            result = main.load_config()

        assert result["project_id"] == "substituted-value"

    def test_unknown_env_var_placeholder_left_as_is(self, monkeypatch):
        yaml_content = "value: ${DEFINITELY_NOT_SET_12345}\n"
        monkeypatch.delenv("DEFINITELY_NOT_SET_12345", raising=False)

        with patch("dotenv.load_dotenv"):
            import main

        with patch("builtins.open", return_value=io.StringIO(yaml_content)):
            result = main.load_config()

        assert result["value"] == "${DEFINITELY_NOT_SET_12345}"


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    @pytest.fixture(autouse=True)
    def _import(self):
        with patch("dotenv.load_dotenv"):
            import main as _main
            self.main = _main

    def _parse(self, argv: list[str]):
        with patch.object(sys, "argv", ["main.py"] + argv):
            return self.main.parse_args()

    def test_no_args_gives_defaults(self):
        args = self._parse([])
        assert args.platforms is None
        assert args.start is None
        assert args.end is None
        assert args.lookback is None
        assert args.schedule is False

    def test_platforms_single(self):
        args = self._parse(["--platforms", "google_ads"])
        assert args.platforms == ["google_ads"]

    def test_platforms_multiple(self):
        args = self._parse(["--platforms", "google_ads", "meta_ads"])
        assert args.platforms == ["google_ads", "meta_ads"]

    def test_start_and_end_parsed_as_dates(self):
        args = self._parse(["--start", "2024-01-01", "--end", "2024-01-31"])
        assert args.start == date(2024, 1, 1)
        assert args.end == date(2024, 1, 31)

    def test_lookback_parsed_as_int(self):
        args = self._parse(["--lookback", "14"])
        assert args.lookback == 14

    def test_schedule_flag(self):
        args = self._parse(["--schedule"])
        assert args.schedule is True

    def test_invalid_platform_raises(self):
        with pytest.raises(SystemExit):
            self._parse(["--platforms", "not_a_real_platform"])

    def test_invalid_date_raises(self):
        with pytest.raises(SystemExit):
            self._parse(["--start", "not-a-date"])


# ---------------------------------------------------------------------------
# run_scheduled cron parsing
# ---------------------------------------------------------------------------

class TestRunScheduled:
    @pytest.fixture(autouse=True)
    def _import(self):
        with patch("dotenv.load_dotenv"):
            import main as _main
            self.main = _main

    def _make_args(self):
        args = argparse.Namespace()
        args.platforms = None
        args.start = None
        args.end = None
        args.lookback = None
        args.schedule = False
        return args

    @staticmethod
    def _make_config_dict() -> dict:
        return {
            "bigquery": {"project_id": "p", "dataset_id": "d"},
            "pipeline": {"lookback_days": 30},
        }

    def test_cron_parsed_correctly_0_4(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_SCHEDULE_CRON", "0 4 * * *")

        mock_schedule = MagicMock()
        mock_schedule.every.return_value.day.at.return_value.do = MagicMock()

        with patch("main.schedule", mock_schedule):
            with patch("main.run_once"):
                with patch("main.time") as mock_time:
                    mock_time.sleep.side_effect = KeyboardInterrupt
                    try:
                        self.main.run_scheduled(self._make_config_dict(), self._make_args())
                    except KeyboardInterrupt:
                        pass

        mock_schedule.every.return_value.day.at.assert_called_with("04:00")

    def test_cron_parsed_correctly_30_14(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_SCHEDULE_CRON", "30 14 * * *")

        mock_schedule = MagicMock()
        mock_schedule.every.return_value.day.at.return_value.do = MagicMock()

        with patch("main.schedule", mock_schedule):
            with patch("main.run_once"):
                with patch("main.time") as mock_time:
                    mock_time.sleep.side_effect = KeyboardInterrupt
                    try:
                        self.main.run_scheduled(self._make_config_dict(), self._make_args())
                    except KeyboardInterrupt:
                        pass

        mock_schedule.every.return_value.day.at.assert_called_with("14:30")

    def test_default_cron_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("PIPELINE_SCHEDULE_CRON", raising=False)

        mock_schedule = MagicMock()
        mock_schedule.every.return_value.day.at.return_value.do = MagicMock()

        with patch("main.schedule", mock_schedule):
            with patch("main.run_once"):
                with patch("main.time") as mock_time:
                    mock_time.sleep.side_effect = KeyboardInterrupt
                    try:
                        self.main.run_scheduled(self._make_config_dict(), self._make_args())
                    except KeyboardInterrupt:
                        pass

        mock_schedule.every.return_value.day.at.assert_called_with("04:00")

    def test_run_once_called_on_startup(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_SCHEDULE_CRON", "0 4 * * *")

        mock_schedule = MagicMock()
        mock_schedule.every.return_value.day.at.return_value.do = MagicMock()

        with patch("main.schedule", mock_schedule):
            with patch("main.run_once") as mock_run_once:
                with patch("main.time") as mock_time:
                    mock_time.sleep.side_effect = KeyboardInterrupt
                    try:
                        self.main.run_scheduled(self._make_config_dict(), self._make_args())
                    except KeyboardInterrupt:
                        pass

        mock_run_once.assert_called_once()
