"""F6 vehicle index tools: find_vehicle (local only) and update_vehicle_index (ARD section 5.11)."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import CallDeadline, InvalidInput, LayoutChanged, RealOemError
from realoem_mcp.gate import GATE_KEY
from realoem_mcp.http_client import Page
from realoem_mcp.models.vehicles import (
    IndexedVehicle,
    VehicleIndexPage,
    VehicleIndexUpdateResult,
    VehicleSearchResult,
)
from realoem_mcp.page_types import PageType
from realoem_mcp.parsers.vehicles import PAGE_SIZE, is_past_end, parse_vehicles
from realoem_mcp.services import Services
from realoem_mcp.vehicle_index import VehicleIndex, sort_key

INDEX_KEY = "vehicle_index"  # services.extras key
UPDATE_STATE_KEY = "vehicle_index_update"  # services.extras key (hosted server)
COOLDOWN = timedelta(hours=1)  # hosted server: at most one completed check per hour
MAX_PAGES_LIMIT = 10
MAX_LIMIT = 100
REBUILD_HINT = "The maintainer should rebuild the baseline with scripts/rebuild_vehicle_index.py."
NO_BASELINE = (
    "No vehicle index baseline is installed; the maintainer must run "
    "scripts/rebuild_vehicle_index.py."
)


def get_index(services: Services) -> VehicleIndex:
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands)
        services.extras[INDEX_KEY] = index
    return index


async def _fetch(services: Services, number: int) -> Page:
    """vehicles?page=<number>&sort=year, always from the network."""
    return await services.client.fetch(
        PageType.VEHICLES, "vehicles", {"page": str(number), "sort": "year"}, refresh=True
    )


def _parse(services: Services, page: Page) -> VehicleIndexPage:
    try:
        return parse_vehicles(page.html, url=page.url, brands=services.brands)
    except LayoutChanged:
        # Never keep an unparseable page cached.
        services.cache.shorten(page.url, timedelta(0), owner=page.owner)
        raise


async def fetch_vehicles_page(services: Services, number: int) -> tuple[VehicleIndexPage, Page]:
    """Fetch and parse vehicles?page=<number>&sort=year, always from the network."""
    page = await _fetch(services, number)
    return _parse(services, page), page


def search_index(
    services: Services,
    *,
    query: str | None,
    brand: str | None,
    series: str | None,
    year: int | None,
    market: str | None,
    type_code: str | None,
    include_unlinked: bool,
    limit: int,
) -> VehicleSearchResult:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"limit must be between 1 and {MAX_LIMIT}, got {limit}.")
    brand_ids = sorted(b.id for b in services.brands)
    if brand is not None and brand.lower() not in brand_ids:
        raise InvalidInput(f"Unknown brand {brand!r}; use one of: {', '.join(brand_ids)}.")
    index = get_index(services)
    total, vehicles = index.search(
        query=query,
        brand=brand,
        series=series,
        year=year,
        market=market,
        type_code=type_code,
        include_unlinked=include_unlinked,
        limit=limit,
    )
    return VehicleSearchResult(total_matches=total, vehicles=vehicles, index=index.meta())


def _result(pages: list[Page], **fields: Any) -> VehicleIndexUpdateResult:
    if pages:
        return VehicleIndexUpdateResult.from_pages(pages, pages_fetched=len(pages), **fields)
    return VehicleIndexUpdateResult(  # no request was made
        source_urls=[],
        fetched_at=datetime.now(UTC),
        from_cache=True,
        requests_made=0,
        pages_fetched=0,
        **fields,
    )


def _check_max_pages(max_pages: int) -> None:
    if not 1 <= max_pages <= MAX_PAGES_LIMIT:
        raise InvalidInput(f"max_pages must be between 1 and {MAX_PAGES_LIMIT}, got {max_pages}.")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _UpdateState:
    """Hosted server: the vehicle index is shared, so its updates are too."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    generation: int = 0  # number of updates that have finished
    last_result: VehicleIndexUpdateResult | None = None
    checked_at: datetime | None = None  # end of the last up_to_date/updated check


