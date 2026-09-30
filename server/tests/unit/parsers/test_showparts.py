import pytest

from realoem_mcp.models.catalog import DiagramParts
from realoem_mcp.parsers.showparts import parse_showparts
from realoem_mcp.services import Services
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
AUTOMATIC = {
    "text": "For vehicles with Automatic transmission",
    "option_codes": [{"code": "S205A", "value": "Yes"}],
}
ATTENTION = {
    "text": "Attention! Aluminum screws may only be used once. "
    "For additional information, refer to the repair manual!",
    "option_codes": [],
}


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    return make_services({})[0]


def _parse(fixture: str, vehicle_id: str, diag_id: str, services: Services) -> DiagramParts:
    return parse_showparts(
        load_fixture(f"showparts/{fixture}.html"),
        url=url("showparts", id=vehicle_id, diagId=diag_id),
        client=services.client,
        vehicle_id=vehicle_id,
        diag_id=diag_id,
    )


def _row(position: str, description: str, part_number: str, **fields: object) -> dict:
    """A PartRow dump with the E90 oil pan defaults (qty 1, indent 2, no dates or extras)."""
    row = {
        "position": position,
        "description": description,
        "supplement": None,
        "qty": "1",
        "valid_from": None,
        "valid_to": None,
        "part_number": part_number,
        "price_usd": None,
        "notes": None,
        "has_photo": False,
        "indent": 2,
        "conditions": [],
    }
    return row | fields


E90_OIL_PAN_ROWS = [
    _row("01", "Oil Pan", "11137552414", price_usd=551.84, notes="+core", conditions=[AUTOMATIC]),
    _row(
        "--",
        "Loctite 5970 liquid sealant",
        "83190404517",
        supplement="50ML",
        price_usd=23.4,
        conditions=[{"text": "Required for repair", "option_codes": []}, ATTENTION],
    ),
    _row("02", "Screw plug", "11137535106", supplement="M12X16", price_usd=3.68),
    _row(
        "03",
        "Gasket ring",
        "07119963151",
        supplement="A12X17-CU",
        price_usd=0.57,
        has_photo=True,
    ),
    _row("04", "Profile-gasket", "11137548031", price_usd=47.4),
    _row(
        "--",
        "Set of aluminium screws oil pan",
        "11132210959",
        conditions=[{"text": "only in conjunction with", "option_codes": []}, ATTENTION],
    ),
    _row(
        "05",
        "Set of aluminium screws oil pan",
        "11132210959",
        indent=3,
        conditions=[
            {
                "text": "For vehicles with Automatic transmission " + ATTENTION["text"],
                "option_codes": [{"code": "S205A", "value": "Yes"}],
            }
        ],
    ),
    _row("06", "Oilreturnpipe", "11437527133", price_usd=10.46, conditions=[AUTOMATIC]),
    _row("07", "O-ring", "11427548322", supplement="17X3", price_usd=2.42),
    _row("08", "Oil levelling sensor", "12617607910", has_photo=True),
    _row("09", "Gasket ring", "12611744292", price_usd=6.42, has_photo=True),
    _row(
        "10",
        "Hex nut with plate",
        "07119905544",
        supplement="M6-8-ZNNIV SI",
        qty="3",
        valid_to="2006-04",
        price_usd=0.64,
        has_photo=True,
    ),
    _row("11", "Protection cap", "11137543122", price_usd=2.17, indent=3),
]
OIL_PAN_HOTSPOTS = [
    ("01", 78, 255, 87, 271),
    ("02", 85, 70, 94, 87),
    ("02", 123, 232, 131, 249),
    ("03", 86, 95, 95, 111),
    ("03", 123, 278, 131, 294),
    ("04", 257, 44, 266, 61),
    ("05", 242, 391, 251, 407),
    ("06", 555, 227, 564, 243),
    ("07", 486, 226, 495, 243),
    ("08", 448, 336, 457, 352),
    ("09", 420, 314, 429, 331),
    ("10", 437, 420, 455, 437),
    ("11", 313, 23, 331, 39),
]


def _hotspots(parts: DiagramParts) -> list[tuple[str, int, int, int, int]]:
    return [(h.position, h.x1, h.y1, h.x2, h.y2) for h in parts.hotspots]


