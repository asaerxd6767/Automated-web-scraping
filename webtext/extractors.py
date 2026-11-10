"""Regex-based extraction of structured fields from raw listing text.

The spider deliberately stores each submission as a raw text blob.  This module
is the "text filtering" layer: it turns that blob into typed fields without
relying on the site's nested HTML.  Keeping it independent of Scrapy makes the
parsing rules easy to unit-test and reuse for other listing formats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .textnorm import clean_text

# Hacker News renders "<span class=rank>27.</span>Title" without a space, so
# the separator after the dot is optional.
_RANK_RE = re.compile(r"^\s*(?P<rank>\d{1,4})\.\s*")
_DOMAIN_TAIL_RE = re.compile(
    r"^(?P<title>.*?)\s*\((?P<domain>[^()]+)\)$",
    re.DOTALL,
)
_VALID_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}",
)
_AUTHOR_RE = re.compile(r"\bby\s+(?P<author>[A-Za-z0-9][A-Za-z0-9_.-]*)")
_POINTS_RE = re.compile(r"\b(?P<points>\d[\d,]*)\s+points?\b", re.IGNORECASE)
_COMMENTS_RE = re.compile(r"\b(?P<comments>\d[\d,]*)\s+comments?\b", re.IGNORECASE)
_DISCUSS_RE = re.compile(r"\bdiscuss\b", re.IGNORECASE)
_AGE_RE = re.compile(
    r"\b(?P<value>\d+)\s+(?P<unit>minute|hour|day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)

_UNIT_TO_HOURS = {
    "minute": 1 / 60,
    "hour": 1.0,
    "day": 24.0,
    "week": 7 * 24.0,
    "month": 30.4375 * 24.0,
    "year": 365.25 * 24.0,
}


@dataclass(frozen=True, slots=True)
class ParsedListing:
    """Typed values recovered from one raw listing."""

    rank: int | None
    title: str
    domain: str | None
    author: str | None
    points: int | None
    comments: int | None
    age_text: str | None
    age_hours: float | None
    warnings: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return not self.warnings


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _split_headline(headline: str) -> tuple[str, str | None]:
    """Separate a headline from its optional trailing ``(domain.tld)``."""

    text = clean_text(headline)
    rank_match = _RANK_RE.match(text)
    if rank_match:
        text = text[rank_match.end() :].strip()

    domain_match = _DOMAIN_TAIL_RE.match(text)
    if not domain_match:
        return text, None

    # Hacker News sometimes shows "github.com/user/repo" in the site bit.
    # Keep the host (the useful core parameter) and discard the path.
    candidate = domain_match.group("domain").strip().lower().split("/", 1)[0]
    if not _VALID_DOMAIN_RE.fullmatch(candidate):
        return text, None

    return domain_match.group("title").strip(), candidate


def _parse_age(details: str) -> tuple[str | None, float | None]:
    match = _AGE_RE.search(details)
    if not match:
        return None, None

    age_text = clean_text(match.group(0))
    value = int(match.group("value"))
    unit = match.group("unit").lower()
    return age_text, round(value * _UNIT_TO_HOURS[unit], 2)


def parse_listing(raw_text: str) -> ParsedListing:
    """Parse one raw Hacker News-style submission block.

    Expected (not required) shape::

        1. Blender 5.3 released (blender.org)
        26 points by amlib 18 minutes ago | hide | 3 comments
    """

    cleaned = clean_text(raw_text, multiline=True)
    lines = [line for line in cleaned.splitlines() if line.strip()]

    if not lines:
        return ParsedListing(
            rank=None,
            title="",
            domain=None,
            author=None,
            points=None,
            comments=None,
            age_text=None,
            age_hours=None,
            warnings=(
                "rank_missing",
                "title_missing",
                "domain_missing",
                "author_missing",
                "points_missing",
                "comments_missing",
                "age_missing",
            ),
        )

    headline = lines[0]
    details = " ".join(lines[1:])

    rank_match = _RANK_RE.match(headline)
    rank = int(rank_match.group("rank")) if rank_match else None

    title, domain = _split_headline(headline)

    author_match = _AUTHOR_RE.search(details)
    author = author_match.group("author") if author_match else None

    points_match = _POINTS_RE.search(details)
    points = _to_int(points_match.group("points")) if points_match else None

    comments_match = _COMMENTS_RE.search(details)
    if comments_match:
        comments = _to_int(comments_match.group("comments"))
    elif _DISCUSS_RE.search(details):
        comments = 0
    else:
        comments = None

    age_text, age_hours = _parse_age(details)

    warnings: list[str] = []
    if rank is None:
        warnings.append("rank_missing")
    if not title:
        warnings.append("title_missing")
    if domain is None:
        warnings.append("domain_missing")
    if author is None:
        warnings.append("author_missing")
    if points is None:
        warnings.append("points_missing")
    if comments is None:
        warnings.append("comments_missing")
    if age_hours is None:
        warnings.append("age_missing")

    return ParsedListing(
        rank=rank,
        title=title,
        domain=domain,
        author=author,
        points=points,
        comments=comments,
        age_text=age_text,
        age_hours=age_hours,
        warnings=tuple(warnings),
    )


def normalise_timestamp(value: object) -> str | None:
    """Convert an ISO-8601 page timestamp to a UTC ``...Z`` string.

    Unknown formats are returned cleaned rather than discarded, so the output
    stays honest about what the source supplied.
    """

    text = clean_text(value)
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
