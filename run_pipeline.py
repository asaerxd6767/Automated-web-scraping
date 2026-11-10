#!/usr/bin/env python3
"""Run the Hacker News harvesting pipeline end to end.

Usage:
    python run_pipeline.py
    python run_pipeline.py --pages 2 --min-points 50 --output data/output/hn.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "webtext.settings")

from scrapy.crawler import CrawlerProcess  # noqa: E402
from scrapy.utils.project import get_project_settings  # noqa: E402

from webtext.pipelines import CSV_COLUMNS  # noqa: E402
from webtext.spiders.hn_frontpage import HnFrontpageSpider  # noqa: E402


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Harvest raw Hacker News listings, extract fields, and export CSV."
    )
    parser.add_argument(
        "--pages",
        type=_positive_int,
        default=2,
        help="number of front-page pages to crawl (default: 2)",
    )
    parser.add_argument(
        "--min-points",
        type=_non_negative_int,
        default=0,
        help="drop listings scoring below this threshold (default: 0)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "output" / "hackernews_listings.csv",
        help="destination CSV path",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
        help="directory for timestamped raw JSONL archives",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=PROJECT_ROOT / "logs",
        help="directory for Scrapy run logs",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="run identifier (default: UTC timestamp)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="console/log file verbosity (default: INFO)",
    )
    return parser


def _validate_output_path(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.suffix.lower() != ".csv":
        raise SystemExit(f"error: --output must end with .csv, got {path}")
    return path


def _verify_csv(path: Path, expected_rows: int) -> list[str]:
    """Read the written CSV back and report structural problems."""

    problems: list[str] = []
    if not path.exists():
        return [f"CSV was not written: {path}"]

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            problems.append(
                f"unexpected CSV header: {reader.fieldnames!r} (expected {list(CSV_COLUMNS)!r})"
            )
        actual_rows = sum(1 for _ in reader)

    if actual_rows != expected_rows:
        problems.append(f"row count mismatch: CSV has {actual_rows}, summary says {expected_rows}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.run_id is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_id):
        raise SystemExit("error: --run-id may only contain letters, digits, '_', '.' and '-'")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = _validate_output_path(args.output)
    summary_path = output_path.with_suffix(".summary.json")
    raw_dir = args.raw_dir.expanduser().resolve()
    log_dir = args.log_dir.expanduser().resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    settings = get_project_settings()
    overrides = {
        "OUTPUT_CSV": str(output_path),
        "OUTPUT_SUMMARY": str(summary_path),
        "RAW_ARCHIVE_DIR": str(raw_dir),
        "MIN_POINTS": args.min_points,
        "LOG_LEVEL": args.log_level,
        "LOG_FILE": str(log_dir / f"crawl_{run_id}.log"),
    }
    for key, value in overrides.items():
        settings.set(key, value, priority="cmdline")

    print(f"Run ID       : {run_id}")
    print(f"Source       : https://news.ycombinator.com/")
    print(f"Pages        : {args.pages} (robots.txt crawl-delay: 30s)")
    print(f"Minimum score: {args.min_points}")
    print(f"Output       : {output_path}")

    started = time.monotonic()
    process = CrawlerProcess(settings)
    process.crawl(HnFrontpageSpider, pages=args.pages, run_id=run_id)
    process.start()

    elapsed = time.monotonic() - started
    if not summary_path.exists():
        print(f"error: run summary missing: {summary_path}", file=sys.stderr)
        return 2

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = int(summary.get("rows_written", 0))
    stats = summary.get("stats", {})

    problems = _verify_csv(output_path, rows)
    print()
    print(f"Finished in {elapsed:.1f}s")
    print(f"Rows written : {rows}")
    print(
        "Dropped      : "
        f"{stats.get('normalise/dropped_empty', 0)} empty, "
        f"{stats.get('validate/dropped_missing_fields', 0)} missing fields, "
        f"{stats.get('validate/dropped_invalid_url', 0)} invalid URLs, "
        f"{stats.get('dedupe/dropped', 0)} duplicates, "
        f"{stats.get('validate/dropped_min_points', 0)} below min points"
    )
    print(f"Warnings     : {summary.get('warnings_total', 0)} parse warnings")
    print(f"CSV          : {output_path}")
    print(f"Raw archive  : {summary.get('raw_archive')}")
    print(f"Summary      : {summary_path}")

    if problems:
        print("\nIntegrity check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    if rows == 0:
        print("\nNo records were written; the source markup or access policy may have changed.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
