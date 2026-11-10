"""Whitespace, HTML-entity, and Unicode normalisation helpers."""

from __future__ import annotations

import html
import re
import unicodedata

# Control characters that are never meaningful in a scraped text field.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_WS = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_INVISIBLE_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")
_MATCHING_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
)


def clean_text(
    value: object,
    *,
    multiline: bool = False,
    max_length: int | None = None,
) -> str:
    """Return a safe, whitespace-normalised string.

    Unstructured HTML text frequently contains non-breaking spaces, zero-width
    characters, HTML entities, Windows newlines, and runs of indentation.  Those
    artefacts break naive ``split``/regex logic, so they are collapsed here
    before any extraction happens.

    ``multiline=True`` keeps line boundaries (one blank line between blocks) so
    a listing's headline and metadata can still be separated.
    """

    if value is None:
        return ""

    text = html.unescape(str(value))
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_INVISIBLE_CHARS)
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)

    if multiline:
        lines = [_HORIZONTAL_WS.sub(" ", line).strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)
        text = _BLANK_LINES.sub("\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text).strip()

    if max_length is not None and len(text) > max_length:
        text = text[:max_length].rstrip()

    return text


def clean_for_matching(value: object) -> str:
    """Normalise typography so literal text matching is predictable."""

    return clean_text(value).translate(_MATCHING_TRANSLATION)


def truncate(value: object, max_length: int) -> str:
    """Whitespace-clean and truncate a value without leaving a partial word."""

    text = clean_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "\u2026"
