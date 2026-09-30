"""check_fitment and compare_vehicles tools (ARD section 5.11, feature D; site notes 3.8)."""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.fitment import FitmentResult
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.part_numbers import matches, normalize
from realoem_mcp.parsers.partsearch import parse_partsearch
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
_CODE = re.compile(r"[A-Za-z0-9]+")


def _vehicle_id(services: Services, raw: str) -> VehicleId:
    vid = VehicleId.parse(raw, brand_segments=services.brands.brand_segments())
    if not _CODE.fullmatch(vid.type_code) or not _CODE.fullmatch(vid.market):
        raise InvalidInput(
            f"{raw!r} is not a RealOEM vehicle id (e.g. VB13-USA-10-2005-E90-BMW-325i); get one "
            "from decode_vin or select_vehicle."
        )
    return vid


async def check(
    services: Services, part_number: str, vehicle_id: str, *, refresh: bool = False
) -> FitmentResult:
    """One partsearch request (none when cached): is the part on this vehicle, and where."""
    query = normalize(part_number)
    vid = _vehicle_id(services, vehicle_id)
    params = {"id": str(vid), "q": query}
    page = await services.client.fetch(PageType.PARTSEARCH, "partsearch", params, refresh=refresh)
    if page.redirected_away:
        raise _redirect_error(page, query, vid)
    try:
        search = parse_partsearch(
            page.html, url=page.url, client=services.client, vehicle_id=str(vid)
        )
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)  # never keep a page we cannot parse
        raise
    if search is None or not matches(query, search.part_number):
        raise _unknown_part(query)
    diagrams = {hit.diagram.diag_id: hit.diagram for hit in search.hits}
    return FitmentResult.from_pages(
        [page],
        query=query,
        vehicle_id=str(vid),
        fits=bool(search.hits),
        used_part_numbers=list(dict.fromkeys(hit.part_number for hit in search.hits)),
        description=search.description,
        price_usd=search.price_usd,
        diagrams=list(diagrams.values()),
        superseded_by=search.superseded_by,
        supersedes=search.supersedes,
    )


def _unknown_part(query: str) -> NotFound:
    return NotFound(
        f"RealOEM does not know part {query}. Check the number with lookup_part; enter all "
        "11 digits if you used the 7-digit short form."
    )


def _redirect_error(page: Page, query: str, vid: VehicleId) -> NotFound:
    """Site notes 3.8: an unknown part redirects to partgrp?id=..&nfpn=<pn>; else the vehicle."""
    target = urlsplit(page.final_url)
    if target.path.endswith("/partgrp") and "nfpn" in parse_qs(target.query):
        return _unknown_part(query)
    return NotFound(
        f"RealOEM has no vehicle {vid}. Use a vehicle id from decode_vin or select_vehicle."
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def check_fitment(
        part_number: str, vehicle_id: str, refresh: bool = False
    ) -> FitmentResult:
        """Check whether a part number is used on one specific vehicle (one request).

        part_number: 11 digits or the 7-digit short form (spaces, dashes, dots are fine).
        vehicle_id: from decode_vin or select_vehicle (the car's own production month; ids
        from lookup_part rows or find_vehicle carry a series or production start month, not
        the car's build month). Returns fits, the
        diagrams showing the part on this vehicle, and used_part_numbers: the numbers
        RealOEM names on those diagrams. When they differ from query, RealOEM resolved a
        supersession (the vehicle uses the newer number). Also description, price_usd,
        superseded_by and supersedes. fits=false means RealOEM knows the part but not on this
        vehicle. An unknown part number or vehicle id is an error. Cite source_urls.
        refresh=true ignores the cache.
        """
        try:
            return await check(services, part_number, vehicle_id, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err
