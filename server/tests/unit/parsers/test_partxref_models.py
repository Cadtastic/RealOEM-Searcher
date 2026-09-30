"""partxref narrowed to one series (series=...): one row per type code x diagram."""

import pytest

from realoem_mcp.errors import LayoutChanged
from realoem_mcp.models.common import DiagramRef, VehicleRef
from realoem_mcp.models.parts import ModelUse, PartXref
from realoem_mcp.parsers.partxref import parse_partxref
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    services, _ = make_services({})
    return services


def _parse(services: Services, slug: str, q: str, series: str, html: str | None = None) -> PartXref:
    xref = parse_partxref(
        html if html is not None else load_fixture(f"partxref/{slug}.html"),
        url=url("partxref", q=q, series=series),
        brands=services.brands,
        client=services.client,
    )
    assert xref is not None
    return xref


async def test_e90_rows_carry_vehicle_body_engine_and_diagram(services: Services) -> None:
    xref = _parse(services, "oil_filter_11427953129_e90", "11427953129", "E90")
    assert xref.series == []
    assert len(xref.models) == 114
    assert len({m.vehicle.type_code for m in xref.models}) == 55
    assert {m.vehicle.brand for m in xref.models} == {"bmw"}
    assert {m.vehicle.series for m in xref.models} == {"E90"}
    assert {m.diagram.diag_id for m in xref.models} == {"02_0092", "11_3753", "11_3867", "11_3971"}
    vb13 = [m for m in xref.models if m.vehicle.type_code == "VB13"]
    assert vb13[1] == ModelUse(
        vehicle=VehicleRef(
            vehicle_id="VB13-USA-02_2004_E90_BMW_325i",
            type_code="VB13",
            market="USA",
            production_month="2004-02",  # nominal: series start, not a build month
            series="E90",
            brand="bmw",
            model="325i",
        ),
        body="Sedan",
        engine="N52",
        diagram=DiagramRef(
            vehicle_id="VB13-USA-02_2004_E90_BMW_325i",
            diag_id="11_3867",
            name="Lubrication system-Oil filter",
            url="https://www.realoem.com/bmw/enUS/showparts?id=VB13-USA-02_2004_E90_BMW_325i&diagId=11_3867",
        ),
    )


async def test_motorcycle_rows_have_no_body_or_engine(services: Services) -> None:
    xref = _parse(services, "motorrad_oil_filter_11427673541_k25", "11427673541", "K25")
    assert len(xref.models) == 12
    first = xref.models[0]
    assert first.vehicle == VehicleRef(
        vehicle_id="0307-EUR-12_2002_K25_BMW_R_1200_GS_04_0307,0317_",
        type_code="0307",
        market="EUR",
        production_month="2002-12",
        series="K25",
        brand="motorrad",
        model="R_1200_GS_04_0307,0317_",
    )
    assert (first.body, first.engine) == (None, None)  # "N/A" and blank on RealOEM
    assert first.diagram.url == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0307-EUR-12_2002_K25_BMW_R_1200_GS_04_0307%2C0317_&diagId=02_0112"
    )
    assert {m.vehicle.brand for m in xref.models} == {"motorrad"}


async def test_rolls_royce_rows_skip_the_transmission_field(services: Services) -> None:
    xref = _parse(services, "rr_oil_filter_11427583220_rr4", "11427583220", "RR4")
    assert len(xref.models) == 12
    assert {(m.vehicle.brand, m.body, m.engine) for m in xref.models} == {
        ("rolls-royce", "Sedan", "N74R")
    }
    assert {m.vehicle.model for m in xref.models} == {"Ghost", "Ghost_EWB"}
    assert xref.models[0].vehicle.vehicle_id == "FK41-EUR-08_2008_RR4_Rolls_Royce_Ghost"


async def test_mini_row_is_tagged_mini(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    old_text = "3 Series E90, 323i, Sedan, N52, EUR, (VB51) :"
    old_link = "id=VB51-EUR-08_2004_E90_BMW_323i&amp;diagId=02_0092"
    assert old_text in html and old_link in html
    html = html.replace(old_text, "MINI R56, Cooper S, Hatchback, N14, USA, (MF73) :", 1)
    html = html.replace(old_link, "id=MF73-USA-02_2008_R56_Mini_Cooper_S&amp;diagId=11_3910", 1)
    row = _parse(services, "", "11427953129", "E90", html=html).models[0]
    assert (row.vehicle.brand, row.vehicle.series, row.vehicle.model) == ("mini", "R56", "Cooper_S")
    assert (row.body, row.engine) == ("Hatchback", "N14")
    assert row.diagram.diag_id == "11_3910"


async def test_unrecognized_row_text_leaves_body_and_engine_empty(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    html = html.replace("3 Series E90, 323i, Sedan, N52, EUR, (VB51) :", "(VB51) :")
    xref = _parse(services, "", "11427953129", "E90", html=html)
    assert (xref.models[0].body, xref.models[0].engine) == (None, None)
    assert xref.models[0].vehicle.type_code == "VB51"  # the id is still parsed from the link


async def test_row_without_diagram_id_raises_layout_changed(services: Services) -> None:
    html = load_fixture("partxref/oil_filter_11427953129_e90.html")
    html = html.replace("&amp;diagId=02_0092#11427953129", "#11427953129", 1)
    with pytest.raises(LayoutChanged) as info:
        _parse(services, "", "11427953129", "E90", html=html)
    assert "unexpected vehicle link" in info.value.detail
