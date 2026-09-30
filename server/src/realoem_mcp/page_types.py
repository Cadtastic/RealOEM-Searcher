"""RealOEM page types. Values are the URL path segments; each type has a default cache TTL."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from realoem_mcp.errors import InvalidInput


class PageType(StrEnum):
    SELECT = "select"
    PRODUCTION = "production"
    PARTGRP = "partgrp"
    SHOWPARTS = "showparts"
    PARTXREF = "partxref"
    PARTSEARCH = "partsearch"
    PART = "part"
    VEHICLES = "vehicles"

    @property
    def ttl(self) -> timedelta:
        return DEFAULT_TTLS[self]

    @classmethod
    def parse(cls, value: str) -> PageType:
        try:
            return cls(value.strip().lower() if isinstance(value, str) else value)
        except ValueError:
            allowed = ", ".join(member.value for member in cls)
            raise InvalidInput(f"Unknown page type {value!r}; use one of: {allowed}.") from None


DEFAULT_TTLS: dict[PageType, timedelta] = {
    PageType.SELECT: timedelta(days=30),
    PageType.PRODUCTION: timedelta(days=180),
    PageType.PARTGRP: timedelta(days=30),
    PageType.SHOWPARTS: timedelta(days=30),
    PageType.PARTXREF: timedelta(days=7),
    PageType.PARTSEARCH: timedelta(days=7),
    PageType.PART: timedelta(days=7),
    PageType.VEHICLES: timedelta(days=1),
}
