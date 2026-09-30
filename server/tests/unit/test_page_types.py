from datetime import timedelta

import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.page_types import PageType


def test_values_are_path_strings() -> None:
    assert [p.value for p in PageType] == [
        "select",
        "production",
        "partgrp",
        "showparts",
        "partxref",
        "partsearch",
        "part",
        "vehicles",
    ]


@pytest.mark.parametrize(
    ("page_type", "days"),
    [
        (PageType.SELECT, 30),
        (PageType.PRODUCTION, 180),
        (PageType.PARTGRP, 30),
        (PageType.SHOWPARTS, 30),
        (PageType.PARTXREF, 7),
        (PageType.PARTSEARCH, 7),
        (PageType.PART, 7),
        (PageType.VEHICLES, 1),
    ],
)
def test_default_ttls(page_type: PageType, days: int) -> None:
    assert page_type.ttl == timedelta(days=days)


def test_parse_accepts_values_and_rejects_others() -> None:
    assert PageType.parse("partxref") is PageType.PARTXREF
    with pytest.raises(InvalidInput, match="use one of: select, production"):
        PageType.parse("vin")


@pytest.mark.parametrize("value", [" PartXref ", "PARTXREF", "\tpartxref\n"])
def test_parse_tolerates_case_and_whitespace(value: str) -> None:
    assert PageType.parse(value) is PageType.PARTXREF


def test_parse_error_text_for_invalid_value_is_unchanged() -> None:
    with pytest.raises(InvalidInput) as info:
        PageType.parse(" Vin ")
    assert info.value.message.startswith(
        "Unknown page type ' Vin '; use one of: select, production"
    )
