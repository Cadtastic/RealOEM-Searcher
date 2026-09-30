from datetime import UTC, datetime

import pytest

from realoem_mcp.config import Settings
from realoem_mcp.http_client import Page, build_url
from realoem_mcp.page_types import PageType


def test_build_url_keeps_param_order_and_encodes_with_percent_20() -> None:
    got = build_url(
        Settings(),
        "select",
        {"product": "M", "series": "K50", "model": "R 1250 GS 19 (0J91, 0J93)"},
    )
    assert got == (
        "https://www.realoem.com/bmw/enUS/select"
        "?product=M&series=K50&model=R%201250%20GS%2019%20%280J91%2C%200J93%29"
    )


def test_build_url_without_params_has_no_query() -> None:
    assert build_url(Settings(), "select", {}) == "https://www.realoem.com/bmw/enUS/select"


def test_build_url_uses_configured_base_url() -> None:
    got = build_url(Settings(base_url="http://127.0.0.1:9/"), "partxref", {"q": "11427953129"})
    assert got == "http://127.0.0.1:9/bmw/enUS/partxref?q=11427953129"


@pytest.mark.parametrize("path", ["", "../admin", "partxref?q=1", "PartXref", "a/b"])
def test_build_url_rejects_odd_paths(path: str) -> None:
    with pytest.raises(ValueError, match="invalid RealOEM path"):
        build_url(Settings(), path, {})


@pytest.mark.parametrize("key", ["dmode", "DMode"])
def test_build_url_never_sends_dmode(key: str) -> None:
    with pytest.raises(ValueError, match="dmode is never sent"):
        build_url(Settings(), "partgrp", {"id": "VB13-USA-10-2005-E90-BMW-325i", key: "0"})


def _page(url: str, final_url: str) -> Page:
    return Page(
        page_type=PageType.PARTGRP,
        url=url,
        final_url=final_url,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=False,
    )


def test_redirected_away_detects_landing_page() -> None:
    requested = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13"
    assert _page(requested, "https://www.realoem.com/bmw/").redirected_away
    assert _page(requested, "https://www.realoem.com/bmw/enUS/").redirected_away


def test_same_page_is_not_redirected_away() -> None:
    requested = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"
    assert not _page(requested, requested).redirected_away
