"""Every committed fixture must be the output of scripts/trim_fixture.py (ARD AD10)."""

import re
from pathlib import Path

import pytest

from scripts.trim_fixture import trim

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ALL_FIXTURES = sorted(FIXTURES.rglob("*.html"))
MASKED_VIN = re.compile(r"X{10}[A-HJ-NPR-Z0-9]{7}")
# Same boundaries as the trimmer's VIN pattern: standing alone or right after a percent-escape.
VIN_LIKE = re.compile(
    r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2}))"
    r"(?=[A-HJ-NPR-Z0-9]{0,16}[0-9])(?=[A-HJ-NPR-Z0-9]{0,16}[A-HJ-NPR-Z])"
    r"[A-HJ-NPR-Z0-9]{17}"
    r"(?![A-Za-z0-9])"
)
FORBIDDEN = re.compile(
    r"jsessionid|linksynergy|ecs-tuning-link|href=[\"']?(?:https?:)?//click\.", re.IGNORECASE
)


def test_fixture_folder_is_not_empty() -> None:
    assert ALL_FIXTURES, f"no fixtures under {FIXTURES}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_is_trimmed(path: Path) -> None:
    html = path.read_text(encoding="utf-8")
    assert trim(html) == html, f"re-run scripts/trim_fixture.py for {path.name}"


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_has_no_unmasked_vin(path: Path) -> None:
    html = MASKED_VIN.sub("", path.read_text(encoding="utf-8"))
    assert VIN_LIKE.findall(html) == []


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_has_no_session_ids_or_affiliate_links(path: Path) -> None:
    assert FORBIDDEN.findall(path.read_text(encoding="utf-8")) == []
