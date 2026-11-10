from __future__ import annotations

from webtext.textnorm import clean_for_matching, clean_text, truncate


def test_clean_text_removes_whitespace_artifacts() -> None:
    raw = "  Hello\xa0\u200b  world \n\n\t next\tline  "
    assert clean_text(raw) == "Hello world next line"


def test_clean_text_unescapes_entities_and_normalises_unicode() -> None:
    assert clean_text("AT&amp;T \ufb01nal \u00e9") == "AT&T final \u00e9"


def test_clean_text_strips_control_characters() -> None:
    assert clean_text("a\x00b\x07c\x7f") == "abc"


def test_clean_text_multiline_preserves_line_structure() -> None:
    raw = "  1. A title\xa0 here  \n\n\n  26 points by bob   \n"
    assert clean_text(raw, multiline=True) == "1. A title here\n26 points by bob"


def test_clean_text_none_and_empty() -> None:
    assert clean_text(None) == ""
    assert clean_text("   ") == ""
    assert clean_text("x", multiline=True) == "x"


def test_clean_for_matching_normalises_typography() -> None:
    assert clean_for_matching("\u201cquoted\u201d \u2014 it\u2019s fine") == (
        '"quoted" - it\'s fine'
    )


def test_truncate_is_whitespace_clean_and_does_not_exceed_limit() -> None:
    result = truncate("  alpha beta gamma  ", 10)
    assert len(result) <= 10
    assert result.endswith("\u2026")
    assert truncate("short", 10) == "short"
