"""Synthetic vehicles-index rows, rendered index pages and a fake RealOEM index (F6 tests)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from html import escape
from typing import Literal

import httpx

from realoem_mcp.models.common import VehicleRef
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.parsers.vehicles import PAGE_SIZE, row_key
from realoem_mcp.vehicle_ids import VehicleId

Source = Literal["baseline", "local"]
ID_SEGMENTS = {"bmw": "BMW", "motorrad": "BMW", "mini": "Mini", "rolls-royce": "Rolls_Royce"}
MODEL_PREFIXES = {"bmw": "BMW", "motorrad": "BMW", "mini": "Mini", "rolls-royce": "Rolls-Royce"}


def vehicle(
    type_code: str,
    market: str = "USA",
    start: str | None = "2010-01",
    end: str | None = "2015-12",
    *,
    brand: str = "bmw",
    series_code: str = "E90",
    model_name: str = "325i",
    series_label: str | None = None,
    body: str | None = "Sedan",
    source: Source = "local",
) -> IndexedVehicle:
    """One index row. start=None makes an unlinked row (no vehicle id, no dates), like RealOEM."""
    ref = None
    if start is not None:
        year, month = start.split("-")
        segment = ID_SEGMENTS[brand]
        raw = f"{type_code}-{market}-{month}-{year}-{series_code}-{segment}-{model_name}"
        ref = VehicleRef.from_id(VehicleId.parse(raw.replace(" ", "_")), brand)
    return IndexedVehicle(
        key=row_key(type_code, market, start),
        vehicle=ref,
        brand=brand,
        series_label=series_label or f"Series {series_code}",
        series_code=series_code if ref else None,
        model_name=model_name,
        type_code=type_code,
        body=body,
        market=market,
        production_from=start,
        production_to=end if start is not None else None,
        source=source,
    )


def numbered(count: int) -> list[IndexedVehicle]:
    """count rows T000, T001, ... one production month apart from 2000-01 (sort=year order)."""
    return [
        vehicle(f"T{i:03d}", start=f"{2000 + i // 12}-{i % 12 + 1:02d}", end="2030-12")
        for i in range(count)
    ]


def render_page(rows: Sequence[IndexedVehicle], number: int) -> str:
    """vehicles?page=<number>&sort=year for an index holding `rows` (same markup as RealOEM).

    A page past the end renders without the vehicles table. RealOEM itself repeats the last
    page's rows under "Showing 8251-8218" (fixture vehicles/sort_year_past_end.html); is_past_end
    recognises both.
    """
    total = len(rows)
    last_page = max(1, math.ceil(total / PAGE_SIZE))
    if number > last_page:  # past the end: no result bar, no table
        return '<html><body><div class="vi-empty">No vehicles found.</div></body></html>'
    chunk = rows[(number - 1) * PAGE_SIZE : number * PAGE_SIZE]
    first = (number - 1) * PAGE_SIZE + 1
    body = "\n".join(_render_row(row, i) for i, row in enumerate(chunk))
    nav = ""
    if last_page > 1:
        last = (
            f'<a href="/bmw/enUS/vehicles?page={last_page}&amp;sort=year" title="Last page">'
            "&raquo;</a>"
            if number < last_page
            else '<span class="vi-pg-disabled">&raquo;</span>'
        )
        nav = f'<div id="vi-pagination"><span class="vi-pg-current">{number}</span>{last}</div>'
    return (
        '<html><body><div id="vi-result-bar"><span>Showing '
        f"<strong>{first}&ndash;{first + len(chunk) - 1}</strong> of <strong>{total}</strong> "
        'vehicles</span><span class="vi-sort">Sort: <span class="vi-sort-active">Year</span>'
        '</span></div><table id="vi-table"><thead><tr><th class="vi-col-series">Series</th>'
        f"</tr></thead><tbody>\n{body}\n</tbody></table>{nav}</body></html>"
    )


def _render_row(row: IndexedVehicle, i: int) -> str:
    model = f"{MODEL_PREFIXES[row.brand]}&nbsp;{escape(row.model_name)}"
    if row.vehicle is not None:
        model = f'<a href="/bmw/enUS/partgrp?id={escape(row.vehicle.vehicle_id)}">{model}</a>'
    prod = ""
    if row.production_from and row.production_to:
        prod = f"{_my(row.production_from)}&ndash;{_my(row.production_to)}"
    cells = [
        ("series", escape(row.series_label)),
        ("model", model),
        ("type", row.type_code),
        ("body", escape(row.body or "N/A")),
        ("prod", prod),
        ("market", row.market),
    ]
    tds = "".join(f'<td class="vi-col-{name}">{value}</td>' for name, value in cells)
    return f'<tr class="r{i % 2}">{tds}</tr>'


def _my(year_month: str) -> str:
    year, month = year_month.split("-")
    return f"{month}/{year}"


class SyntheticIndex(httpx.AsyncBaseTransport):
    """Serves vehicles?page=N&sort=year from `rows`, which tests may change between requests."""

    def __init__(self, rows: Sequence[IndexedVehicle]) -> None:
        self.rows = list(rows)
        self.requests: list[httpx.Request] = []
        self.on_request: Callable[[int], None] | None = None  # called with the request count
        self.past_end_html: str | None = None  # replaces the default page past the end

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(len(self.requests))
        params = request.url.params
        if request.url.path != "/bmw/enUS/vehicles" or params.get("sort") != "year":
            return httpx.Response(404, text="not a vehicles index URL", request=request)
        number = int(params["page"])
        past_end = (number - 1) * PAGE_SIZE >= len(self.rows)
        if past_end and self.past_end_html is not None:
            html = self.past_end_html
        else:
            html = render_page(self.rows, number)
        headers = {"Content-Type": "text/html;charset=UTF-8"}
        return httpx.Response(200, text=html, headers=headers, request=request)
