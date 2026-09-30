from datetime import date

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.common import (
    canonical_url,
    json_ld,
    parse_mdy,
    parse_my,
    parse_price_usd,
    parse_yyyymm00,
    require,
    text,
    tree,
)
from tests.harness import load_fixture

PARTGRP_URL = "https://www.realoem.com/bmw/enUS/partgrp?id=VB13-USA-10-2005-E90-BMW-325i"


def test_text_collapses_whitespace() -> None:
    doc = tree("<dd>(06/01/2017 &mdash;\n\n   ), Exchangeable   retrospectively</dd>")
    assert text(doc.css_first("dd")) == "(06/01/2017 — ), Exchangeable retrospectively"
    assert text(None) == ""


def test_require_returns_node_or_raises_layout_changed() -> None:
    doc = tree('<div class="content"><h1>11427953129</h1></div>')
    assert text(require(doc, "div.content > h1", "partxref", "https://x")) == "11427953129"
    with pytest.raises(LayoutChanged) as info:
        require(doc, "div.partSearchResults", "partxref", "https://x/partxref?q=1")
    assert info.value.page_type == "partxref"
    assert info.value.url == "https://x/partxref?q=1"
    assert "div.partSearchResults" in info.value.detail


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("09/01/2004", date(2004, 9, 1)),
        ("03/17/2006 (ENDED)", date(2006, 3, 17)),
        ("(06/01/2017 — )", date(2017, 6, 1)),
        ("-", None),
        ("", None),
    ],
)
def test_parse_mdy(value: str, expected: date | None) -> None:
    assert parse_mdy(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("04/2006", "2006-04"), ("Up To 12/2011", "2011-12"), ("", None), ("--", None)],
)
def test_parse_my(value: str, expected: str | None) -> None:
    assert parse_my(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("20051000", "2005-10"), ("20080700", "2008-07"), ("200510", None), ("", None)],
)
def test_parse_yyyymm00(value: str, expected: str | None) -> None:
    assert parse_yyyymm00(value) == expected


def test_invalid_month_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid month"):
        parse_my("13/2006")
    with pytest.raises(ValueError, match="invalid month"):
        parse_yyyymm00("20051300")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("$12.25", 12.25), ("$551.84", 551.84), ("$1,234.50", 1234.5), (" $ 7 ", 7.0), ("", None)],
)
def test_parse_price_usd(value: str, expected: float | None) -> None:
    assert parse_price_usd(value) == expected


def test_canonical_url_from_real_partgrp_page() -> None:
    doc = tree(load_fixture("common/partgrp_e90_325i.html"))
    assert canonical_url(doc) == PARTGRP_URL
    assert canonical_url(tree("<p>no head</p>")) is None


def test_json_ld_from_real_partgrp_page() -> None:
    doc = tree(load_fixture("common/partgrp_e90_325i.html"))
    (page,) = json_ld(doc, "CollectionPage")
    assert page["url"] == PARTGRP_URL
    items = page["mainEntity"]["itemListElement"]
    assert len(items) == int(page["mainEntity"]["numberOfItems"]) == 39
    assert items[4] == {
        "@type": "ListItem",
        "position": 5,
        "url": PARTGRP_URL + "&mg=11",
        "name": "ENGINE",
    }
    (crumbs,) = json_ld(doc, "BreadcrumbList")
    assert crumbs["itemListElement"][1]["name"] == "BMW 3 Series E90 325i"
    assert json_ld(doc, "Product") == []


def test_json_ld_handles_graphs_lists_and_bad_json() -> None:
    doc = tree(
        '<script type="application/ld+json">{not json</script>'
        '<script type="application/ld+json">[{"@type": "ImageObject", "n": 1}]</script>'
        '<script type="application/ld+json">{"@graph": [{"@type": ["Thing", "ImageObject"]}]}'
        "</script>"
    )
    assert json_ld(doc, "ImageObject") == [
        {"@type": "ImageObject", "n": 1},
        {"@type": ["Thing", "ImageObject"]},
    ]
