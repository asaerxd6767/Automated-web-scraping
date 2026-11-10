"""Item pipelines: archive raw text, clean it, extract fields, validate, export."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from scrapy.exceptions import DropItem

from .extractors import normalise_timestamp, parse_listing
from .textnorm import clean_text

CSV_COLUMNS = (
    "rank",
    "item_id",
    "title",
    "url",
    "domain",
    "author",
    "points",
    "comments",
    "age_text",
    "age_hours",
    "posted_at",
    "scraped_at",
    "source",
    "source_url",
    "parse_warnings",
)

_REQUIRED_FIELDS = ("item_id", "title", "url")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(part) for part in value)
    return value


class _CrawlerAwarePipeline:
    """Support both the legacy and Scrapy 2.20+ pipeline hook signatures."""

    crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls()
        instance.crawler = crawler
        return instance

    def get_spider(self, spider=None):
        if spider is not None:
            return spider
        crawler = getattr(self, "crawler", None)
        if crawler is None or getattr(crawler, "spider", None) is None:
            raise RuntimeError("pipeline used without an active spider/crawler")
        return crawler.spider


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class RawArchivePipeline(_CrawlerAwarePipeline):
    """Persist each harvested raw listing to JSONL before any cleaning.

    This is the provenance layer: the CSV is a cleaned derivative, while the
    archive can be replayed through a revised extractor without re-crawling.
    """

    def __init__(self) -> None:
        self._handle = None
        self.path: Path | None = None

    def open_spider(self, spider=None) -> None:
        spider = self.get_spider(spider)
        settings = spider.crawler.settings
        raw_dir = Path(settings.get("RAW_ARCHIVE_DIR", "data/raw")).expanduser()
        raw_dir.mkdir(parents=True, exist_ok=True)
        self.path = raw_dir / f"{spider.name}_{spider.run_id}.jsonl"
        self._handle = self.path.open("w", encoding="utf-8", newline="\n", buffering=1)
        spider.crawler.stats.set_value("archive/path", str(self.path))

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        if self._handle is None:
            return item

        record = {
            "source": item.get("source"),
            "source_url": item.get("source_url"),
            "item_id": item.get("item_id"),
            "title_raw": item.get("title_raw"),
            "url": item.get("url"),
            "posted_at": item.get("posted_at"),
            "harvested_at": item.get("harvested_at"),
            "raw_text": item.get("raw_text"),
        }
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        spider.crawler.stats.inc_value("archive/records")
        return item

    def close_spider(self, spider=None) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


class NormalisePipeline(_CrawlerAwarePipeline):
    """Collapse whitespace artefacts in raw text before field extraction."""

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        raw_text = clean_text(item.get("raw_text"), multiline=True)
        if not raw_text:
            spider.crawler.stats.inc_value("normalise/dropped_empty")
            raise DropItem(f"empty raw text for item {item.get('item_id')!r}")

        item["raw_text"] = raw_text
        item["title_raw"] = clean_text(item.get("title_raw"))
        item["url"] = clean_text(item.get("url"))
        spider.crawler.stats.inc_value("normalise/records")
        return item


class ExtractionPipeline(_CrawlerAwarePipeline):
    """Apply the regex/text-filtering layer to the normalised listing."""

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        parsed = parse_listing(item.get("raw_text", ""))

        item["rank"] = parsed.rank
        item["title"] = parsed.title
        item["domain"] = parsed.domain
        item["author"] = parsed.author
        item["points"] = parsed.points
        item["comments"] = parsed.comments
        item["age_text"] = parsed.age_text
        item["age_hours"] = parsed.age_hours
        item["parse_warnings"] = list(parsed.warnings)

        stats = spider.crawler.stats
        stats.inc_value("extract/records")
        if parsed.warnings:
            stats.inc_value("extract/records_with_warnings")
            stats.inc_value("extract/warnings_total", len(parsed.warnings))
        return item


class ValidationPipeline(_CrawlerAwarePipeline):
    """Reject unusable records and enforce the optional minimum-score filter."""

    def __init__(self, min_points: int = 0) -> None:
        self.min_points = min_points

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(min_points=crawler.settings.getint("MIN_POINTS", 0))
        instance.crawler = crawler
        return instance

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        stats = spider.crawler.stats

        missing = [field for field in _REQUIRED_FIELDS if not item.get(field)]
        if missing:
            stats.inc_value("validate/dropped_missing_fields")
            raise DropItem(f"missing required fields {missing}: {item.get('url')}")

        parsed_url = urlparse(str(item["url"]))
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            stats.inc_value("validate/dropped_invalid_url")
            raise DropItem(f"invalid URL: {item.get('url')!r}")

        points = item.get("points") or 0
        if points < self.min_points:
            stats.inc_value("validate/dropped_min_points")
            raise DropItem(
                f"points {points} below minimum {self.min_points}: {item.get('url')}"
            )

        item["posted_at"] = normalise_timestamp(item.get("posted_at"))
        warnings = list(item.get("parse_warnings") or [])
        if not item.get("posted_at"):
            warnings.append("posted_at_missing")
            stats.inc_value("validate/warnings_total")
        item["parse_warnings"] = warnings
        item["scraped_at"] = item.get("harvested_at") or _utc_now_iso()

        stats.inc_value("validate/kept")
        return item


class DedupePipeline(_CrawlerAwarePipeline):
    """Drop records seen earlier in this run (e.g. when pages overlap)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def open_spider(self, spider=None) -> None:
        self._seen = set()

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        key = str(item.get("item_id") or item.get("url"))
        if key in self._seen:
            spider.crawler.stats.inc_value("dedupe/dropped")
            raise DropItem(f"duplicate listing: {key}")
        self._seen.add(key)
        return item


