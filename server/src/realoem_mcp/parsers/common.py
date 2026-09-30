"""selectolax helpers and value parsers shared by every page parser (ARD section 5.9)."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from realoem_mcp.errors import LayoutChanged

Tree = LexborHTMLParser
Node = LexborNode

_MDY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_MY = re.compile(r"(\d{2})/(\d{4})")
_YYYYMM00 = re.compile(r"(\d{4})(\d{2})00")
_PRICE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")


def tree(html: str) -> Tree:
    return LexborHTMLParser(html)


def text(node: Node | None) -> str:
    """All text under node with whitespace collapsed; "" for None.

    <br> and block-level boundaries are NOT turned into spaces: text on either side of them is
    joined as written. Callers that need a separator there must split the nodes themselves.
    """
    if node is None:
        return ""
    return " ".join(node.text(deep=True).split())


def require(root: Tree | Node, selector: str, page_type: str, url: str) -> Node:
    """First match of selector, or LayoutChanged when the page lacks it."""
    node = root.css_first(selector)
    if node is None:
        raise LayoutChanged(page_type, f"missing {selector!r}", url)
    return node


def parse_mdy(value: str) -> date | None:
    """First MM/DD/YYYY in value (e.g. "03/17/2006 (ENDED)") as a date; None if absent."""
    match = _MDY.search(value)
    if match is None:
        return None
    month, day, year = (int(group) for group in match.groups())
    return date(year, month, day)


def parse_my(value: str) -> str | None:
    """First MM/YYYY in value as "YYYY-MM"; None if absent."""
    match = _MY.search(value)
    if match is None:
        return None
    month, year = match.groups()
    return _year_month(year, month)


def parse_yyyymm00(value: str) -> str | None:
    """RealOEM prod code "20051000" as "2005-10"; None if value is not in that form."""
    match = _YYYYMM00.fullmatch(value.strip())
    if match is None:
        return None
    year, month = match.groups()
    return _year_month(year, month)


def parse_price_usd(value: str) -> float | None:
    """Price text such as "$1,234.56" as 1234.56; None when no price is shown."""
    match = _PRICE.search(value)
    if match is None:
        return None
    return float(match.group(1).replace(",", ""))


def canonical_url(root: Tree | Node) -> str | None:
    link = root.css_first('link[rel="canonical"]')
    if link is None:
        return None
    return link.attributes.get("href") or None


def json_ld(root: Tree | Node, type_: str) -> list[dict[str, Any]]:
    """Every JSON-LD object whose @type is type_, in document order. Invalid blocks are skipped."""
    found: list[dict[str, Any]] = []
    for script in root.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text(deep=True))
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph", [item])
            for obj in [graph] if isinstance(graph, dict) else graph:
                if isinstance(obj, dict) and _has_type(obj, type_):
                    found.append(obj)
    return found


def _has_type(obj: dict[str, Any], type_: str) -> bool:
    declared = obj.get("@type")
    return declared == type_ or (isinstance(declared, list) and type_ in declared)


def _year_month(year: str, month: str) -> str:
    if not 1 <= int(month) <= 12:
        raise ValueError(f"invalid month {month!r}")
    return f"{year}-{month}"
