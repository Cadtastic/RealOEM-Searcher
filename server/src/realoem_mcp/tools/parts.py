"""lookup_part tool and fetch_part_xref helper (ARD section 5.11, feature A)."""

from __future__ import annotations

import re
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.parts import PartLookupResult, PartXref
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.part_numbers import matches, normalize
from realoem_mcp.parsers.partxref import parse_partxref
from realoem_mcp.services import Services

_SERIES = re.compile(r"[A-Z0-9]{2,8}")  # E90, E90N, RR4, K255, MOSP


def _series_code(raw: str) -> str:
    code = raw.strip().upper()
    if not _SERIES.fullmatch(code):
        raise InvalidInput(
            f"{raw!r} is not a RealOEM series code. Use a code from a lookup_part result's "
            "series list, e.g. E90, E90N, R56, RR4 or K25."
        )
    return code


async def fetch_part_xref(
    services: Services, part_number: str, *, series: str | None = None, refresh: bool = False
) -> tuple[PartXref | None, Page]:
    """Fetch and parse partxref for raw user input (one request, or none when cached).

    Returns (None, page) when RealOEM reports the part as not found or returns a different part
    (last-7-digit false match, junk part 00000000000). Raises InvalidInput before any request
    for malformed input. A blank series means no series. A page that fails to parse is dropped
    from the cache before LayoutChanged is re-raised, so the next call fetches it again. Used by
    lookup_part and by the fitment and supersession features.
    """
    query = normalize(part_number)
    params = {"q": query}
    if series is not None and series.strip():
        params["series"] = _series_code(series)
    page = await services.client.fetch(PageType.PARTXREF, "partxref", params, refresh=refresh)
    try:
        xref = _parse(services, page, narrowed="series" in params)
    except LayoutChanged:
        # Never keep a page we cannot parse.
        services.cache.shorten(page.url, timedelta(0), owner=page.owner)
        raise
    if xref is None or not matches(query, xref.part_number):
        return None, page
    return xref, page


def _parse(services: Services, page: Page, *, narrowed: bool) -> PartXref | None:
    xref = parse_partxref(page.html, url=page.url, brands=services.brands, client=services.client)
    if xref is not None and not narrowed and xref.models:
        raise LayoutChanged(PageType.PARTXREF, "vehicle rows on a page without a series", page.url)
    if xref is not None and narrowed and xref.series:
        raise LayoutChanged(
            PageType.PARTXREF, "series list on a page narrowed to one series", page.url
        )
    return xref


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def lookup_part(
        part_number: str, series: str | None = None, refresh: bool = False
    ) -> PartLookupResult:
        """Look up a BMW, MINI, Rolls-Royce or BMW Motorrad part number on RealOEM.

        Use it when the user gives a part number and asks what it is, whether it is current,
        what replaced it, or which vehicles use it. part_number: 11 digits or the 7-digit short
        form; spaces, dashes and dots are fine (e.g. "11 42 7 953 129"). series (optional): a
        series code from a previous result's part.series[].code (e.g. "E90", "R56", "RR4",
        "K25") to list that series' vehicles and the diagrams showing the part.

        Returns status "current", "ended" (RealOEM marks it ENDED or lists a successor) or
        "not_found", plus part: description (may be null), supplier_ref, weight_kg,
        valid_from/valid_to, superseded_by and supersedes (with dates and remarks), series
        (each with code, name, brand and production range; plain lookup) or models (vehicle id,
        body, engine and diagram link per row; with series). Model vehicle ids carry a
        nominal date RealOEM ignores (it treats them as undated), not a specific car's build
        month. Cite source_urls. One request to RealOEM, none when cached; refresh=true fetches
        a fresh copy.
        """
        try:
            query = normalize(part_number)
            xref, page = await fetch_part_xref(
                services, part_number, series=series, refresh=refresh
            )
        except RealOemError as err:
            raise ToolError(err.message) from err
        if xref is None:
            status = "not_found"
        elif xref.ended or xref.superseded_by:
            status = "ended"
        else:
            status = "current"
        return PartLookupResult.from_pages([page], query=query, status=status, part=xref)
