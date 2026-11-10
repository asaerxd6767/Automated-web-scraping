from __future__ import annotations

import re

import pytest
from scrapy.http import HtmlResponse, Request

from webtext.spiders.hn_frontpage import HnFrontpageSpider


def make_response(html: str) -> HtmlResponse:
    url = "https://news.ycombinator.com/news"
    return HtmlResponse(
        url=url,
        body=html.encode("utf-8"),
        encoding="utf-8",
        request=Request(url=url),
    )


def test_spider_harvests_raw_rows(fixture_html: str) -> None:
    spider = HnFrontpageSpider(pages=1, run_id="fixture")
    items = list(spider.parse(make_response(fixture_html)))

    assert len(items) >= 20
    first = items[0]
    assert first["source"] == "news.ycombinator.com"
    assert first["source_url"] == "https://news.ycombinator.com/news"
    assert re.fullmatch(r"\d+", first["item_id"])
    assert first["url"].startswith("http")
    assert first["title_raw"]
    assert "points" in first["raw_text"] or "job" in first["raw_text"]
    assert "\n" in first["raw_text"]
    assert first["harvested_at"].endswith("+00:00")


def test_spider_normalises_posted_at_to_utc(fixture_html: str) -> None:
    spider = HnFrontpageSpider(pages=1, run_id="fixture")
    items = list(spider.parse(make_response(fixture_html)))

    assert items[0]["posted_at"].endswith("Z")


def test_start_requests_respects_page_count() -> None:
    spider = HnFrontpageSpider(pages=3, run_id="fixture")
    requests = list(spider.start_requests())

    assert [request.url for request in requests] == [
        "https://news.ycombinator.com/news",
        "https://news.ycombinator.com/news?p=2",
        "https://news.ycombinator.com/news?p=3",
    ]


def test_spider_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        HnFrontpageSpider(pages=0)
    with pytest.raises(ValueError):
        HnFrontpageSpider(pages="nope")
    with pytest.raises(ValueError):
        HnFrontpageSpider(pages=1, run_id="../escape")