class CsvExportPipeline(_CrawlerAwarePipeline):
    """Buffer validated rows and atomically write a deterministic CSV + summary."""

    def __init__(self, output_path: Path, summary_path: Path) -> None:
        self.output_path = output_path
        self.summary_path = summary_path
        self._rows: list[dict] = []

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(
            output_path=Path(crawler.settings.get("OUTPUT_CSV")).expanduser(),
            summary_path=Path(crawler.settings.get("OUTPUT_SUMMARY")).expanduser(),
        )
        instance.crawler = crawler
        return instance

    def open_spider(self, spider=None) -> None:
        self._rows = []

    def process_item(self, item, spider=None):
        spider = self.get_spider(spider)
        self._rows.append({column: item.get(column) for column in CSV_COLUMNS})
        spider.crawler.stats.inc_value("output/buffered")
        return item

    def close_spider(self, spider=None) -> None:
        spider = self.get_spider(spider)
        rows = sorted(
            self._rows,
            key=lambda row: (
                row.get("rank") is None,
                row.get("rank") or 0,
                str(row.get("item_id") or ""),
            ),
        )

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _csv_value(row.get(column)) for column in CSV_COLUMNS})

        content = buffer.getvalue()
        _atomic_write(self.output_path, content)

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        stats = spider.crawler.stats
        stats.set_value("output/csv_path", str(self.output_path))
        stats.set_value("output/summary_path", str(self.summary_path))
        stats.set_value("output/rows_written", len(rows))
        stats.set_value("output/csv_sha256", digest)

        summary = {
            "run_id": getattr(spider, "run_id", None),
            "generated_at": _utc_now_iso(),
            "source": getattr(spider, "source_name", None),
            "pages_requested": getattr(spider, "pages", None),
            "min_points": spider.crawler.settings.getint("MIN_POINTS", 0),
            "rows_written": len(rows),
            "warnings_total": (
                stats.get_value("extract/warnings_total", 0)
                + stats.get_value("validate/warnings_total", 0)
            ),
            "csv_path": str(self.output_path),
            "csv_sha256": digest,
            "raw_archive": stats.get_value("archive/path"),
            "stats": stats.get_stats(),
        }
        _atomic_write(
            self.summary_path,
            json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        )
