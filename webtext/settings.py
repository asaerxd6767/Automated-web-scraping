"""Scrapy settings for the web-text harvesting project.

Politeness settings are deliberately conservative.  Hacker News publishes
``Crawl-delay: 30`` in robots.txt, so the crawler sends at most one request
every 30 seconds and never bypasses robots rules.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

BOT_NAME = "webtext"
SPIDER_MODULES = ["webtext.spiders"]
NEWSPIDER_MODULE = "webtext.spiders"

# Identification and crawl policy.
USER_AGENT = "webtext-pipeline/1.0 (educational data-collection demo)"
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 30.0  # honours news.ycombinator.com robots.txt Crawl-delay
DOWNLOAD_DELAY_JITTER = 0  # never undercut the robots.txt crawl delay
DOWNLOAD_TIMEOUT = 30
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

# Be a good citizen: no cookies, no unnecessary headers, no cache surprises.
COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False
HTTPCACHE_ENABLED = False
AJAXCRAWL_ENABLED = False

# Logging.
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_INSTALL_ROOT_HANDLER = True

# Extraction and output configuration (overridden by the CLI).
RAW_ARCHIVE_DIR = str(BASE_DIR / "data" / "raw")
OUTPUT_CSV = str(BASE_DIR / "data" / "output" / "hackernews_listings.csv")
OUTPUT_SUMMARY = str(BASE_DIR / "data" / "output" / "hackernews_listings.summary.json")
MIN_POINTS = 0

ITEM_PIPELINES = {
    "webtext.pipelines.RawArchivePipeline": 100,
    "webtext.pipelines.NormalisePipeline": 200,
    "webtext.pipelines.ExtractionPipeline": 300,
    "webtext.pipelines.ValidationPipeline": 400,
    "webtext.pipelines.DedupePipeline": 500,
    "webtext.pipelines.CsvExportPipeline": 600,
}

FEED_EXPORT_ENCODING = "utf-8"
