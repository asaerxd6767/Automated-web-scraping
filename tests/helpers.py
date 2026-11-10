"""Shared test helpers."""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from scrapy.settings import Settings


class StubStats:
    """Minimal replacement for Scrapy's stats collector."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.values[key] = int(self.values.get(key, start)) + count

    def set_value(self, key: str, value: object) -> None:
        self.values[key] = value

    def get_value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def get_stats(self) -> dict[str, object]:
        return dict(self.values)


class StubSpider:
    name = "hn_frontpage"
    source_name = "news.ycombinator.com"
    pages = 1
    run_id = "testrun"

    def __init__(self, **settings) -> None:
        self.crawler = SimpleNamespace(
            settings=Settings(settings),
            stats=StubStats(),
        )


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