async def test_bmw_oil_pan_every_field(services: Services) -> None:
    parts = _parse("e90_325i_11_3733", E90, "11_3733", services)
    assert parts.diagram.model_dump() == {
        "vehicle_id": E90,
        "diag_id": "11_3733",
        "name": "Oil Pan",
        "url": url("showparts", id=E90, diagId="11_3733"),
    }
    assert parts.image_url == "https://www.realoem.com/bmw/images/diag_2zas.jpg"
    assert (parts.image_width, parts.image_height) == (640, 448)
    assert _hotspots(parts) == OIL_PAN_HOTSPOTS
    assert [row.model_dump() for row in parts.rows] == E90_OIL_PAN_ROWS
    assert parts.notes_legend == {
        "+core": "plus core charge (possibility of a return of the old part)"
    }


async def test_later_production_month_drops_rows_that_ended(services: Services) -> None:
    vehicle_id = "VB13-USA-08-2006-E90-BMW-325i"
    parts = _parse("e90_325i_200608_11_3733", vehicle_id, "11_3733", services)
    assert [row.model_dump() for row in parts.rows] == [
        row for row in E90_OIL_PAN_ROWS if row["position"] != "10"
    ]
    assert parts.diagram.vehicle_id == vehicle_id
    assert _hotspots(parts) == OIL_PAN_HOTSPOTS  # the image still marks position 10


async def test_eur_market_vehicle_gets_the_same_table(services: Services) -> None:
    vehicle_id = "VB11-EUR-10-2005-E90-BMW-325i"
    parts = _parse("e90_325i_eur_11_3733", vehicle_id, "11_3733", services)
    assert [row.model_dump() for row in parts.rows] == E90_OIL_PAN_ROWS
    assert parts.diagram.url == url("showparts", id=vehicle_id, diagId="11_3733")
    assert parts.rows[0].price_usd == 551.84  # prices are USD for every market


async def test_mini_rows_without_edge_classes_have_indent_zero(services: Services) -> None:
    vehicle_id = "MF73-USA-02-2008-R56-Mini-Cooper_S"
    parts = _parse("r56_cooper_s_11_3910", vehicle_id, "11_3910", services)
    assert parts.diagram.name == "Oil pan/oil level indicator"
    assert parts.image_url == "https://www.realoem.com/bmw/images/diag_6q63.jpg"
    assert [(r.position, r.part_number, r.indent) for r in parts.rows] == [
        ("01", "11137550483", 1),
        ("--", "83190404517", 3),
        ("02", "11137585928", 0),
        ("03", "11137546275", 0),
        ("03", "12617546239", 0),
        ("04", "11437585970", 0),
        ("05", "11437560212", 0),
        ("06", "11437586030", 0),
        ("07", "11437560211", 0),
        ("08", "11317542856", 0),
        ("09", "11137578545", 0),
        ("10", "83190404517", 3),
    ]
    assert [c.text for c in parts.rows[1].conditions] == ["Required for repair"]
    assert [c.text for c in parts.rows[-1].conditions] == ["See PuMA measure 50752218"]
    assert (parts.rows[3].valid_to, parts.rows[4].valid_to) == ("2023-09", None)
    assert parts.notes_legend == {}


async def test_motorcycle_german_supplements_and_missing_prices(services: Services) -> None:
    vehicle_id = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"
    parts = _parse("k50_r1250gs_11_5146", vehicle_id, "11_5146", services)
    assert parts.diagram.name == "Screw connection, engine housing"
    assert [(r.description, r.supplement, r.price_usd) for r in parts.rows[:3]] == [
        ("Crankcase", "SILBER", None),
        ("Crankcase", "SCHWARZ", None),
        ("ISA screw", "M6X30-8.8-ZNNIV", None),
    ]
    assert len(parts.rows) == 11
    assert {row.indent for row in parts.rows} == {0}
    assert parts.rows[3].price_usd == 16.92


async def test_xref_style_vehicle_id_is_kept_as_given(services: Services) -> None:
    vehicle_id = "VB13-USA-02_2004_E90_BMW_325i"  # as in lookup_part model rows
    parts = _parse("e90_325i_xref_id_11_3867", vehicle_id, "11_3867", services)
    assert parts.diagram.model_dump() == {
        "vehicle_id": vehicle_id,
        "diag_id": "11_3867",
        "name": "Lubrication system-Oil filter",
        "url": url("showparts", id=vehicle_id, diagId="11_3867"),
    }
    assert parts.rows[2].model_dump() == _row(
        "03", "Set oil-filter element", "11427953129", indent=0
    )
