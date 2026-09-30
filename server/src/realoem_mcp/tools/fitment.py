"""check_fitment and compare_vehicles tools (ARD section 5.11, feature D; site notes 3.8)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import chain, zip_longest
from urllib.parse import parse_qs, urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import DiagramListResult, PartRow
from realoem_mcp.models.fitment import (
    CompareScope,
    ComparisonResult,
    FitmentResult,
    PartComparison,
    PartSummary,
)
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.part_numbers import matches, normalize
from realoem_mcp.parsers.partgrp import DIAG_ID, MAIN_GROUP
from realoem_mcp.parsers.partsearch import parse_partsearch
from realoem_mcp.services import Services
from realoem_mcp.tools.catalog import fetch_diagram_list, fetch_diagram_parts
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
MIN_REQUESTS, MAX_REQUESTS = 2, 60
NO_PART_NUMBER = {None, "--"}
_CODE = re.compile(r"[A-Za-z0-9]+")
_SUBGROUP = re.compile(r"\d{2}")


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


@dataclass
class _Occurrences:
    description: str | None
    qty: list[str] = field(default_factory=list)
    diag_ids: list[str] = field(default_factory=list)


@dataclass
class _Side:
    vehicle_id: str
    scope: list[str]  # in-scope diagIds, in list order
    ignored: list[str]  # requested diag_ids outside the scope
    rows: dict[str, list[PartRow]] = field(default_factory=dict)  # diagIds read
    unfetched: list[str] = field(default_factory=list)

    def parts(self) -> dict[str, _Occurrences]:
        """Part number -> occurrences over the diagrams read, in scope order."""
        found: dict[str, _Occurrences] = {}
        for diag_id in self.scope:
            for row in self.rows.get(diag_id, []):
                if row.part_number in NO_PART_NUMBER:
                    continue
                entry = found.setdefault(row.part_number, _Occurrences(row.description))
                entry.qty.append(row.qty or "")
                if diag_id not in entry.diag_ids:
                    entry.diag_ids.append(diag_id)
        return found


def _check_scope(
    main_group: str, subgroup: str | None, diag_ids: list[str] | None, max_requests: int
) -> list[str] | None:
    """diag_ids without duplicates (None when absent or empty); InvalidInput before any request."""
    if not MAIN_GROUP.fullmatch(main_group):
        raise InvalidInput(
            f"main_group must be a two-digit RealOEM main group such as 11, got {main_group!r}."
        )
    if subgroup is not None and not _SUBGROUP.fullmatch(subgroup):
        raise InvalidInput(
            f"subgroup must be a two-digit subgroup code from list_diagrams such as 10, got "
            f"{subgroup!r}."
        )
    for diag_id in diag_ids or []:
        if not DIAG_ID.fullmatch(diag_id) or not diag_id.startswith(f"{main_group}_"):
            raise InvalidInput(
                f"diag_ids must be diagrams of main group {main_group} such as "
                f"{main_group}_3733, got {diag_id!r}."
            )
    if not MIN_REQUESTS <= max_requests <= MAX_REQUESTS:
        raise InvalidInput(
            f"max_requests must be between {MIN_REQUESTS} and {MAX_REQUESTS}, not {max_requests}."
        )
    return list(dict.fromkeys(diag_ids)) if diag_ids else None


def _side(diagrams: DiagramListResult, subgroup: str | None, diag_ids: list[str] | None) -> _Side:
    scope = [
        thumb.diagram.diag_id
        for group in diagrams.subgroups
        if subgroup is None or group.code == subgroup
        for thumb in group.diagrams
    ]
    if diag_ids is not None:
        scope = [diag_id for diag_id in scope if diag_id in diag_ids]
    ignored = [diag_id for diag_id in diag_ids or [] if diag_id not in scope]
    return _Side(vehicle_id=diagrams.vehicle_id, scope=scope, ignored=ignored)


async def compare(
    services: Services,
    vehicle_a: str,
    vehicle_b: str,
    main_group: str,
    *,
    subgroup: str | None = None,
    diag_ids: list[str] | None = None,
    max_requests: int = 20,
    refresh: bool = False,
) -> ComparisonResult:
    """Compare the part numbers two vehicles use in one main group, within a request budget.

    Budget = network requests (cached pages are free). Both diagram lists come first, then the
    in-scope diagrams alternating A/B in list order; once the budget is spent the rest are read
    from the cache only, and cache misses are reported as unfetched.
    """
    ids = [str(_vehicle_id(services, raw)) for raw in (vehicle_a, vehicle_b)]
    diag_ids = _check_scope(main_group, subgroup, diag_ids, max_requests)
    pages: list[Page] = []
    lists: list[DiagramListResult] = []
    for vehicle_id in ids:
        diagrams, page = await fetch_diagram_list(services, vehicle_id, main_group, refresh=refresh)
        lists.append(diagrams)
        pages.append(page)
    if subgroup is not None and not any(
        group.code == subgroup for diagrams in lists for group in diagrams.subgroups
    ):
        raise NotFound(
            f"neither vehicle has subgroup {subgroup} in main group {main_group}; list_diagrams "
            "shows the subgroups of each vehicle."
        )
    a, b = (_side(diagrams, subgroup, diag_ids) for diagrams in lists)
    used = sum(not page.from_cache for page in pages)
    for side, diag_id in _alternate(a, b):
        fetched = await fetch_diagram_parts(
            services,
            side.vehicle_id,
            diag_id,
            refresh=refresh,
            cache_only=used >= max_requests,
        )
        if fetched is None:
            side.unfetched.append(diag_id)
            continue
        parts, page = fetched
        pages.append(page)
        used += not page.from_cache
        side.rows[diag_id] = parts.rows
    return _result(
        pages, a, b, CompareScope(main_group=main_group, subgroup=subgroup, diag_ids=diag_ids)
    )


def _alternate(a: _Side, b: _Side) -> list[tuple[_Side, str]]:
    """A's first diagram, B's first, A's second, ... then the rest of the longer scope."""
    pairs = zip_longest(((a, d) for d in a.scope), ((b, d) for d in b.scope))
    return [item for item in chain.from_iterable(pairs) if item is not None]


