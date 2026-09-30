"""Catalog models (feature C, ARD section 5.11): cascade, main groups, diagrams, parts lists."""

from __future__ import annotations

from pydantic import BaseModel

from realoem_mcp.models.common import DiagramRef, ResultMeta, VehicleRef
from realoem_mcp.models.select import SelectOption


class VehicleSelectionResult(ResultMeta):
    selected: dict[str, SelectOption]  # level -> effective choice, auto-selected levels included
    next_level: str | None  # first level without a choice; None once complete
    options: list[SelectOption]  # choices for next_level ([] when complete)
    complete: bool
    vehicle: VehicleRef | None
    type_code: str | None
    summary: str | None  # "You Have Selected:" text, e.g. "3 Series E90 BMW 325i"


class VehicleSpecs(BaseModel):
    vehicle: VehicleRef  # built from the page's canonical vehicle id
    model_name: str | None  # e.g. "3 Series E90 325i"
    body: str | None  # e.g. "Sedan"; None for motorcycles ("N/A")
    engine: str | None
    steering: str | None  # e.g. "Left-hand drive"
    transmission: str | None  # only some vehicles (e.g. Rolls-Royce)


class MainGroup(BaseModel):
    mg: str  # two digits, e.g. "11"
    name: str  # e.g. "ENGINE"


class PartGroups(BaseModel):  # parser output of parsers/partgrp.py (main groups page)
    specs: VehicleSpecs
    main_groups: list[MainGroup]


class PartGroupsResult(ResultMeta, PartGroups):
    pass


class DiagramThumb(BaseModel):
    diagram: DiagramRef
    thumbnail_url: str


class Subgroup(BaseModel):
    code: str  # e.g. "10"
    name: str  # e.g. "Engine Housing"
    diagrams: list[DiagramThumb]


class DiagramListResult(ResultMeta):
    vehicle_id: str
    main_group: str
    subgroups: list[Subgroup]


class Hotspot(BaseModel):
    position: str  # matches PartRow.position, e.g. "01"
    x1: int
    y1: int
    x2: int
    y2: int  # display space: the same pixels as image_width x image_height


class OptionCode(BaseModel):
    code: str  # e.g. "S205A"
    value: str  # e.g. "Yes"


class Condition(BaseModel):
    text: str  # e.g. "For vehicles with Automatic transmission"
    option_codes: list[OptionCode]


class PartRow(BaseModel):
    position: str  # "01", or "--" for accessories without a callout
    description: str
    supplement: str | None
    qty: str | None
    valid_from: str | None  # "YYYY-MM"
    valid_to: str | None  # "YYYY-MM"
    part_number: str | None
    price_usd: float | None
    notes: str | None  # e.g. "+core"; see DiagramParts.notes_legend
    has_photo: bool
    indent: int  # 0-3, from the description cell's edge1..edge3 class
    conditions: list[Condition]


class DiagramParts(BaseModel):  # parser output of parsers/showparts.py
    diagram: DiagramRef
    image_url: str
    image_width: int
    image_height: int
    hotspots: list[Hotspot]
    rows: list[PartRow]
    notes_legend: dict[str, str]  # e.g. {"+core": "plus core charge (...)"}


class DiagramPartsResult(ResultMeta, DiagramParts):
    pass
