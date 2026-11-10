from __future__ import annotations

import pytest

from webtext.extractors import normalise_timestamp, parse_listing


def test_parse_typical_listing() -> None:
    parsed = parse_listing(
        "12. Show HN: A tiny tool (example.com)\n"
        "245 points by alice 3 hours ago | hide | 42 comments"
    )

    assert parsed.rank == 12
    assert parsed.title == "Show HN: A tiny tool"
    assert parsed.domain == "example.com"
    assert parsed.author == "alice"
    assert parsed.points == 245
    assert parsed.comments == 42
    assert parsed.age_text == "3 hours ago"
    assert parsed.age_hours == 3.0
    assert parsed.warnings == ()
    assert parsed.is_complete


def test_parse_handles_non_breaking_spaces_and_commas() -> None:
    parsed = parse_listing(
        "1. A big number (example.org)\n1,234 points by dev_user 18 minutes ago | hide | 1,001 comments"
    )

    assert parsed.points == 1234
    assert parsed.comments == 1001
    assert parsed.age_hours == 0.3


def test_parse_singular_comment_and_discuss() -> None:
    one = parse_listing(
        "2. One comment (example.com)\n9 points by bob 1 hour ago | hide | 1 comment"
    )
    assert one.comments == 1
    assert one.age_hours == 1.0

    none = parse_listing(
        "3. No comments yet (example.com)\n7 points by carol 2 days ago | hide | discuss"
    )
    assert none.comments == 0


def test_parse_title_with_parentheses_keeps_them() -> None:
    parsed = parse_listing(
        "4. Show HN: My tool (v2) (github.com)\n3 points by dan 1 day ago | hide | 3 comments"
    )
    assert parsed.title == "Show HN: My tool (v2)"
    assert parsed.domain == "github.com"


def test_parse_domain_with_path_keeps_host() -> None:
    parsed = parse_listing(
        "9. Show HN: My repo (github.com/example/project)\n"
        "12 points by dev 2 hours ago | hide | 5 comments"
    )
    assert parsed.title == "Show HN: My repo"
    assert parsed.domain == "github.com"


def test_parse_invalid_domain_parenthetical_stays_in_title() -> None:
    parsed = parse_listing(
        "10. Not a domain (see the docs)\n2 points by user 1 hour ago | hide | 1 comment"
    )
    assert parsed.title == "Not a domain (see the docs)"
    assert parsed.domain is None


def test_parse_ask_hn_without_domain() -> None:
    parsed = parse_listing(
        "5. Ask HN: How do you test parsers?\n10 points by eve 4 hours ago | hide | 6 comments"
    )
    assert parsed.title == "Ask HN: How do you test parsers?"
    assert parsed.domain is None
    assert "domain_missing" in parsed.warnings
    assert not parsed.is_complete


def test_parse_job_listing_without_score_or_comments() -> None:
    parsed = parse_listing(
        "6. Acme (YC S24) is hiring engineers (acme.com)\n"
        "job by whoishiring 2 hours ago | hide"
    )
    assert parsed.title == "Acme (YC S24) is hiring engineers"
    assert parsed.domain == "acme.com"
    assert parsed.author == "whoishiring"
    assert parsed.points is None
    assert parsed.comments is None
    assert "points_missing" in parsed.warnings
    assert "comments_missing" in parsed.warnings


def test_parse_unicode_title_is_preserved() -> None:
    parsed = parse_listing(
        "7. Why \u201cquotes\u201d matter \u2014 a test (example.co.uk)\n"
        "9 points by dev_user 1 day ago | hide | 3 comments"
    )
    assert parsed.title == "Why \u201cquotes\u201d matter \u2014 a test"
    assert parsed.domain == "example.co.uk"
    assert parsed.age_hours == 24.0


def test_parse_empty_text_reports_all_missing_fields() -> None:
    parsed = parse_listing(" \n\t ")
    assert parsed.rank is None
    assert parsed.title == ""
    assert "title_missing" in parsed.warnings
    assert len(parsed.warnings) == 7


def test_parse_rank_without_space_before_title() -> None:
    # Regression: raw Hacker News text contains "27.Building..." because the
    # rank span is adjacent to the title anchor.
    parsed = parse_listing(
        "27.Building a CPU (example.dev)\n19 points by random__duck 2 hours ago | hide | 4 comments"
    )
    assert parsed.rank == 27
    assert parsed.title == "Building a CPU"
    assert parsed.domain == "example.dev"


def test_parse_missing_rank() -> None:
    parsed = parse_listing(
        "A title without a rank (example.com)\n1 point by user 5 minutes ago | hide | 2 comments"
    )
    assert parsed.rank is None
    assert parsed.title == "A title without a rank"
    assert "rank_missing" in parsed.warnings


def test_invalid_domain_tail_stays_in_title() -> None:
    parsed = parse_listing(
        "8. Not a domain (2024)\n2 points by user 1 hour ago | hide | 1 comment"
    )
    assert parsed.title == "Not a domain (2024)"
    assert parsed.domain is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("18 minutes ago", 0.3),
        ("1 hour ago", 1.0),
        ("2 days ago", 48.0),
        ("1 week ago", 168.0),
    ],
)
def test_relative_age_conversion(raw: str, expected: float) -> None:
    parsed = parse_listing(f"1. Title (example.com)\n5 points by user {raw} | hide | 1 comment")
    assert parsed.age_hours == expected


def test_normalise_timestamp() -> None:
    assert normalise_timestamp("2026-11-10T16:15:43") == "2026-11-10T16:15:43Z"
    assert normalise_timestamp("2026-11-10T17:15:43+01:00") == "2026-11-10T16:15:43Z"
    assert normalise_timestamp("  ") is None
    assert normalise_timestamp("not-a-date") == "not-a-date"
