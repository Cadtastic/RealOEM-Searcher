"""Catalog tools (feature C, ARD section 5.11): model cascade, main groups, diagrams, parts lists.

fetch_diagram_list and fetch_diagram_parts are exported for feature D (fitment).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, NotFound, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.catalog import (
    DiagramListResult,
    DiagramPartsResult,
    PartGroupsResult,
    VehicleSelectionResult,
)
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.partgrp import (
    DIAG_ID,
    MAIN_GROUP,
    parse_diagram_list,
    parse_part_groups,
    vehicle_brand,
)
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
MISSING_GROUP_TTL = timedelta(days=1)
_PROD = re.compile(r"\d{4}(0[1-9]|1[0-2])00")
_CODE = re.compile(r"[A-Za-z0-9]+")


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def select_vehicle(
        product: Literal["P", "M"] = "P",
        archive: Literal["0", "1"] | None = None,
        series: str | None = None,
        body: str | None = None,
        model: str | None = None,
        market: str | None = None,
        prod: str | None = None,
        engine: str | None = None,
        steering: str | None = None,
        trans: str | None = None,
        refresh: bool = False,
    ) -> VehicleSelectionResult:
        """Pick a vehicle in RealOEM's catalog one level at a time, when there is no VIN.

        Levels in order: product (P cars incl. MINI and Rolls-Royce, M motorcycles), catalog
        (sent as archive: 0 current, 1 classic for older models such as E30/E36/E46/R53),
        series, body, model, market, prod (production month as YYYYMM00, e.g. 20051000),
        engine, steering, trans (the last two mostly for classic cars). Call it first with
        just product (or nothing), then call again with every value in `selected` plus the
        `value` of your choice from `options` for `next_level`. Levels with a single option
        (and USA under this US catalog) are auto-selected and appear in `selected`. Parameter
        names equal level names except catalog, whose parameter is archive. When complete is
        true, vehicle.vehicle_id is ready for list_part_groups. refresh=true ignores the cache.
        """
        levels = {
            "product": product,
            "archive": archive,
            "series": series,
            "body": body,
            "model": model,
            "market": market,
            "prod": prod,
            "engine": engine,
            "steering": steering,
            "trans": trans,
        }
        try:
            return await _select(services, levels, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def list_part_groups(vehicle_id: str, refresh: bool = False) -> PartGroupsResult:
        """List a vehicle's specifications and its main parts groups (one request).

        vehicle_id comes from decode_vin, select_vehicle or another RealOEM result. Returns
        specs (vehicle with RealOEM's canonical vehicle id, model_name, body, engine, steering,
        transmission) and main_groups (mg number such as "11" and name such as "ENGINE"); pass
        an mg to list_diagrams. refresh=true ignores the cache.
        """
        try:
            vid = _vehicle_id(services, vehicle_id)
            page = await _fetch(services, PageType.PARTGRP, {"id": str(vid)}, vid, refresh=refresh)
            with _expire_if_unparseable(services, page):
                groups = parse_part_groups(page.html, url=page.url, brands=services.brands)
            return PartGroupsResult.from_pages([page], **dict(groups))
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def list_diagrams(
        vehicle_id: str, main_group: str, refresh: bool = False
    ) -> DiagramListResult:
        """List the subgroups and diagrams of one main group of a vehicle (one request).

        main_group is the two-digit mg from list_part_groups (e.g. "11" engine, "34" brakes).
        Returns subgroups (code, name) with their diagrams (diagram.diag_id, diagram.name,
        diagram.url, thumbnail_url); pass a diag_id to get_diagram_parts. Titles can repeat
        (two "OIL PAN" diagrams), so always refer to diagrams by diag_id. refresh=true
        ignores the cache.
        """
        try:
            result, _ = await fetch_diagram_list(  # never None without cache_only
                services, vehicle_id, main_group, refresh=refresh
            )
            return result
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def get_diagram_parts(
        vehicle_id: str, diag_id: str, refresh: bool = False
    ) -> DiagramPartsResult:
        """Return one diagram's parts list, image and hotspots for a vehicle (one request).

        diag_id comes from list_diagrams (or from a lookup_part result). RealOEM filters the
        list by the vehicle id's production month. Each row has position, description,
        supplement, qty, valid_from/valid_to ("YYYY-MM"), part_number, price_usd, notes (see
        notes_legend), has_photo, indent and conditions (text plus option_codes such as
        S205A=Yes, meaning "only for vehicles with that option"). hotspots are boxes per
        position in the same pixel space as image_width x image_height. refresh=true ignores
        the cache.
        """
        try:
            result, _ = await fetch_diagram_parts(  # never None without cache_only
                services, vehicle_id, diag_id, refresh=refresh
            )
            return result
        except RealOemError as err:
            raise ToolError(err.message) from err


async def fetch_diagram_list(
    services: Services,
    vehicle_id: str,
    main_group: str,
    *,
    refresh: bool = False,
    cache_only: bool = False,
) -> tuple[DiagramListResult, Page] | None:
    """A main group's diagram list. cache_only=True never touches the network: None on a miss."""
    vid = _vehicle_id(services, vehicle_id)
    if not MAIN_GROUP.fullmatch(main_group):
        raise InvalidInput(
            f"main_group must be a two-digit RealOEM main group such as 11, got {main_group!r}."
        )
    params = {"id": str(vid), "mg": main_group}
    page = await _load(
        services, PageType.PARTGRP, params, vid, refresh=refresh, cache_only=cache_only
    )
    if page is None:
        return None
    brand = vehicle_brand(services.brands, vid)
    with _expire_if_unparseable(services, page):
        subgroups = parse_diagram_list(
            page.html,
            url=page.url,
            client=services.client,
            vehicle_id=str(vid),
            dedupe_names=brand.dedupe_repeated_names,
        )
    if not subgroups:
        services.cache.shorten(page.url, MISSING_GROUP_TTL, owner=page.owner)
        raise NotFound(
            f"vehicle {vid} has no main group {main_group}; list_part_groups shows the ones it has."
        )
    result = DiagramListResult.from_pages(
        [page], vehicle_id=str(vid), main_group=main_group, subgroups=subgroups
    )
    return result, page


