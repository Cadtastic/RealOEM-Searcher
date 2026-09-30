import re

import pytest

from realoem_mcp.models.select import SelectOption, SelectPage
from realoem_mcp.parsers.select import parse_select
from tests.harness import load_fixture, url


def _parse(slug: str, **params: str) -> SelectPage:
    return parse_select(load_fixture(f"select/{slug}.html"), url=url("select", **params))


def _selected(page: SelectPage) -> dict[str, tuple[str, str]]:
    """{level: (value, label)} for every level with a selected row."""
    return {
        level.level: (level.selected_option.value, level.selected_option.label)
        for level in page.levels
        if level.selected_option is not None
    }


def test_vin_hit_bmw_e93_every_level_selected() -> None:
    page = _parse("vin_bmw_e93_px22770", vin="PX22770")
    assert page.vehicle_id == "WL13-USA-07-2008-E93-BMW-328i"
    assert page.type_code == "WL13"
    assert page.summary == "3 Series E93 BMW 328i"
    assert [level.level for level in page.levels] == [
        "product",
        "catalog",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
    ]
    assert [level.label for level in page.levels] == [
        "Product",
        "Catalog",
        "Series",
        "Body",
        "Model",
        "Market",
        "Prod Month",
        "Engine",
    ]
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("0", "Current"),
        "series": ("E93", "3' E93 (2005 — 2010)"),
        "body": ("Cab", "Convertible"),
        "model": ("328i", "328i"),
        "market": ("USA", "USA"),
        "prod": ("20080700", "07/2008"),
        "engine": ("N52N", "N52N"),
    }


def test_vin_hit_keeps_every_option_of_every_level() -> None:
    page = _parse("vin_bmw_e93_px22770", vin="PX22770")
    assert page.level("product").options == [
        SelectOption(value="P", label="Car", selected=True),
        SelectOption(value="M", label="Motorcycle", selected=False),
    ]
    series = page.level("series").options
    assert len(series) == 243
    assert series[0] == SelectOption(value="E81", label="1' E81 (2006 — 2011)", selected=False)
    assert [option.value for option in page.level("engine").options] == ["N51", "N52N"]
    prod = page.level("prod").options
    assert len(prod) == 47  # year group headers (li.ro-lb-group) are not options
    assert (prod[0].value, prod[0].label) == ("20050900", "09/2005")
    assert (prod[-1].value, prod[-1].label) == ("20100200", "02/2010")


def test_vin_hit_mini_classic_catalog() -> None:
    page = _parse("vin_mini_r53_td86476", vin="TD86476")
    assert page.vehicle_id == "RE33-USA-04-2004-R53-Mini-Cooper_S"
    assert page.type_code == "RE33"
    assert page.summary == "MINI R53 Mini Cooper S"
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("R53", "MINI R53"),
        "body": ("HC", "3 doors"),
        "model": ("Cooper S", "Cooper S"),
        "market": ("USA", "USA"),
        "prod": ("20040400", "04/2004"),
        "engine": ("W11", "W11"),
    }


def test_vin_hit_rolls_royce() -> None:
    page = _parse("vin_rr_ghost_ux52589", vin="UX52589")
    assert page.vehicle_id == "FK43-USA-12-2013-RR4-Rolls_Royce-Ghost"
    assert page.type_code == "FK43"
    assert page.summary == "Rolls-Royce Ghost RR4 Rolls-Royce Ghost"
    assert _selected(page)["series"] == ("RR4", "Rolls-Royce Ghost RR4")
    assert _selected(page)["engine"] == ("N74R", "N74R")
    assert len(page.level("prod").options) == 129


def test_vin_hit_motorcycle_has_no_body_or_engine_level() -> None:
    page = _parse("vin_moto_r1200gs_z656595", vin="Z656595")
    assert page.vehicle_id == "0A61-USA-09-2017-K50-BMW-R_1200_GS_17_0A51,_0A61_"
    assert page.type_code == "0A61"
    assert page.summary == "K50 (R 1200 GS, R 1250 GS) BMW R 1200 GS 17 (0A51, 0A61)"
    assert page.level("body") is None
    assert page.level("engine") is None
    assert _selected(page) == {
        "product": ("M", "Motorcycle"),
        "catalog": ("0", "Current"),
        "series": ("K50", "K50 (R 1200 GS, R 1250 GS) (2011 — 2023)"),
        "model": ("R 1200 GS 17 (0A51, 0A61)", "R 1200 GS 17 (0A51, 0A61)"),
        "market": ("USA", "USA"),
        "prod": ("20170900", "09/2017"),
    }


