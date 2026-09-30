import pytest

from realoem_mcp.errors import InvalidInput
from realoem_mcp.vehicle_ids import DEFAULT_BRAND_SEGMENTS, VehicleId


def test_dash_form() -> None:
    vid = VehicleId.parse("VB13-USA-10-2005-E90-BMW-325i")
    assert vid == VehicleId(
        raw="VB13-USA-10-2005-E90-BMW-325i",
        type_code="VB13",
        market="USA",
        month="10",
        year="2005",
        series="E90",
        brand_segment="BMW",
        model="325i",
    )
    assert vid.production_month == "2005-10"
    assert str(vid) == "VB13-USA-10-2005-E90-BMW-325i"


def test_xref_underscore_form() -> None:
    vid = VehicleId.parse("VB13-USA-02_2004_E90_BMW_325i")
    assert (vid.type_code, vid.market, vid.production_month) == ("VB13", "USA", "2004-02")
    assert (vid.series, vid.brand_segment, vid.model) == ("E90", "BMW", "325i")


def test_empty_date_form() -> None:
    vid = VehicleId.parse("VB13-USA---E90-BMW-325i")
    assert (vid.type_code, vid.market, vid.production_month) == ("VB13", "USA", None)
    assert (vid.series, vid.brand_segment, vid.model) == ("E90", "BMW", "325i")


@pytest.mark.parametrize(
    ("raw", "series", "brand_segment", "model"),
    [
        ("MF73-USA-02-2008-R56-Mini-Cooper_S", "R56", "Mini", "Cooper_S"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", "RR4", "Rolls_Royce", "Ghost"),
        ("FK41-EUR-06_2010_RR4_Rolls_Royce_Ghost", "RR4", "Rolls_Royce", "Ghost"),
        ("XXXX-CHN-01-2016-M13-Zinoro-60H", "M13", "Zinoro", "60H"),
        (
            "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_",
            "K50",
            "BMW",
            "R_1250_GS_19_0J91,_0J93_",
        ),
    ],
)
def test_brand_variants_use_longest_brand_segment(
    raw: str, series: str, brand_segment: str, model: str
) -> None:
    vid = VehicleId.parse(raw)
    assert (vid.series, vid.brand_segment, vid.model) == (series, brand_segment, model)


def test_percent_decoded_once_and_trimmed() -> None:
    vid = VehicleId.parse("  0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_ ")
    assert vid.raw == "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    assert VehicleId.parse("A-B-01-2000-X-BMW-100%2541").model == "100%41"


def test_unknown_brand_segment_keeps_series_and_date() -> None:
    vid = VehicleId.parse("AB12-USA-01-2020-G20-Isetta-X")
    assert (vid.series, vid.brand_segment, vid.model, vid.production_month) == (
        "G20",
        None,
        None,
        "2020-01",
    )
    assert VehicleId.parse("AB12-USA-01-2020-G20-Isetta-X", brand_segments=["Isetta"]).model == (
        "X"
    )


def test_unknown_shape_parses_only_type_code_and_market() -> None:
    vid = VehicleId.parse("VB13-USA")
    assert vid == VehicleId(raw="VB13-USA", type_code="VB13", market="USA")
    assert VehicleId.parse("VB13") == VehicleId(raw="VB13", type_code="VB13", market="")


def test_empty_id_is_invalid_input() -> None:
    with pytest.raises(InvalidInput):
        VehicleId.parse("   ")


def test_default_brand_segments() -> None:
    assert DEFAULT_BRAND_SEGMENTS == ("Rolls_Royce", "Zinoro", "Mini", "BMW")
