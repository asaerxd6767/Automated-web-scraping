# Hacker News Automated Text Extraction Pipeline

A small, production-minded Scrapy pipeline that harvests raw listing text from a
real public web source, filters structured parameters out of that text with
regular expressions, removes whitespace/Unicode artefacts, and writes a clean,
typed CSV.

The chosen source is the Hacker News front page
(`https://news.ycombinator.com/`). It is a genuine unstructured listing page:
titles, domains, authors, scores, comment counts, and relative timestamps all
arrive as prose inside the page, and several values need text-level parsing.

## Pipeline

```text
Hacker News listing rows
        │
        ▼
HnFrontpageSpider          harvest raw row text + provenance metadata
        │
        ▼
RawArchivePipeline         JSONL archive of untouched raw text (replayable)
        │
        ▼
NormalisePipeline          HTML entities, NBSP, zero-width chars, newlines
        │
        ▼
ExtractionPipeline         regex text filtering → typed fields
        │
        ▼
ValidationPipeline         required fields, URL sanity, optional min-score filter
        │
        ▼
DedupePipeline             drop repeated item IDs across pages
        │
        ▼
CsvExportPipeline          sorted CSV + run summary, written atomically
```

## Project layout

```text
.
├── run_pipeline.py              # CLI: settings, crawl, integrity check, exit code
├── scrapy.cfg                   # Scrapy project entry point
├── requirements.txt
├── pyproject.toml               # pytest configuration
├── webtext/
│   ├── items.py                 # RawListingItem field definitions
│   ├── settings.py              # polite crawl + output configuration
│   ├── textnorm.py              # whitespace/Unicode/entity cleaning
│   ├── extractors.py            # pure regex extraction logic
│   ├── pipelines.py             # archive → clean → extract → validate → CSV
│   └── spiders/
│       └── hn_frontpage.py      # raw-text harvester
├── tests/
│   ├── fixtures/hn_frontpage.html
│   ├── helpers.py
│   ├── test_textnorm.py
│   ├── test_extractors.py
│   ├── test_spider.py
│   └── test_pipelines.py
├── data/
│   ├── raw/                     # timestamped raw JSONL archives
│   └── output/                  # CSV + run summary
└── logs/                        # timestamped Scrapy logs
```

## Setup

Tested with Python 3.12 and Scrapy 2.20 on WSL/Ubuntu.

```bash
cd /home/zeke/Coding/python/data_science
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Windows PowerShell, use `.venv\Scripts\pip` and `.venv\Scripts\python`
instead. If your Python installation is externally managed, use a virtual
environment as shown above.

## Run

```bash
.venv/bin/python run_pipeline.py --pages 2
```

Example output from the verified live run:

```text
Run ID       : 20261110T164508Z
Source       : https://news.ycombinator.com/
Pages        : 2 (robots.txt crawl-delay: 30s)
Minimum score: 0
Output       : .../data/output/hackernews_listings.csv

Finished in 60.9s
Rows written : 60
Dropped      : 0 empty, 0 missing fields, 0 invalid URLs, 0 duplicates, 0 below min points
Warnings     : 3 parse warnings
CSV          : .../data/output/hackernews_listings.csv
Raw archive  : .../data/raw/hn_frontpage_20261110T164508Z.jsonl
Summary      : .../data/output/hackernews_listings.summary.json
```

The two pages contained 60 unique listings. 59 records parsed with no warnings;
the single remaining record is a paid YC job listing that genuinely has no
author, score, or comment count on the page.

### CLI options

| Option | Default | Purpose |
| --- | --- | --- |
| `--pages N` | `2` | Number of front-page pages to crawl. |
| `--min-points N` | `0` | Drop listings below this score (missing score counts as 0). |
| `--output PATH` | `data/output/hackernews_listings.csv` | Destination CSV. |
| `--raw-dir PATH` | `data/raw` | Directory for timestamped raw JSONL. |
| `--log-dir PATH` | `logs` | Directory for Scrapy logs. |
| `--run-id ID` | UTC timestamp | Stable identifier for the run/archive filenames. |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

Examples:

```bash
# Only high-signal posts
.venv/bin/python run_pipeline.py --pages 2 --min-points 100

# A single page, custom outputs
.venv/bin/python run_pipeline.py --pages 1 \
  --output data/output/hn_one_page.csv --run-id demo-001
