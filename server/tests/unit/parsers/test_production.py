import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.parsers.common import tree
from realoem_mcp.parsers.production import parse_production
from tests.harness import load_fixture, url

BMW = load_fixture("production/vin_bmw_e93_px22770.html")
MINI = load_fixture("production/vin_mini_r53_td86476.html")


def _parse(html: str, serial: str = "PX22770") -> dict[str, ProductionStats]:
    return parse_production(html, url=url("production", vin=serial))


def test_bmw_match() -> None:
    assert _parse(BMW) == {
        "WL13": ProductionStats(
            built_month="2008-07",
            seq_in_month=321,
            total_in_month=547,
            seq_in_type=12557,
            total_in_type=17781,
        )
    }


def test_mini_match() -> None:
    assert _parse(MINI, "TD86476") == {
        "RE33": ProductionStats(
            built_month="2004-04",
            seq_in_month=228,
            total_in_month=1392,
            seq_in_type=36422,
            total_in_type=82906,
        )
    }


def test_motorcycle_match_without_engine() -> None:
    # Captured with the v1 UI; the production markup is the same in both variants.
    html = load_fixture("production/vin_moto_r1200gs_z656595.html")
    assert _parse(html, "Z656595") == {
        "0A61": ProductionStats(
            built_month="2017-09",
            seq_in_month=73,
            total_in_month=246,
            seq_in_type=1896,
            total_in_type=3207,
        )
    }


def test_no_record_is_an_empty_dict() -> None:
    assert _parse(load_fixture("production/vin_miss_zzzzzzz.html"), "ZZZZZZZ") == {}


def test_several_matches_keep_page_order() -> None:
    mini_match = tree(MINI).css_first(".ps-vin-match").html
    html = BMW.replace('<div class="ps-vin-match">', mini_match + '<div class="ps-vin-match">', 1)
    assert list(_parse(html)) == ["RE33", "WL13"]


def test_two_records_for_one_type_code_raise_layout_changed() -> None:
    bmw_match = tree(BMW).css_first(".ps-vin-match").html
    html = BMW.replace('<div class="ps-vin-match">', bmw_match + '<div class="ps-vin-match">', 1)
    with pytest.raises(LayoutChanged) as info:
        _parse(html)
    assert info.value.detail == "type WL13 has more than one production record"


def test_missing_counts_become_none() -> None:
    html = BMW.replace("built that month", "made that month").replace("across all", "in all")
    stats = _parse(html)["WL13"]
    assert stats.built_month == "2008-07"
    assert (stats.seq_in_month, stats.total_in_month) == (None, None)
    assert (stats.seq_in_type, stats.total_in_type) == (None, None)


@pytest.mark.parametrize(
    ("html", "detail"),
    [
        (load_fixture("select/vin_miss_zzzzzzz.html"), "missing '#ps-vin-result'"),
        (
            BMW.replace('class="ps-vin-match"', 'class="ps-vin-other"'),
            "#ps-vin-result has neither a match nor an error",
        ),
        (
            BMW.replace("type WL13,", "code WL13,"),
            "no type or build month in '— code WL13, USA, engine N52N — built July 2008'",
        ),
        (
            BMW.replace("July&nbsp;2008", "Juli&nbsp;2008"),
            "no type or build month in '— type WL13, USA, engine N52N — built Juli 2008'",
        ),
    ],
    ids=["no-result-block", "no-match", "no-type", "unknown-month"],
)
def test_broken_page_raises_layout_changed(html: str, detail: str) -> None:
    with pytest.raises(LayoutChanged) as info:
        _parse(html)
    assert info.value.page_type == "production"
    assert info.value.detail == detail