def test_vin_hit_classic_e30_adds_steering_and_transmission() -> None:
    page = _parse("vin_e30_classic_1234567", vin="1234567")
    assert page.vehicle_id == "1251-EUR-11-1986-E30-BMW-325e"
    assert page.type_code == "1251"
    assert [level.level for level in page.levels][-2:] == ["steering", "trans"]
    assert page.level("trans").label == "Transmission"
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("E30", "3' E30 (1981 — 1994)"),
        "body": ("2-T", "Coupe"),
        "model": ("325e", "325e"),
        "market": ("EUR", "EUR"),
        "prod": ("19861100", "11/1986"),
        "engine": ("M20", "M20"),
        "steering": ("L", "Left hand drive"),
        "trans": ("M", "Manual"),
    }
    assert page.level("trans").options == [
        SelectOption(value="M", label="Manual", selected=True),
        SelectOption(value="A", label="Automatic", selected=False),
    ]


def test_vin_miss_has_no_vehicle() -> None:
    page = _parse("vin_miss_zzzzzzz", vin="ZZZZZZZ")
    assert (page.vehicle_id, page.type_code, page.summary) == (None, None, None)
    assert [level.level for level in page.levels] == ["product", "catalog", "series"]
    assert page.selected("series") is None


def test_cascade_series_selected_body_auto_selected_model_open() -> None:
    page = _parse("cascade_e90", product="P", archive="0", series="E90")
    assert page.vehicle_id is None
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("0", "Current"),
        "series": ("E90", "3' E90 (2004 — 2023)"),
        "body": ("Lim", "Sedan"),
    }
    models = page.level("model").options
    assert len(models) == 20
    assert (models[0].value, models[-1].value) == ("316i", "M3")
    assert not any(option.selected for option in models)


def test_cascade_market_auto_selected_prod_list_grouped_by_year() -> None:
    page = _parse(
        "cascade_e90_325i", product="P", archive="0", series="E90", body="Lim", model="325i"
    )
    assert _selected(page)["market"] == ("USA", "USA")
    assert [option.value for option in page.level("market").options] == [
        "CHN",
        "EUR",
        "IDN",
        "IND",
        "MYS",
        "RUS",
        "THA",
        "USA",
    ]
    prod = page.level("prod")
    assert prod.selected_option is None
    assert len(prod.options) == 27
    assert (prod.options[0].value, prod.options[0].label) == ("20040200", "02/2004")
    assert (prod.options[-1].value, prod.options[-1].label) == ("20060800", "08/2006")
    assert page.level("engine") is None


def test_cascade_eur_offers_steering() -> None:
    page = _parse(
        "cascade_e90_325i_eur_200510",
        product="P",
        archive="0",
        series="E90",
        body="Lim",
        model="325i",
        market="EUR",
        prod="20051000",
    )
    assert page.vehicle_id is None
    assert _selected(page)["engine"] == ("N52", "N52")
    assert page.level("steering").options == [
        SelectOption(value="L", label="Left hand drive", selected=False),
        SelectOption(value="R", label="Right hand drive", selected=False),
    ]


def test_cascade_motorcycle_model_values_keep_spaces_and_commas() -> None:
    page = _parse(
        "cascade_k50_r1250gs",
        product="M",
        archive="0",
        series="K50",
        model="R 1250 GS 19 (0J91, 0J93)",
    )
    assert [level.level for level in page.levels] == [
        "product",
        "catalog",
        "series",
        "model",
        "market",
        "prod",
    ]
    assert _selected(page)["model"] == ("R 1250 GS 19 (0J91, 0J93)", "R 1250 GS 19 (0J91, 0J93)")
    assert len(page.level("model").options) == 13
    assert page.level("prod").selected_option is None
    assert len(page.level("prod").options) == 26


def test_cascade_classic_series_offers_five_bodies() -> None:
    page = _parse("cascade_classic_e46", product="P", archive="1", series="E46")
    assert _selected(page) == {
        "product": ("P", "Car"),
        "catalog": ("1", "Classic"),
        "series": ("E46", "3' E46 (1997 — 2023)"),
    }
    assert [(o.value, o.label) for o in page.level("body").options] == [
        ("Lim", "Sedan"),
        ("Cab", "Convertible"),
        ("Cou", "Coupe"),
        ("com", "Compact"),
        ("tou", "Touring"),
    ]
    assert page.level("series").options[0] == SelectOption(
        value="ISE", label="Isetta (1955 — 1962)", selected=False
    )


@pytest.mark.parametrize(
    "slug",
    ["vin_bmw_e93_px22770", "cascade_e90_325i_eur_200510", "cascade_k50_r1250gs"],
)
def test_every_prod_option_is_a_yyyymm00_code(slug: str) -> None:
    prod = _parse(slug).level("prod")
    assert all(re.fullmatch(r"(19|20)\d{2}(0[1-9]|1[0-2])00", o.value) for o in prod.options)