def _result(pages: list[Page], a: _Side, b: _Side, scope: CompareScope) -> ComparisonResult:
    parts_a, parts_b = a.parts(), b.parts()
    in_both = [
        PartComparison(
            part_number=number,
            description=occ.description or parts_b[number].description,
            qty_a=occ.qty,
            qty_b=parts_b[number].qty,
        )
        for number, occ in parts_a.items()
        if number in parts_b
    ]
    return ComparisonResult.from_pages(
        pages,
        scope=scope,
        complete=not a.unfetched and not b.unfetched,
        in_both=in_both,
        only_a=_only(parts_a, parts_b),
        only_b=_only(parts_b, parts_a),
        unfetched_a=a.unfetched,
        unfetched_b=b.unfetched,
        ignored_diag_ids_a=a.ignored,
        ignored_diag_ids_b=b.ignored,
    )


def _only(mine: dict[str, _Occurrences], other: dict[str, _Occurrences]) -> list[PartSummary]:
    return [
        PartSummary(
            part_number=number, description=occ.description, qty=occ.qty, diag_ids=occ.diag_ids
        )
        for number, occ in mine.items()
        if number not in other
    ]


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def check_fitment(
        part_number: str, vehicle_id: str, refresh: bool = False
    ) -> FitmentResult:
        """Check whether a part number is used on one specific vehicle (one request).

        part_number: 11 digits or the 7-digit short form (spaces, dashes, dots are fine).
        vehicle_id: from decode_vin or select_vehicle (the car's own production month; ids
        from lookup_part rows are treated as undated, and find_vehicle ids carry the model's
        production-start month, not the car's build month). Returns fits, the
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

    @app.tool()
    async def compare_vehicles(
        vehicle_a: str,
        vehicle_b: str,
        main_group: str,
        subgroup: str | None = None,
        diag_ids: list[str] | None = None,
        max_requests: int = 20,
        refresh: bool = False,
    ) -> ComparisonResult:
        """Compare the part numbers two vehicles use in one main group (e.g. "11" engine).

        Narrow with subgroup (two-digit code from list_diagrams, e.g. "10") and/or diag_ids
        (diagrams of that main group); both given = only listed diagrams inside the subgroup.
        Compares the set of part numbers over all in-scope diagrams of each vehicle, so the
        diagrams need not match: in_both (qty_a/qty_b = raw quantity per occurrence), only_a,
        only_b. ignored_diag_ids_a/b = requested diag_ids outside that vehicle's scope. Costs
        2 requests for the diagram lists plus one per diagram; max_requests (2-60, default
        20) caps network requests, cached pages are free. complete=false means unfetched_a/b
        diagrams were not read: say the result is partial; calling again with the same
        arguments continues from the cache. Cite source_urls. refresh=true ignores the cache.
        """
        try:
            return await compare(
                services,
                vehicle_a,
                vehicle_b,
                main_group,
                subgroup=subgroup,
                diag_ids=diag_ids,
                max_requests=max_requests,
                refresh=refresh,
            )
        except RealOemError as err:
            raise ToolError(err.message) from err