```

### Output files

| File | Description |
| --- | --- |
| `data/output/hackernews_listings.csv` | Final cleaned dataset (overwritten each run). |
| `data/output/hackernews_listings.summary.json` | Run counters, paths, SHA-256 of the CSV, and Scrapy stats. |
| `data/raw/hn_frontpage_<run-id>.jsonl` | Untouched raw rows captured before cleaning. |
| `logs/crawl_<run-id>.log` | Full Scrapy log with request/response statistics. |

## CSV schema

| Column | Type | Notes |
| --- | --- | --- |
| `rank` | integer | Front-page rank, 1–60 across two pages. |
| `item_id` | string | Hacker News item ID; used for deduplication. |
| `title` | string | Cleaned title, with the trailing site/domain removed. |
| `url` | string | Absolute destination URL. |
| `domain` | string | Host parsed from the listing's site bit, e.g. `github.com`; blank for text posts. |
| `author` | string | Submitter username; blank for job listings. |
| `points` | integer | Score; blank when the source shows no score. |
| `comments` | integer | Comment count; `discuss` becomes `0`. |
| `age_text` | string | Source-relative age, e.g. `2 hours ago`. |
| `age_hours` | float | Derived from `age_text`, rounded to 2 decimals. |
| `posted_at` | ISO-8601 UTC | Taken from the page's canonical timestamp attribute. |
| `scraped_at` | ISO-8601 UTC | Harvest time for this record. |
| `source` | string | `news.ycombinator.com`. |
| `source_url` | string | Listing page URL (useful for pagination provenance). |
| `parse_warnings` | string | Semicolon-separated warnings, empty when all fields were found. |

Example row (line-wrapped for readability):

```csv
rank,item_id,title,url,domain,author,points,comments,age_text,age_hours,posted_at,scraped_at,source,source_url,parse_warnings
1,50442426,Blender 5.3 released with Gaussian Splat support,https://www.blender.org/download/releases/5-3/,blender.org,amlib,65,8,29 minutes ago,0.48,2026-11-10T16:15:43Z,2026-11-10T16:45:41+00:00,news.ycombinator.com,https://news.ycombinator.com/news,
```

## Text filtering logic

The extractor is deliberately independent of Scrapy and unit-testable. Given
this raw text:

```text
16..NET 11 (devblogs.microsoft.com/dotnet)
39 points by runesoerensen 2 hours ago | hide | 10 comments
```

it produces:

```text
rank=16, title=".NET 11", domain="devblogs.microsoft.com",
author="runesoerensen", points=39, comments=10,
age_text="2 hours ago", age_hours=2.0
```

Notable rules:

- **Rank prefix** — HN renders the rank and title adjacent
  (`27.Building...`), so the dot separator is optional.
- **Domain** — the trailing parenthetical is kept only when it contains a valid
  host. Paths are stripped: `github.com/user/repo` → `github.com`. Titles such
  as `(v2)`, `(2024)`, or `(see the docs)` remain part of the title.
- **Scores and comments** — thousands separators are accepted; singular forms
  (`1 point`, `1 comment`) work; `discuss` maps to zero comments.
- **Relative age** — minutes, hours, days, weeks, months, and years are
  converted to `age_hours`.
- **Whitespace artefacts** — HTML entities, NBSP, zero-width characters,
  control chars, Windows line endings, and indentation runs are normalised
  before regex matching and again at export.
- **Missing values** — a missing optional field is left blank and recorded in
  `parse_warnings` rather than being silently invented.

Required for export: `item_id`, `title`, and a valid `http(s)` URL. Records that
fail these checks, duplicate an existing `item_id`, or fall below
`--min-points` are dropped and counted in the summary.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Result from the final verification:

```text
41 passed
```

The suite covers:

- whitespace/Unicode/entity cleanup and truncation;
- rank, domain-path, title-parenthetical, singular/plural, `discuss`, Unicode,
  missing-field, and timestamp extraction cases;
- spider harvesting against a saved real HTML fixture (offline);
- pagination request construction and configuration validation;
- raw-archive round-tripping, deduplication, validation drops, deterministic
  CSV sorting/quoting, warning joining, summary generation, and a full
  fixture-to-CSV integration run.

The live crawl is intentionally not part of the test suite, so tests stay fast
and deterministic.

## Design notes and limitations

- **Politeness.** `ROBOTSTXT_OBEY=True`, one concurrent request, and a 30-second
  download delay honour Hacker News' `Crawl-delay: 30` directive. A two-page run
  therefore takes about a minute. Do not lower the delay for this source.
- **Provenance before cleaning.** The JSONL archive is written before
  normalisation. A revised extractor can be replayed over it without hitting
  the site again.
- **Atomic outputs.** CSV and summary are written to temporary files and
  `os.replace`-d into place, so a crash cannot leave a half-written dataset.
- **Deterministic order.** Rows are sorted by rank and then item ID before
  export; repeated runs are directly comparable.
- **Extensibility.** Add another spider and a matching pure parser function in
  `extractors.py`; the archive/validation/dedupe/export layers stay unchanged.
- **Limitations.** HTML or text-format changes on the source require parser
  updates; relative timestamps are only as precise as the rendered page; paid
  job listings legitimately lack score/comment metadata; the pipeline does not
  execute JavaScript or bypass access controls; it is designed for a small
  number of pages, not bulk mirroring.

## Troubleshooting

- **Exit code 1 / zero rows** — inspect `logs/crawl_<run-id>.log`. The CLI
  returns 1 when the crawl completes but writes no records (markup change,
  block, or robots policy change).
- **Exit code 2** — CSV/summary integrity check failed, or the summary was not
  produced. The CSV header and row count are verified against the summary.
- **Encoding** — output is UTF-8 without a BOM. Import it as UTF-8 in Excel,
  pandas, or a database client.
- **Different working directory** — defaults are resolved relative to the
  project root; pass `--output`/`--raw-dir` explicitly if needed.
