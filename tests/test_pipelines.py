from __future__ import annotations

import json
from pathlib import Path

import pytest
from scrapy.exceptions import DropItem

from webtext.items import RawListingItem
from webtext.pipelines import (
    CSV_COLUMNS,
    CsvExportPipeline,
    DedupePipeline,
    ExtractionPipeline,
    NormalisePipeline,
    RawArchivePipeline,
    ValidationPipeline,
)

from .helpers import StubSpider, read_csv_rows


def make_item(
    raw_text: str = "1. Example title (example.com)\n"
    "25 points by alice 2 hours ago | hide | 4 comments",
    **overrides,
) -> RawListingItem:
    values = {
        "source": "news.ycombinator.com",
        "source_url": "https://news.ycombinator.com/news",
        "item_id": "123",
        "title_raw": "Example title",
        "url": "https://example.com/article",
        "posted_at": "2026-11-10T14:00:00Z",
        "harvested_at": "2026-11-10T16:00:00+00:00",
        "raw_text": raw_text,
    }
    values.update(overrides)
    return RawListingItem(**values)


def prepare_item(raw_text: str | None = None, **overrides) -> RawListingItem:
    """Build an item through extraction, then apply test-specific overrides."""

    item = make_item(raw_text) if raw_text is not None else make_item()
    item = ExtractionPipeline().process_item(item, StubSpider())
    for key, value in overrides.items():
        item[key] = value
    return item


def test_normalise_cleans_whitespace_and_passes_metadata() -> None:
    spider = StubSpider()
    pipeline = NormalisePipeline()
    item = make_item(
        raw_text="  1. A\xa0title  (example.com)\n\n  25 points by alice 2 hours ago  ",
        title_raw="  A\xa0title  ",
    )

    result = pipeline.process_item(item, spider)

    assert result["raw_text"] == "1. A title (example.com)\n25 points by alice 2 hours ago"
    assert result["title_raw"] == "A title"
    assert spider.crawler.stats.get_value("normalise/records") == 1


def test_normalise_drops_empty_raw_text() -> None:
    spider = StubSpider()
    with pytest.raises(DropItem):
        NormalisePipeline().process_item(make_item(raw_text=" \n\t"), spider)
    assert spider.crawler.stats.get_value("normalise/dropped_empty") == 1


def test_extraction_sets_typed_fields_and_warnings() -> None:
    spider = StubSpider()
    item = NormalisePipeline().process_item(make_item(), spider)
    item = ExtractionPipeline().process_item(item, spider)

    assert item["rank"] == 1
    assert item["title"] == "Example title"
    assert item["domain"] == "example.com"
    assert item["author"] == "alice"
    assert item["points"] == 25
    assert item["comments"] == 4
    assert item["age_hours"] == 2.0
    assert item["parse_warnings"] == []
    assert spider.crawler.stats.get_value("extract/records") == 1


def test_validation_rejects_missing_fields() -> None:
    spider = StubSpider()
    with pytest.raises(DropItem, match="missing required fields"):
        ValidationPipeline(min_points=0).process_item(make_item(title=""), spider)
    assert spider.crawler.stats.get_value("validate/dropped_missing_fields") == 1


def test_validation_rejects_bad_url() -> None:
    spider = StubSpider()
    with pytest.raises(DropItem, match="invalid URL"):
        ValidationPipeline(min_points=0).process_item(
            prepare_item(url="javascript:alert(1)"), spider
        )
    assert spider.crawler.stats.get_value("validate/dropped_invalid_url") == 1


def test_validation_applies_minimum_points_filter() -> None:
    spider = StubSpider()
    item = prepare_item(points=5)
    with pytest.raises(DropItem, match="below minimum"):
        ValidationPipeline(min_points=10).process_item(item, spider)
    assert spider.crawler.stats.get_value("validate/dropped_min_points") == 1


def test_validation_normalises_timestamp_and_sets_scraped_at() -> None:
    spider = StubSpider()
    item = prepare_item(posted_at="2026-11-10T15:00:00+01:00")
    result = ValidationPipeline(min_points=0).process_item(item, spider)

    assert result["posted_at"] == "2026-11-10T14:00:00Z"
    assert result["scraped_at"] == "2026-11-10T16:00:00+00:00"
    assert "posted_at_missing" not in result["parse_warnings"]


def test_dedupe_drops_second_occurrence() -> None:
    spider = StubSpider()
    pipeline = DedupePipeline()
    pipeline.open_spider(spider)
    first = make_item()
    second = make_item()

    assert pipeline.process_item(first, spider) is first
    with pytest.raises(DropItem, match="duplicate"):
        pipeline.process_item(second, spider)
    assert spider.crawler.stats.get_value("dedupe/dropped") == 1