async def _acquire_within_deadline(services: Services, lock: asyncio.Lock) -> None:
    """Wait for the lock, but not past the tool call's deadline (read with the gate's clock)."""
    gate = services.extras.get(GATE_KEY)
    left = gate.time_left() if gate is not None else None
    if left is None:
        await lock.acquire()
        return
    if left <= 0:
        raise CallDeadline()
    try:
        async with asyncio.timeout(left):
            await lock.acquire()
    except TimeoutError:
        raise CallDeadline() from None


async def update_index_shared(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """update_index for the hosted server: one update at a time, and at most one completed
    check per hour for everyone.

    A caller that arrives while an update runs waits for it (within the call deadline) and gets
    its result, with requests_made 0: the requests were made, and charged, for the caller that
    ran the update. Only an up_to_date or updated result starts the cooldown, so a partial
    update can be continued. The cooldown lives in memory: a restart allows one more check.
    """
    _check_max_pages(max_pages)
    state = services.extras.setdefault(UPDATE_STATE_KEY, _UpdateState())
    seen = state.generation
    await _acquire_within_deadline(services, state.lock)
    try:
        if state.generation != seen and state.last_result is not None:  # the update waited for
            return state.last_result.model_copy(update={"requests_made": 0, "from_cache": True})
        if state.checked_at is not None and _now() - state.checked_at < COOLDOWN:
            index = get_index(services)
            return _result(
                [],
                status="cooldown",
                added=[],
                remote_total=index.last_remote_total() or 0,
                local_total=index.count(),
                message=f"The index was checked at {state.checked_at:%H:%M} UTC; it is refreshed "
                "at most once an hour.",
            )
        result = await update_index(services, max_pages)
        state.generation += 1
        state.last_result = result
        if result.status in ("up_to_date", "updated"):
            state.checked_at = _now()
        return result
    finally:
        state.lock.release()


async def update_index(services: Services, max_pages: int) -> VehicleIndexUpdateResult:
    """ARD section 5.11 update algorithm: probe one page, then scan back from the last page
    (or from where an interrupted scan stopped)."""
    _check_max_pages(max_pages)
    index = get_index(services)
    local_total = index.count()
    if index.meta().built_at is None or local_total == 0:
        return _result(
            [],
            status="drift",
            added=[],
            remote_total=0,
            local_total=local_total,
            message=NO_BASELINE,
        )
    known, resume = index.keys(), index.resume_point()
    max_start = resume[0] if resume else index.max_prod_start()
    parsed: dict[int, VehicleIndexPage] = {}
    pages: list[Page] = []
    new: dict[str, IndexedVehicle] = {}

    def keep(result: VehicleIndexPage, page: Page) -> VehicleIndexPage:
        parsed[result.page] = result  # keyed by the page RealOEM says it served
        pages.append(page)
        new.update((row.key, row) for row in result.rows if row.key not in known)
        return result

    # Probe where the index ends, but never past RealOEM's last known end.
    probe_total = min(local_total, index.last_remote_total() or local_total)
    probe_number = max(1, math.ceil(probe_total / PAGE_SIZE))
    probe_page = await _fetch(services, probe_number)
    if probe_number > 1 and is_past_end(probe_page.html):
        services.cache.shorten(probe_page.url, timedelta(0), owner=probe_page.owner)
        first, first_page = await fetch_vehicles_page(services, 1)
        index.record_check(remote_total=first.total, resume=None)
        return _result(
            [probe_page, first_page],
            status="drift",
            added=[],
            remote_total=first.total,
            local_total=local_total,
            message=f"RealOEM lists {first.total} vehicles, fewer than the {local_total} in the "
            f"index (vehicles were removed or merged). {REBUILD_HINT}",
        )
    probe = keep(_parse(services, probe_page), probe_page)
    remote_total = probe.total
    stopped_at: int | None = None  # next page to read when max_pages ran out
    if remote_total != local_total or new:
        number = min(resume[1], probe.last_page) if resume else probe.last_page
        while True:
            current = parsed.get(number)
            if current is None:
                if len(pages) >= max_pages:
                    stopped_at = number
                    break
                current = keep(*await fetch_vehicles_page(services, number))
            first_start = current.rows[0].production_from if current.rows else None
            older = first_start is None or (max_start is not None and first_start < max_start)
            if number <= 1 or older:
                break
            number -= 1
    added = sorted(new.values(), key=sort_key)
    index.add_local(added)
    expected = remote_total - local_total
    resume_point = None
    if remote_total == local_total and not added:
        status = "up_to_date"
        message = f"The vehicle index is up to date ({remote_total} vehicles on RealOEM)."
    elif len(added) == expected:
        status = "updated"
        message = f"Added {len(added)} new vehicle(s); the index now has all {remote_total}."
    elif len(added) < expected and stopped_at is not None:
        status = "partial"
        resume_point = (max_start, stopped_at)
        if added:
            message = (
                f"Added {len(added)} of {expected} new vehicles before reaching max_pages="
                f"{max_pages}. Call update_vehicle_index again to continue from page "
                f"{stopped_at}."
            )
        else:
            message = (
                f"No new vehicles in the {len(pages)} page(s) allowed by max_pages={max_pages}; "
                f"{expected} are still missing. Call update_vehicle_index again with a larger "
                f"max_pages (up to {MAX_PAGES_LIMIT}) to continue from page {stopped_at}."
            )
    else:
        status = "drift"
        message = (
            f"RealOEM lists {remote_total} vehicles and the index had {local_total}; "
            f"{len(added)} new vehicle(s) were added, but the difference is not explained by new "
            f"vehicles at the end of the list (vehicles were back-dated, removed or changed). "
            f"{REBUILD_HINT}"
        )
    index.record_check(remote_total=remote_total, resume=resume_point)
    return _result(
        pages,
        status=status,
        added=added,
        remote_total=remote_total,
        local_total=index.count(),
        message=message,
    )


def register(app: MCPServer, services: Services) -> None:
    @app.tool()
    async def find_vehicle(
        query: str | None = None,
        brand: str | None = None,
        series: str | None = None,
        year: int | None = None,
        market: str | None = None,
        type_code: str | None = None,
        include_unlinked: bool = False,
        limit: int = 25,
    ) -> VehicleSearchResult:
        """Find BMW, MINI, Rolls-Royce and BMW Motorrad vehicles in the local vehicle index.

        Use this first whenever the user names a vehicle ("2019 R 1250 GS", "E90 325i USA") to get
        vehicle ids for list_part_groups and the other catalog tools. Makes no request to RealOEM.
        query: words that must all appear (case-insensitive substrings) in the series label, series
        code, model name or type code. brand: bmw, mini, rolls-royce or motorrad. series (e.g. E90),
        market (e.g. USA) and type_code (e.g. VB13) match exactly, ignoring case. year: vehicles in
        production that year. include_unlinked: also return the few rows RealOEM lists without a
        vehicle id. limit: 1-100 vehicles (default 25).
        Returns total_matches, vehicles (vehicle id, series, model, type code, body, market,
        production_from/production_to as YYYY-MM) and index (built_at, baseline_total, local_rows,
        last_update_at). Vehicle ids carry the production START month; for a specific car's build
        month use select_vehicle or decode_vin. End dates of vehicles still in production are as
        of built_at. If nothing matches, call update_vehicle_index and search again.
        """
        try:
            return search_index(
                services,
                query=query,
                brand=brand,
                series=series,
                year=year,
                market=market,
                type_code=type_code,
                include_unlinked=include_unlinked,
                limit=limit,
            )
        except RealOemError as err:
            raise ToolError(err.message) from err

    @app.tool()
    async def update_vehicle_index(max_pages: int = 5) -> VehicleIndexUpdateResult:
        """Add vehicles RealOEM listed since the local vehicle index was built.

        Use when find_vehicle does not find a vehicle the user named, or when the user asks to
        update the vehicle list. Fetches RealOEM's vehicles index sorted by year: one request when
        nothing is new, otherwise pages from the end backwards: at most max_pages requests
        (1-10, default 5), plus one to read the total when the local index is larger than
        RealOEM's. Returns status (up_to_date; updated; partial = page limit reached, call again
        to continue where it stopped; drift = the maintainer should rebuild the baseline, also
        returned without any request when no baseline is installed), added (the new vehicles),
        remote_total, local_total, pages_fetched and message. Never downloads the whole index.
        On the hosted server the index is shared: status cooldown means it was checked less
        than an hour ago and nothing was fetched; search again with find_vehicle.
        """
        try:
            if services.settings.mode == "http":
                return await update_index_shared(services, max_pages)
            return await update_index(services, max_pages)
        except RealOemError as err:
            raise ToolError(err.message) from err
