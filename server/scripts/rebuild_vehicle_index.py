"""MAINTAINER ONLY: rebuild the committed vehicle index baseline from RealOEM (PRD F6.1, F6.6).

Fetches every page of /bmw/enUS/vehicles?sort=year (about 165 pages plus one re-check of the last
page, about 6 minutes at the normal 2-second rate limit) through RealOemClient, checks each page,
and writes brands/<brand>/vehicles.csv plus brands/vehicles.meta.toml. Never run this from a tool
or in CI; run it once per catalog release, after the project owner agreed to it.

Usage (from server/):
    uv run python scripts/rebuild_vehicle_index.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.models.vehicles import IndexedVehicle
from realoem_mcp.services import Services, create_services
from realoem_mcp.tools.vehicles import fetch_vehicles_page
from realoem_mcp.vehicle_index import write_baseline

MAX_ATTEMPTS = 3


class RebuildError(Exception):
    """The index could not be read consistently; nothing was written."""


class _IndexChanged(Exception):
    """RealOEM's index changed during the crawl (total or last page)."""


@dataclass(frozen=True)
class RebuildSummary:
    total: int
    pages: int
    requests: int
    attempts: int
    per_brand: dict[str, int]
    unlinked: int
    built_at: date

    def lines(self) -> list[str]:
        brands = ", ".join(f"{brand} {count}" for brand, count in sorted(self.per_brand.items()))
        return [
            f"vehicles: {self.total} ({self.unlinked} without a vehicle id)",
            f"pages: {self.pages}, requests: {self.requests}, attempts: {self.attempts}",
            f"per brand: {brands}",
            f"built_at: {self.built_at}",
        ]


async def crawl(services: Services) -> tuple[list[IndexedVehicle], int, int]:
    """All rows in sort=year order, the total and the number of pages; raises _IndexChanged."""
    rows: list[IndexedVehicle] = []
    last_keys: list[str] = []
    number, last_page, total = 1, 1, None
    while number <= last_page:
        page, _ = await fetch_vehicles_page(services, number)
        if page.page != number:
            raise RebuildError(f"asked for page {number} but RealOEM returned page {page.page}")
        if total is None:
            total, last_page = page.total, page.last_page
        elif page.total != total:
            raise _IndexChanged(f"total changed from {total} to {page.total} on page {number}")
        rows.extend(page.rows)
        last_keys = [row.key for row in page.rows]
        number += 1
    # Rows inserted or removed mid-crawl shift later pages; the last page shows it.
    check, _ = await fetch_vehicles_page(services, last_page)
    if check.total != total or [row.key for row in check.rows] != last_keys:
        raise _IndexChanged(f"page {last_page} changed during the crawl")
    if len(rows) != total:
        raise RebuildError(f"read {len(rows)} rows but RealOEM reports {total} vehicles")
    duplicates = sorted(key for key, n in Counter(row.key for row in rows).items() if n > 1)
    if duplicates:
        raise RebuildError(f"{len(duplicates)} duplicate row keys: {', '.join(duplicates)}")
    return rows, total, last_page


async def rebuild(
    settings: Settings,
    *,
    built_at: date,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> RebuildSummary:
    """Crawl, restarting when the index changes, then write the baseline into brands_dir."""
    services = create_services(settings, transport=transport, clock=clock, sleep=sleep)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                rows, total, pages = await crawl(services)
            except _IndexChanged as change:
                print(f"attempt {attempt}: {change}; restarting", file=sys.stderr)
                continue
            brand_ids = [brand.id for brand in services.brands]
            per_brand = write_baseline(
                settings.brands_dir, brand_ids, rows, total=total, built_at=built_at
            )
            return RebuildSummary(
                total=total,
                pages=pages,
                requests=services.client.requests_made,
                attempts=attempt,
                per_brand=per_brand,
                unlinked=sum(1 for row in rows if row.vehicle is None),
                built_at=built_at,
            )
        raise RebuildError(f"RealOEM's vehicles index kept changing ({max_attempts} attempts)")
    finally:
        await services.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MAINTAINER ONLY: rebuild brands/*/vehicles.csv from RealOEM (~166 requests)."
    )
    parser.parse_args(argv)
    settings = Settings.from_env()
    print(
        f"Fetching RealOEM's vehicles index into {settings.brands_dir} "
        f"({settings.min_interval_s:g} s between requests)...",
        file=sys.stderr,
    )
    try:
        summary = asyncio.run(rebuild(settings, built_at=datetime.now(UTC).date()))
    except (RealOemError, RebuildError) as err:
        print(f"rebuild failed, nothing written: {err}", file=sys.stderr)
        return 1
    for line in summary.lines():
        print(line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
