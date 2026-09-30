"""Part lookup models (ARD section 5.11, feature A). PartXref is the partxref parser output."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef


class SupersessionEntry(BaseModel):
    part_number: str
    description: str | None
    valid_from: date | None
    valid_to: date | None  # None = open-ended
    remark: str | None  # e.g. "Exchangeable retrospectively"
    in_catalog: bool  # link was part?... (True) or partxref?q= (False)


class SeriesUse(BaseModel):
    code: str  # series= code from the link, e.g. "E90N"
    name: str  # label without the "BMW " prefix and dates, e.g. "3 Series E90 LCI"
    brand: str  # brand registry id
    production_from: str | None  # "YYYY-MM"
    production_to: str | None  # "YYYY-MM"


class ModelUse(BaseModel):
    vehicle: VehicleRef  # id from the link; its date is the series start, not a build month
    body: str | None
    engine: str | None
    diagram: DiagramRef


class PartXref(BaseModel):
    part_number: str
    description: str | None
    supplier_ref: str | None
    weight_kg: float | None
    valid_from: date | None
    valid_to: date | None
    ended: bool  # RealOEM marks the "To" date "(ENDED)"
    superseded_by: list[SupersessionEntry]
    supersedes: list[SupersessionEntry]
    series: list[SeriesUse]  # plain lookup
    models: list[ModelUse]  # lookup narrowed to one series


class PartLookupResult(ResultMeta):
    query: str  # normalized input
    status: Literal["current", "ended", "not_found"]
    part: PartXref | None  # None when not_found
