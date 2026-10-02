"""Vehicle index models (ARD section 5.11, F6) plus the vehicles-page parser output."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta, VehicleRef


class IndexedVehicle(BaseModel):
    key: str  # "{type}-{market}-{MM}-{YYYY}", or "{type}-{market}--" for unlinked rows
    vehicle: VehicleRef | None  # None for unlinked rows
    brand: str
    series_label: str
    series_code: str | None
    model_name: str
    type_code: str
    body: str | None
    market: str
    production_from: str | None  # "YYYY-MM"
    production_to: str | None  # "YYYY-MM"
    source: Literal["baseline", "local"]


class IndexMeta(BaseModel):
    built_at: date | None  # None when no baseline is installed
    baseline_total: int
    local_rows: int
    last_update_at: datetime | None


class VehicleSearchResult(BaseModel):
    total_matches: int
    vehicles: list[IndexedVehicle]
    index: IndexMeta


class VehicleIndexUpdateResult(ResultMeta):
    # "cooldown": hosted server only; the shared index was checked under an hour ago.
    status: Literal["up_to_date", "updated", "partial", "drift", "cooldown"]
    added: list[IndexedVehicle]
    remote_total: int
    local_total: int
    pages_fetched: int
    message: str


class VehicleIndexPage(BaseModel):
    """One parsed vehicles-index page (parsers/vehicles.py)."""

    page: int  # current page number
    last_page: int
    first: int  # "Showing <first>-<last> of <total>"
    last: int
    total: int
    rows: list[IndexedVehicle]  # source="local": rows read from RealOEM, not from the baseline
