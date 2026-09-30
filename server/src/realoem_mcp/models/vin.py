"""VIN decode models (ARD section 5.11)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import ResultMeta, VehicleRef


class ProductionStats(BaseModel):
    built_month: str  # "YYYY-MM"
    seq_in_month: int | None  # this serial's position among the vehicles built that month
    total_in_month: int | None
    seq_in_type: int | None  # position across all production of the type code
    total_in_type: int | None


class VinDecodeResult(ResultMeta):
    serial: str  # last 7 VIN characters: the only part sent to RealOEM
    status: Literal["found", "not_found"]
    confidence: Literal["normal", "low"]
    warnings: list[str]
    vehicle: VehicleRef | None = None
    product: Literal["car", "motorcycle"] | None = None
    catalog: Literal["current", "classic"] | None = None
    series_name: str | None = None  # RealOEM's series label, e.g. "3' E93 (2005 — 2010)"
    body: str | None = None  # e.g. "Convertible"; None for motorcycles
    engine: str | None = None  # e.g. "N52N"; None for motorcycles
    steering: str | None = None  # e.g. "Left hand drive"; only when RealOEM shows it
    transmission: str | None = None  # e.g. "Manual"; Classic-catalog cars only
    production: ProductionStats | None = None  # only with include_production
