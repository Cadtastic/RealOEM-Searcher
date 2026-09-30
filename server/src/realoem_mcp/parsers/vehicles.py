"""Vehicles index page: /bmw/enUS/vehicles?page=N&sort=year (site notes section 5.5)."""

from __future__ import annotations

import math
import re

from realoem_mcp.brands import BrandRegistry
from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle, VehicleIndexPage
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.common import Node, parse_my, require, text, tree
from realoem_mcp.vehicle_ids import VehicleId

PAGE_TYPE = PageType.VEHICLES.value
PAGE_SIZE = 50  # vehicles per index page
LINK_PREFIX = "/bmw/enUS/partgrp?id="
NBSP = "\xa0"
# Brand prefix of the model cell ("Mini&nbsp;Cooper") for rows without a link; others go by type.
UNLINKED_PREFIX_BRANDS = {"Mini": "mini", "Rolls-Royce": "rolls-royce"}
_RANGE = re.compile(r"(\d[\d,]*)\s*[^\d\s,]\s*(\d[\d,]*)")  # "8201&ndash;8218"
_MONTH_YEAR = re.compile(r"\d{2}/\d{4}")
_PAGE_PARAM = re.compile(r"[?&]page=(\d+)")


def product_for_type(type_code: str) -> str:
    """Motorcycle type codes start with "0" (site notes section 5.5)."""
    return "M" if type_code.startswith("0") else "P"


def is_past_end(html: str) -> bool:
    """True for a page past the end of the index: no table#vi-table, a table without rows, or
    RealOEM's live answer, which repeats the last page's rows under a result bar whose range
    starts after it ends ("Showing 8251-8218" for page 166 of 165)."""
    root = tree(html)
    if root.css_first("table#vi-table > tbody > tr.r0, table#vi-table > tbody > tr.r1") is None:
        return True
    bar = root.css_first("#vi-result-bar > span")  # the same node parse_vehicles reads
    numbers = bar.css("strong") if bar is not None else []
    showing = _RANGE.fullmatch(text(numbers[0])) if numbers else None
    if showing is None:
        return False  # parse_vehicles reports the unreadable result bar
    first, last = (int(group.replace(",", "")) for group in showing.groups())
    return first > last


def parse_vehicles(html: str, *, url: str, brands: BrandRegistry) -> VehicleIndexPage:
    root = tree(html)
    bar = require(root, "#vi-result-bar > span", PAGE_TYPE, url)
    numbers = bar.css("strong")  # a series filter adds a third <strong> ("Series: M")
    if len(numbers) < 2:
        raise LayoutChanged(PAGE_TYPE, "result bar does not show 'Showing a-b of n'", url)
    showing = _RANGE.fullmatch(text(numbers[0]))
    total_text = text(numbers[1]).replace(",", "")
    if showing is None or not total_text.isdigit():
        raise LayoutChanged(PAGE_TYPE, f"unreadable result bar {text(bar)!r}", url)
    first, last = (int(group.replace(",", "")) for group in showing.groups())
    table = require(root, "table#vi-table > tbody", PAGE_TYPE, url)
    rows = [_row(tr, url, brands) for tr in table.css("tr.r0, tr.r1")]
    if len(rows) != last - first + 1:
        raise LayoutChanged(PAGE_TYPE, f"{len(rows)} rows but 'Showing {first}-{last}'", url)
    page, last_page = _pagination(root, url)
    total = int(total_text)
    if last_page != max(1, math.ceil(total / PAGE_SIZE)) or first != (page - 1) * PAGE_SIZE + 1:
        raise LayoutChanged(
            PAGE_TYPE,
            f"page {page} of {last_page} shows rows {first}-{last} of {total}, "
            f"expected {PAGE_SIZE} rows per page",
            url,
        )
    return VehicleIndexPage(
        page=page, last_page=last_page, first=first, last=last, total=total, rows=rows
    )


def _pagination(root: Node, url: str) -> tuple[int, int]:
    nav = root.css_first("#vi-pagination")
    if nav is None:  # everything fits on one page
        return 1, 1
    current = text(require(nav, "span.vi-pg-current", PAGE_TYPE, url))
    if not current.isdigit():
        raise LayoutChanged(PAGE_TYPE, f"current page {current!r} is not a number", url)
    last_link = nav.css_first('a[title="Last page"]')
    if last_link is None:  # on the last page
        return int(current), int(current)
    match = _PAGE_PARAM.search(last_link.attributes.get("href") or "")
    if match is None:
        raise LayoutChanged(PAGE_TYPE, "last-page link has no page number", url)
    return int(current), int(match.group(1))


def _row(tr: Node, url: str, brands: BrandRegistry) -> IndexedVehicle:
    cells = {
        name: require(tr, f"td.vi-col-{name}", PAGE_TYPE, url)
        for name in ("series", "model", "type", "body", "prod", "market")
    }
    prefix, sep, model_name = cells["model"].text(deep=True).partition(NBSP)
    if not sep:
        raise LayoutChanged(PAGE_TYPE, "model cell has no brand prefix", url)
    type_code, market = text(cells["type"]), text(cells["market"])
    series_label = cells["series"].text(deep=True).strip()
    model_name = " ".join(model_name.split())
    if not (type_code and market and series_label and model_name):
        raise LayoutChanged(PAGE_TYPE, "row without series, model, type code or market", url)
    dates = _MONTH_YEAR.findall(text(cells["prod"]))
    if len(dates) not in (0, 2):
        raise LayoutChanged(PAGE_TYPE, f"unreadable production range {text(cells['prod'])!r}", url)
    start, end = (parse_my(dates[0]), parse_my(dates[1])) if dates else (None, None)
    product = product_for_type(type_code)
    link = cells["model"].css_first(f'a[href^="{LINK_PREFIX}"]')
    if link is None:
        brand = (
            UNLINKED_PREFIX_BRANDS.get(prefix.strip())
            or brands.for_series(None, product=product).id
        )
        vehicle = None
    else:
        vid = VehicleId.parse(
            (link.attributes.get("href") or "")[len(LINK_PREFIX) :],
            brand_segments=brands.brand_segments(),
        )
        brand = brands.for_vehicle_id(vid, product=product).id
        vehicle = VehicleRef.from_id(vid, brand)
    body = text(cells["body"])
    return IndexedVehicle(
        key=row_key(type_code, market, start),
        vehicle=vehicle,
        brand=brand,
        series_label=series_label,
        series_code=vehicle.series if vehicle else None,
        model_name=model_name,
        type_code=type_code,
        body=None if body in ("", "N/A") else body,
        market=market,
        production_from=start,
        production_to=end,
        source="local",
    )


def row_key(type_code: str, market: str, production_from: str | None) -> str:
    """{type}-{market}-{MM}-{YYYY}, or {type}-{market}-- without a production start."""
    if production_from is None:
        return f"{type_code}-{market}--"
    year, month = production_from.split("-")
    return f"{type_code}-{market}-{month}-{year}"
