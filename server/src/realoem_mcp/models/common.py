"""Shared result models (ARD section 5.10). Build VehicleRef/DiagramRef only via these helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel

if TYPE_CHECKING:
    from realoem_mcp.http_client import Page, RealOemClient
    from realoem_mcp.vehicle_ids import VehicleId


class ResultMeta(BaseModel):
    source_urls: list[str]
    fetched_at: datetime  # oldest fetched_at among pages used (UTC)
    from_cache: bool  # True only if every page came from cache
    requests_made: int  # pages this call fetched from the network

    @classmethod
    def from_pages(cls, pages: Sequence[Page], **fields: Any) -> Self:
        if not pages:
            raise ValueError("from_pages needs at least one page")
        return cls(
            source_urls=list(dict.fromkeys(page.url for page in pages)),
            fetched_at=min(page.fetched_at for page in pages),
            from_cache=all(page.from_cache for page in pages),
            requests_made=sum(1 for page in pages if not page.from_cache),
            **fields,
        )


class VehicleRef(BaseModel):
    vehicle_id: str
    type_code: str
    market: str
    production_month: str | None  # "YYYY-MM"
    series: str | None
    brand: str  # brand registry id: bmw | mini | rolls-royce | motorrad
    model: str | None

    @classmethod
    def from_id(cls, vid: VehicleId, brand: str) -> VehicleRef:
        return cls(
            vehicle_id=vid.raw,
            type_code=vid.type_code,
            market=vid.market,
            production_month=vid.production_month,
            series=vid.series,
            brand=brand,
            model=vid.model,
        )


class DiagramRef(BaseModel):
    vehicle_id: str
    diag_id: str  # "{mg}_{nnnn}"
    name: str
    url: str

    @classmethod
    def build(cls, client: RealOemClient, vehicle_id: str, diag_id: str, name: str) -> DiagramRef:
        url = client.build_url("showparts", {"id": vehicle_id, "diagId": diag_id})
        return cls(vehicle_id=vehicle_id, diag_id=diag_id, name=name, url=url)
