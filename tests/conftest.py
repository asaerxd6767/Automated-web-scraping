from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixture_html() -> str:
    path = Path(__file__).parent / "fixtures" / "hn_frontpage.html"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def output_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "listings.csv",
        tmp_path / "listings.summary.json",
        tmp_path / "raw",
    )
