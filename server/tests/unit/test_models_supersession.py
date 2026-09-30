from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from realoem_mcp.http_client import Page
from realoem_mcp.models.common import ResultMeta
from realoem_mcp.models.parts import SupersessionEntry
from realoem_mcp.models.supersession import SupersessionHop, SupersessionResult
from realoem_mcp.page_types import PageType

BASE = "https://www.realoem.com/bmw/enUS/partxref?q="


def _page(q: str, *, from_cache: bool, day: int) -> Page:
    return Page(
        page_type=PageType.PARTXREF,
        url=BASE + q,
        final_url=BASE + q,
        status=200,
        html="",
        fetched_at=datetime(2026, 9, day, 12, 0, tzinfo=UTC),
        from_cache=from_cache,
    )


def _fields() -> dict[str, object]:
    return {
        "query": "11427541827",
        "status": "replaced",
        "current_part_number": "11427953129",
        "chain": [
            SupersessionHop(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
            ),
            SupersessionHop(
                part_number="11427953129",
                description="Set oil-filter element",
                valid_from=date(2017, 6, 1),
                valid_to=None,
                remark="Exchangeable retrospectively",
            ),
        ],
        "alternatives": [],
        "history": [
            SupersessionEntry(
                part_number="11427541827",
                description="Set oil-filter element",
                valid_from=date(2004, 9, 1),
                valid_to=date(2006, 3, 17),
                remark=None,
                in_catalog=False,
            )
        ],
        "complete": True,
        "warnings": [],
    }


def test_result_extends_result_meta_with_the_ard_fields() -> None:
    assert issubclass(SupersessionResult, ResultMeta)
    assert list(SupersessionResult.model_fields) == [
        "source_urls",
        "fetched_at",
        "from_cache",
        "requests_made",
        "query",
        "status",
        "current_part_number",
        "chain",
        "alternatives",
        "history",
        "complete",
        "warnings",
    ]
    assert list(SupersessionHop.model_fields) == [
        "part_number",
        "description",
        "valid_from",
        "valid_to",
        "remark",
    ]


def test_from_pages_covers_every_page_of_the_chain() -> None:
    pages = [
        _page("11427541827", from_cache=True, day=28),
        _page("11427953129", from_cache=False, day=30),
    ]
    result = SupersessionResult.from_pages(pages, **_fields())
    data = result.model_dump(mode="json")
    assert data["source_urls"] == [BASE + "11427541827", BASE + "11427953129"]
    assert data["fetched_at"] == "2026-09-28T12:00:00Z"
    assert (data["from_cache"], data["requests_made"]) == (False, 1)
    assert data["chain"][1] == {
        "part_number": "11427953129",
        "description": "Set oil-filter element",
        "valid_from": "2017-06-01",
        "valid_to": None,
        "remark": "Exchangeable retrospectively",
    }
    assert data["history"][0]["in_catalog"] is False
    assert (data["complete"], data["warnings"]) == (True, [])


@pytest.mark.parametrize(
    "status", ["current", "replaced", "no_successor", "ambiguous", "not_found"]
)
def test_status_accepts_the_five_ard_values(status: str) -> None:
    pages = [_page("11427541827", from_cache=False, day=30)]
    assert SupersessionResult.from_pages(pages, **{**_fields(), "status": status}).status == status


def test_status_rejects_lookup_part_statuses() -> None:
    pages = [_page("11427541827", from_cache=False, day=30)]
    with pytest.raises(ValidationError):
        SupersessionResult.from_pages(pages, **{**_fields(), "status": "ended"})
