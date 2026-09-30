"""parse_select raises LayoutChanged instead of guessing (NFR3). Broken pages are real fixtures
with one structural edit each."""

import re

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.parsers.select import parse_select
from tests.harness import load_fixture, url

URL = url("select", vin="PX22770")
HIT = load_fixture("select/vin_bmw_e93_px22770.html")


def _layout_error(html: str) -> LayoutChanged:
    with pytest.raises(LayoutChanged) as info:
        parse_select(html, url=URL)
    assert info.value.page_type == "select"
    assert info.value.url == URL
    return info.value


def test_v1_markup_is_rejected() -> None:
    error = _layout_error(load_fixture("select/vin_bmw_e93_px22770_v1.html"))
    assert error.detail == "no v2 list boxes ([data-ro-level]) in #selectForm"


def test_page_without_select_form() -> None:
    error = _layout_error(load_fixture("common/partgrp_e90_325i.html"))
    assert error.detail == "missing '#selectForm'"


def test_page_without_result_block() -> None:
    error = _layout_error(HIT.replace('id="selectResults"', 'id="somethingElse"'))
    assert error.detail == "missing '#selectResults'"


def test_unknown_level() -> None:
    error = _layout_error(HIT.replace('data-ro-level="engine"', 'data-ro-level="colour"'))
    assert error.detail == "unknown cascade level 'colour'"


def test_comment_between_caption_and_list_box_is_ignored() -> None:
    html = HIT.replace(
        '<div class="ro-lb-label">Engine:</div>',
        '<div class="ro-lb-label">Engine:</div><!-- list box -->',
    )
    assert parse_select(html, url=URL).level("engine").label == "Engine"


def test_level_without_caption() -> None:
    error = _layout_error(HIT.replace('<div class="ro-lb-label">Engine:</div>', ""))
    assert error.detail == "no .ro-lb-label before level 'engine'"


def test_row_link_without_the_level_parameter() -> None:
    error = _layout_error(HIT.replace("&amp;engine=", "&amp;motor="))
    assert error.detail == "row in level 'engine' has no engine= in its link"


@pytest.mark.parametrize("value", ["2008-07", "20081300", "20080000"])
def test_prod_value_that_is_not_yyyymm00(value: str) -> None:
    error = _layout_error(HIT.replace("prod=20080700", f"prod={value}"))
    assert error.detail == f"prod value {value!r} is not YYYYMM00"


def test_level_without_rows() -> None:
    html = re.sub(r"<li><a [^>]*&amp;engine=[^>]*>[^<]*</a></li>", "", HIT)
    error = _layout_error(html)
    assert error.detail == "level 'engine' has no rows"


def test_level_with_two_selected_rows() -> None:
    html = HIT.replace(
        '<a class="ro-lb-row" href="/bmw/enUS/select?archive=0&amp;product=M">',
        '<a class="ro-lb-row is-selected" href="/bmw/enUS/select?archive=0&amp;product=M">',
    )
    error = _layout_error(html)
    assert error.detail == "level 'product' has more than one selected row"


def test_result_form_without_type_code() -> None:
    html = HIT.replace(
        '<span class="searchResults-label">Type Code:</span>',
        '<span class="searchResults-label">Code:</span>',
    )
    error = _layout_error(html)
    assert error.detail == "#selectResults has a form but no vehicle id or type code"
