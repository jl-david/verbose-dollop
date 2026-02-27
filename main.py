#!/usr/bin/env python3
"""
main.py – Looker Studio Marketing Integration Pipeline
=======================================================
Entry point for running the data pipeline manually or on a schedule.

Usage
-----
  # Run all platforms, last 30 days (default)
  python main.py

  # Run specific platforms only
  python main.py --platforms google_ads meta_ads

  # Custom date range
  python main.py --start 2024-01-01 --end 2024-01-31

  # Schedule mode (runs daily at the configured cron time)
  python main.py --schedule
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import schedule
import structlog
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "config" / ".env", override=False)

from pipeline.aggregator import DataAggregator

logger = structlog.get_logger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent / "config" / "config.yaml"
    with open(config_path) as fh:
        raw = fh.read()

    # Simple env-var substitution for ${VAR} placeholders
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)

    return yaml.safe_load(raw)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Looker Studio Marketing Data Pipeline")
    p.add_argument(
        "--platforms",
        nargs="+",
        choices=DataAggregator.ALL_PLATFORMS,
        default=None,
        help="Platforms to fetch (default: all)",
    )
    p.add_argument("--start", type=date.fromisoformat, default=None, help="Start date YYYY-MM-DD")
    p.add_argument("--end",   type=date.fromisoformat, default=None, help="End date YYYY-MM-DD")
    p.add_argument(
        "--lookback",
        type=int,
        default=None,
        help="Number of look-back days when no explicit dates are given",
    )
    p.add_argument(
        "--schedule",
        action="store_true",
        help="Run in scheduled mode (uses PIPELINE_SCHEDULE_CRON env var)",
    )
    return p.parse_args()


def run_once(config: dict, args: argparse.Namespace) -> None:
    aggregator = DataAggregator(config, platforms=args.platforms)
    aggregator.run(
        start_date=args.start,
        end_date=args.end,
        lookback_days=args.lookback,
    )


def run_scheduled(config: dict, args: argparse.Namespace) -> None:
    cron = os.environ.get("PIPELINE_SCHEDULE_CRON", "0 4 * * *")
    # Parse simple cron: "minute hour * * *"
    parts = cron.split()
    if len(parts) >= 2:
        minute, hour = parts[0], parts[1]
        run_time = f"{int(hour):02d}:{int(minute):02d}"
    else:
        run_time = "04:00"

    logger.info("scheduled mode active", run_time=run_time)
    schedule.every().day.at(run_time).do(run_once, config=config, args=args)

    # Also run immediately on start
    run_once(config, args)

    while True:
        schedule.run_pending()
        time.sleep(60)


def main() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )

    args = parse_args()
    config = load_config()

    logger.info(
        "pipeline starting",
        platforms=args.platforms or DataAggregator.ALL_PLATFORMS,
        scheduled=args.schedule,
    )

    try:
        if args.schedule:
            run_scheduled(config, args)
        else:
            run_once(config, args)
    except KeyboardInterrupt:
        logger.info("pipeline stopped by user")
        sys.exit(0)
    except Exception as exc:
        logger.error("pipeline failed", error=str(exc), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
