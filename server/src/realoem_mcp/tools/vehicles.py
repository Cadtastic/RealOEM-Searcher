"""F6 vehicle index tools: find_vehicle (local only) and update_vehicle_index (ARD section 5.11)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from realoem_mcp.errors import InvalidInput, RealOemError
from realoem_mcp.models.vehicles import VehicleSearchResult
from realoem_mcp.services import Services
from realoem_mcp.vehicle_index import VehicleIndex

INDEX_KEY = "vehicle_index"  # services.extras key
MAX_LIMIT = 100


def get_index(services: Services) -> VehicleIndex:
    """The process-wide VehicleIndex, opened on first use (Services.aclose closes it)."""
    index = services.extras.get(INDEX_KEY)
    if index is None:
        index = VehicleIndex.open(services.settings, services.brands)
        services.extras[INDEX_KEY] = index
    return index


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