async def fetch_diagram_parts(
    services: Services,
    vehicle_id: str,
    diag_id: str,
    *,
    refresh: bool = False,
    cache_only: bool = False,
) -> tuple[DiagramPartsResult, Page] | None:
    """A diagram's parts list. cache_only=True never touches the network: None on a miss."""
    vid = _vehicle_id(services, vehicle_id)
    if not DIAG_ID.fullmatch(diag_id):
        raise InvalidInput(
            f"diag_id looks like 11_3733 (main group, underscore, number), got {diag_id!r}."
        )
    params = {"id": str(vid), "diagId": diag_id}
    page = await _load(
        services, PageType.SHOWPARTS, params, vid, refresh=refresh, cache_only=cache_only
    )
    if page is None:
        return None
    with _expire_if_unparseable(services, page):
        parts = parse_showparts(
            page.html, url=page.url, client=services.client, vehicle_id=str(vid), diag_id=diag_id
        )
    return DiagramPartsResult.from_pages([page], **dict(parts)), page


async def _select(
    services: Services, levels: dict[str, str | None], *, refresh: bool
) -> VehicleSelectionResult:
    params: dict[str, str] = {}
    for name, value in levels.items():
        if value is None:
            continue
        if not value.strip():
            raise InvalidInput(f"{name} must not be empty; leave it out instead.")
        params[name] = value.strip()
    if "prod" in params and not _PROD.fullmatch(params["prod"]):
        raise InvalidInput(
            f"prod is a production month as YYYYMM00 (e.g. 20051000), got {params['prod']!r}."
        )
    page = await services.client.fetch(PageType.SELECT, "select", params, refresh=refresh)
    if page.redirected_away:
        raise NotFound(
            "RealOEM did not show a selection page for these values; start again with only "
            "product and add one level at a time from the options it returns."
        )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        open_level = next((level for level in select.levels if level.selected_option is None), None)
        if select.vehicle_id is None and open_level is None:
            raise LayoutChanged(PageType.SELECT, "no open level and no vehicle id", page.url)
    selected = {
        level.level: level.selected_option
        for level in select.levels
        if level.selected_option is not None
    }
    if select.vehicle_id is None:
        return VehicleSelectionResult.from_pages(
            [page],
            selected=selected,
            next_level=open_level.level,
            options=open_level.options,
            complete=False,
            vehicle=None,
            type_code=None,
            summary=None,
        )
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    product = selected["product"].value if "product" in selected else None
    brand = services.brands.for_vehicle_id(vid, product=product)
    return VehicleSelectionResult.from_pages(
        [page],
        selected=selected,
        next_level=None,
        options=[],
        complete=True,
        vehicle=VehicleRef.from_id(vid, brand.id),
        type_code=select.type_code,
        summary=select.summary,
    )


def _vehicle_id(services: Services, raw: str) -> VehicleId:
    vid = VehicleId.parse(raw, brand_segments=services.brands.brand_segments())
    if not _CODE.fullmatch(vid.type_code) or not _CODE.fullmatch(vid.market):
        raise InvalidInput(
            f"{raw!r} is not a RealOEM vehicle id (e.g. VB13-USA-10-2005-E90-BMW-325i); get one "
            "from decode_vin or select_vehicle."
        )
    return vid


async def _load(
    services: Services,
    page_type: PageType,
    params: dict[str, str],
    vid: VehicleId,
    *,
    refresh: bool,
    cache_only: bool,
) -> Page | None:
    """The page from the cache only (None on a miss), or fetched as usual."""
    if cache_only:
        return services.client.cached(page_type, page_type.value, params)
    return await _fetch(services, page_type, params, vid, refresh=refresh)


async def _fetch(
    services: Services,
    page_type: PageType,
    params: dict[str, str],
    vid: VehicleId,
    *,
    refresh: bool,
) -> Page:
    """Fetch a vehicle page; RealOEM redirects unknown vehicle ids to its landing page."""
    page = await services.client.fetch(page_type, page_type.value, params, refresh=refresh)
    if page.redirected_away:
        raise NotFound(
            f"RealOEM has no vehicle {vid}. Use a vehicle id from decode_vin or select_vehicle."
        )
    return page


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW, owner=page.owner)
        raise
