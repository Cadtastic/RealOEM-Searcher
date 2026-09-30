"""partsearch: one part on one vehicle, the diagrams showing it (site notes 3.8)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.models.common import DiagramRef
from realoem_mcp.models.fitment import PartSearch, PartSearchHit
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_price_usd, require, text, tree
from realoem_mcp.parsers.partgrp import DIAG_ID
from realoem_mcp.parsers.supersession import parse_supersession

PAGE = PageType.PARTSEARCH
# "11427953129", or "11427541827 - Set oil-filter element" as on partxref's no-vehicles template
_HEADING = re.compile(r"(?P<number>\d{11})(?:\s*-\s*(?P<description>.+))?")
MISS = "The specified part was not found."
NO_VEHICLES = "Search for another part"  # partxref's no-vehicles template (notes 3.3)
_HIT = re.compile(r"Part (?P<number>\d{11}) was found on diagram: (?P<name>.+)")


def parse_partsearch(
    html: str, *, url: str, client: RealOemClient, vehicle_id: str
) -> PartSearch | None:
    """The partsearch page as a PartSearch, or None when it shows a "was not found" error.

    RealOEM answers an unknown part with a redirect (site notes 3.8), which the tool handles;
    the error div (partxref's markup) is read defensively. Diagram references are built for
    vehicle_id (the id that was requested). No I/O.
    """
    root = tree(html)
    error = root.css_first("div.content > div.error")
    if error is not None:
        if "was not found" not in text(error):
            raise LayoutChanged(PAGE, f"unexpected error message {text(error)!r}", url)
        return None
    heading = require(root, "div.content > h1", PAGE, url)
    content = heading.parent
    match = _HEADING.fullmatch(text(heading))
    if content is None or match is None:
        raise LayoutChanged(PAGE, f"unexpected part heading {text(heading)!r}", url)
    superseded_by, supersedes = parse_supersession(content, url=url)
    results = require(content, "div.partSearchResults", PAGE, url)
    return PartSearch(
        part_number=match["number"],
        description=text(content.css_first("div.content > h2")) or match["description"],
        price_usd=_price(content),
        hits=_hits(results, url=url, client=client, vehicle_id=vehicle_id),
        superseded_by=superseded_by,
        supersedes=supersedes,
    )


def _price(content: Node) -> float | None:
    """<dt>Price:</dt><dd>$12.25</dd> in the header list; None when empty or absent."""
    for dt in content.css("div.content > dl > dt"):
        if text(dt) == "Price:":
            dd = dt.next
            while dd is not None and dd.tag != "dd":
                dd = dd.next
            return parse_price_usd(text(dd))
    return None


def _hits(
    results: Node, *, url: str, client: RealOemClient, vehicle_id: str
) -> list[PartSearchHit]:
    diagrams = results.css("div.partSearchResults > div.diagram")
    if not diagrams:
        no_vehicles = results.css_first("h4.vs2")
        if text(results) != MISS and (no_vehicles is None or text(no_vehicles) != NO_VEHICLES):
            raise LayoutChanged(PAGE, f"unexpected search result {text(results)!r}", url)
        return []
    return [_hit(diagram, url, client, vehicle_id) for diagram in diagrams]


def _hit(diagram: Node, url: str, client: RealOemClient, vehicle_id: str) -> PartSearchHit:
    info = require(diagram, "div.diag-info", PAGE, url)
    match = _HIT.fullmatch(text(info))
    link = info.css_first('a[href*="showparts"]')
    diag_id = _diag_id(link.attributes.get("href") or "") if link is not None else None
    if match is None or diag_id is None:
        raise LayoutChanged(PAGE, f"unexpected diagram hit {text(info)!r}", url)
    return PartSearchHit(
        part_number=match["number"],
        diagram=DiagramRef.build(client, vehicle_id, diag_id, match["name"]),
    )


def _diag_id(href: str) -> str | None:
    values = parse_qs(urlsplit(href).query).get("diagId", [])
    return values[0] if len(values) == 1 and DIAG_ID.fullmatch(values[0]) else None
