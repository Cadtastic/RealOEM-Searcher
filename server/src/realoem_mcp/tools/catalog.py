"""Catalog tools (feature C, ARD section 5.11): the model cascade (select_vehicle)."""

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
from realoem_mcp.models.catalog import VehicleSelectionResult
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

EXPIRE_NOW = timedelta(0)
_PROD = re.compile(r"\d{4}(0[1-9]|1[0-2])00")


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


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise
