from datetime import UTC, datetime

from realoem_mcp.http_client import Page
from realoem_mcp.models.vin import ProductionStats, VinDecodeResult
from realoem_mcp.page_types import PageType
from tests.harness import url

SELECT_URL = url("select", vin="ZZZZZZZ")


def _page() -> Page:
    return Page(
        page_type=PageType.SELECT,
        url=SELECT_URL,
        final_url=SELECT_URL,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
        from_cache=False,
    )


def test_not_found_result_only_needs_the_status_fields() -> None:
    result = VinDecodeResult.from_pages(
        [_page()], serial="ZZZZZZZ", status="not_found", confidence="normal", warnings=[]
    )
    assert result.model_dump() == {
        "source_urls": [SELECT_URL],
        "fetched_at": datetime(2026, 9, 30, tzinfo=UTC),
        "from_cache": False,
        "requests_made": 1,
        "serial": "ZZZZZZZ",
        "status": "not_found",
        "confidence": "normal",
        "warnings": [],
        "vehicle": None,
        "product": None,
        "catalog": None,
        "series_name": None,
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
        "production": None,
    }


def test_production_stats_fields() -> None:
    stats = ProductionStats(
        built_month="2008-07",
        seq_in_month=321,
        total_in_month=547,
        seq_in_type=None,
        total_in_type=None,
    )
    assert stats.model_dump() == {
        "built_month": "2008-07",
        "seq_in_month": 321,
        "total_in_month": 547,
        "seq_in_type": None,
        "total_in_type": None,
    }
