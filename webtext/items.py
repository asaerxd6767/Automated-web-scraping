"""Scrapy item definitions for a harvested listing."""

import scrapy


class RawListingItem(scrapy.Item):
    """A single listing, first as raw text and later as cleaned fields."""

    # Harvest metadata (set by the spider).
    source = scrapy.Field()
    source_url = scrapy.Field()
    item_id = scrapy.Field()
    title_raw = scrapy.Field()
    url = scrapy.Field()
    posted_at = scrapy.Field()
    harvested_at = scrapy.Field()
    raw_text = scrapy.Field()

    # Cleaned/extracted fields (set by pipelines).
    rank = scrapy.Field()
    title = scrapy.Field()
    domain = scrapy.Field()
    author = scrapy.Field()
    points = scrapy.Field()
    comments = scrapy.Field()
    age_text = scrapy.Field()
    age_hours = scrapy.Field()
    scraped_at = scrapy.Field()
    parse_warnings = scrapy.Field()