def test_raw_archive_preserves_original_text(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    spider = StubSpider(RAW_ARCHIVE_DIR=str(raw_dir))
    pipeline = RawArchivePipeline()
    pipeline.open_spider(spider)

    raw_text = "  1. Raw\xa0text  \n  25 points by alice  "
    pipeline.process_item(make_item(raw_text=raw_text), spider)
    pipeline.close_spider(spider)

    path = raw_dir / "hn_frontpage_testrun.jsonl"
    assert path.exists()
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["raw_text"] == raw_text
    assert record["item_id"] == "123"
    assert spider.crawler.stats.get_value("archive/records") == 1


def test_csv_export_writes_deterministic_sorted_output(tmp_path: Path) -> None:
    output = tmp_path / "listings.csv"
    summary = tmp_path / "listings.summary.json"
    spider = StubSpider(MIN_POINTS=0)
    pipeline = CsvExportPipeline(output, summary)
    pipeline.open_spider(spider)

    first = make_item(item_id="2", title='A "quoted", title', rank=2, points=10)
    second = make_item(item_id="1", title="Caf\u00e9 \u2014 unicode", rank=1, points=None)
    third = make_item(item_id="3", title="Unranked", rank=None, points=3)
    for item in (first, second, third):
        pipeline.process_item(item, spider)
    pipeline.close_spider(spider)

    rows = read_csv_rows(output)
    assert [row["item_id"] for row in rows] == ["1", "2", "3"]
    assert rows[0]["title"] == "Caf\u00e9 \u2014 unicode"
    assert rows[1]["title"] == 'A "quoted", title'
    assert rows[1]["points"] == "10"
    assert rows[0]["points"] == ""
    assert list(rows[0].keys()) == list(CSV_COLUMNS)
    assert not list(tmp_path.glob(".*.tmp"))

    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["rows_written"] == 3
    assert payload["csv_path"] == str(output)
    assert payload["min_points"] == 0
    assert len(payload["csv_sha256"]) == 64


def test_csv_export_joins_warning_lists(tmp_path: Path) -> None:
    output = tmp_path / "listings.csv"
    summary = tmp_path / "listings.summary.json"
    spider = StubSpider()
    pipeline = CsvExportPipeline(output, summary)
    pipeline.open_spider(spider)

    item = make_item(parse_warnings=["domain_missing", "posted_at_missing"])
    pipeline.process_item(item, spider)
    pipeline.close_spider(spider)

    rows = read_csv_rows(output)
    assert rows[0]["parse_warnings"] == "domain_missing; posted_at_missing"


def test_full_pipeline_from_fixture_writes_csv(fixture_html: str, output_paths) -> None:
    output, summary, raw_dir = output_paths
    settings = {
        "RAW_ARCHIVE_DIR": str(raw_dir),
        "OUTPUT_CSV": str(output),
        "OUTPUT_SUMMARY": str(summary),
        "MIN_POINTS": 0,
    }
    spider = StubSpider(**settings)

    from scrapy.http import HtmlResponse, Request

    from webtext.spiders.hn_frontpage import HnFrontpageSpider

    url = "https://news.ycombinator.com/news"
    response = HtmlResponse(
        url=url,
        body=fixture_html.encode("utf-8"),
        encoding="utf-8",
        request=Request(url=url),
    )
    harvested = list(HnFrontpageSpider(pages=1, run_id="testrun").parse(response))
    assert harvested

    archive = RawArchivePipeline()
    archive.open_spider(spider)
    dedupe = DedupePipeline()
    dedupe.open_spider(spider)
    export = CsvExportPipeline(output, summary)
    export.open_spider(spider)

    chain = [
        NormalisePipeline(),
        ExtractionPipeline(),
        ValidationPipeline(min_points=0),
        dedupe,
        export,
    ]

    for item in harvested:
        archive.process_item(item, spider)
        for pipeline in chain:
            item = pipeline.process_item(item, spider)

    archive.close_spider(spider)
    export.close_spider(spider)

    rows = read_csv_rows(output)
    assert len(rows) == len(harvested)
    assert len({row["item_id"] for row in rows}) == len(rows)
    assert all(row["title"] for row in rows)
    assert all(row["url"].startswith("https://") for row in rows)
    assert all(row["item_id"] for row in rows)
    assert all(row["rank"].isdigit() for row in rows)
    assert [int(row["rank"]) for row in rows] == list(range(1, len(rows) + 1))
    assert all(row["posted_at"].endswith("Z") for row in rows if row["posted_at"])

    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["rows_written"] == len(rows)
    assert (raw_dir / "hn_frontpage_testrun.jsonl").exists()
    assert payload["raw_archive"].endswith(".jsonl")
