"""decode_vin (feature B, ARD section 5.11): VIN -> RealOEM vehicle, optionally build statistics."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.http_client import Page
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.select import SelectPage
from realoem_mcp.models.vin import VinDecodeResult
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.select import parse_select
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId

VIN_HIT_TTL = timedelta(days=180)
VIN_MISS_TTL = timedelta(days=1)
EXPIRE_NOW = timedelta(0)
_SEPARATORS = re.compile(r"[\s.\-_/]+")
_LETTERS_AND_DIGITS = re.compile(r"[A-Z0-9]*")
_PRODUCTS = {"P": "car", "M": "motorcycle"}
_CATALOGS = {"0": "current", "1": "classic"}


@dataclass(frozen=True)
class VinInput:
    serial: str  # last 7 characters: the only part ever sent to RealOEM
    wmi: str | None  # manufacturer prefix (first 3 characters) of a full 17-character VIN


def normalize_vin(raw: str) -> VinInput:
    """Uppercase, drop separators (spaces . - _ /), accept exactly 7 or 17 VIN characters."""
    vin = _SEPARATORS.sub("", raw)
    # isascii first: str.upper() maps some non-ASCII letters to ASCII (U+017F long s -> "S").
    if not vin.isascii() or not _LETTERS_AND_DIGITS.fullmatch(vin.upper()):
        raise InvalidInput(f"{raw!r} is not a VIN: a VIN has only letters and digits.")
    vin = vin.upper()
    if len(vin) not in (7, 17):
        raise InvalidInput(
            f"A VIN has 17 characters; give all 17 or just the last 7 (got {len(vin)})."
        )
    if bad := sorted(set(vin) & set("IOQ")):
        raise InvalidInput(
            f"VINs never contain the letters I, O or Q (found {', '.join(bad)}); "
            "check for a 1 or 0 typed as a letter."
        )
    return VinInput(serial=vin[-7:], wmi=vin[:3] if len(vin) == 17 else None)


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def decode_vin(vin: str, refresh: bool = False) -> VinDecodeResult:
        """Decode a BMW, MINI, Rolls-Royce or BMW Motorrad VIN with RealOEM.

        Use when the user gives a VIN (all 17 characters or just the last 7) and wants to know
        the vehicle, or before looking up parts for their specific car. Only the last 7
        characters are sent to RealOEM. Returns status ("found" or "not_found"); vehicle
        (vehicle_id to pass to list_part_groups or check_fitment, type_code, market,
        production_month, series, brand, model); product ("car"/"motorcycle"); catalog
        ("current"/"classic"); series_name, body, engine, and steering and transmission when
        RealOEM shows them. RealOEM silently picks one vehicle per serial, so present the result
        as RealOEM's best match; confidence is "low" when a full VIN's manufacturer prefix does
        not match the decoded brand, and warnings explain why. RealOEM has no option codes, paint
        or upholstery for a VIN. refresh=true ignores the cache.
        """
        try:
            return await _decode(services, vin, refresh=refresh)
        except RealOemError as err:
            raise ToolError(err.message) from err


async def _decode(services: Services, raw: str, *, refresh: bool) -> VinDecodeResult:
    vin = normalize_vin(raw)
    warnings: list[str] = []
    wmi_brand = None
    if vin.wmi is not None:
        wmi_brand = services.brands.for_wmi(vin.wmi)
        if wmi_brand is None:
            warnings.append(
                f"Unrecognized manufacturer prefix {vin.wmi}: it is not a known BMW, MINI, "
                "Rolls-Royce or BMW Motorrad prefix."
            )
    page = await services.client.fetch(
        PageType.SELECT, "select", {"vin": vin.serial}, refresh=refresh, ttl=VIN_HIT_TTL
    )
    with _expire_if_unparseable(services, page):
        select = parse_select(page.html, url=page.url)
        if select.vehicle_id is None or select.type_code is None:
            services.cache.shorten(page.url, VIN_MISS_TTL)
            return VinDecodeResult.from_pages(
                [page],
                serial=vin.serial,
                status="not_found",
                confidence="normal",
                warnings=warnings,
            )
        product = _code(select, "product", _PRODUCTS, page.url)
        catalog = _code(select, "catalog", _CATALOGS, page.url)
    vid = VehicleId.parse(select.vehicle_id, brand_segments=services.brands.brand_segments())
    brand = services.brands.for_vehicle_id(vid, product="M" if product == "motorcycle" else "P")
    confidence = "normal"
    if wmi_brand is not None and wmi_brand.id != brand.id:
        confidence = "low"
        warnings.append(
            f"The VIN's manufacturer prefix {vin.wmi} belongs to {wmi_brand.display_name}, but "
            f"RealOEM matched serial {vin.serial} to a {brand.display_name} vehicle; it is "
            "probably a different vehicle with the same last 7 characters."
        )
    return VinDecodeResult.from_pages(
        [page],
        serial=vin.serial,
        status="found",
        confidence=confidence,
        warnings=warnings,
        vehicle=VehicleRef.from_id(vid, brand.id),
        product=product,
        catalog=catalog,
        series_name=_label(select, "series"),
        body=_label(select, "body"),
        engine=_label(select, "engine"),
        steering=_label(select, "steering"),
        transmission=_label(select, "trans"),
    )


@contextmanager
def _expire_if_unparseable(services: Services, page: Page) -> Iterator[None]:
    """ARD 5.10: a page that fails to parse must not stay cached; expire it, then re-raise."""
    try:
        yield
    except LayoutChanged:
        services.cache.shorten(page.url, EXPIRE_NOW)
        raise


def _code(select: SelectPage, level: str, names: dict[str, str], url: str) -> str:
    option = select.selected(level)
    if option is None or option.value not in names:
        raise LayoutChanged(PageType.SELECT, f"VIN result has no known {level} selected", url)
    return names[option.value]


def _label(select: SelectPage, level: str) -> str | None:
    option = select.selected(level)
    return option.label if option is not None else None
