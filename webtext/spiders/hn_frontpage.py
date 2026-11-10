"""Scrapy spider that harvests raw front-page listings from Hacker News."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import scrapy

from ..extractors import normalise_timestamp
from ..items import RawListingItem


class HnFrontpageSpider(scrapy.Spider):
    """Collect raw submission text from ``news.ycombinator.com``.

    The spider intentionally does *not* parse title/author/points itself.  It
    captures the text of each submission row and hands it to the normalisation
    and extraction pipelines.  That keeps the crawl layer replaceable and makes
    the text-filtering rules independently testable.
    """

    name = "hn_frontpage"
    allowed_domains = ["news.ycombinator.com"]
    base_url = "https://news.ycombinator.com/news"
    source_name = "news.ycombinator.com"

    def __init__(self, pages: int | str = 1, run_id: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.pages = int(pages)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"pages must be an integer, got {pages!r}") from exc
        if self.pages < 1:
            raise ValueError("pages must be >= 1")

        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.run_id):
            raise ValueError("run_id may only contain letters, digits, '_', '.' and '-'")

    async def start(self):
        """Scrapy >= 2.13 entry point (``start_requests`` below is legacy)."""

        for request in self.start_requests():
            yield request

    def start_requests(self):
        """Kept for Scrapy < 2.13 and for direct unit testing."""

        for page in range(1, self.pages + 1):
            url = self.base_url if page == 1 else f"{self.base_url}?p={page}"
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={"page": page},
                headers={"Accept-Language": "en"},
            )

    def parse(self, response):
        rows = response.css("tr.athing.submission")
        if not rows:
            # Accommodate older/alternate Hacker News markup.
            rows = response.css("tr.athing")

        if not rows:
            self.logger.warning("No submission rows found on %s", response.url)
            return

        harvested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        for row in rows:
            title_anchor = row.css("span.titleline > a")
            if not title_anchor:
                title_anchor = row.css("td.title > a")

            title_raw = title_anchor.xpath("string(.)").get() or ""
            href = title_anchor.attrib.get("href", "")

            subtext = row.xpath(
                "following-sibling::tr[td[contains(concat(' ', normalize-space(@class), ' '),"
                " ' subtext ')]]"
            )
            subtext_row = subtext[0] if len(subtext) else None
            subtext_text = (
                subtext_row.xpath("string(.)").get() if subtext_row is not None else ""
            ) or ""

            row_text = row.xpath("string(.)").get() or ""
            raw_text = "\n".join(part for part in (row_text, subtext_text) if part.strip())

            posted_at = None
            if subtext_row is not None:
                posted_at = subtext_row.css("span.age::attr(title)").get()

            yield RawListingItem(
                source=self.source_name,
                source_url=response.url,
                item_id=row.attrib.get("id", ""),
                title_raw=title_raw,
                url=response.urljoin(href),
                posted_at=normalise_timestamp(posted_at),
                harvested_at=harvested_at,
                raw_text=raw_text,
            )
