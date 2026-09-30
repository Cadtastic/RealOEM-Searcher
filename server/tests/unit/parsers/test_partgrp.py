import pytest

from realoem_mcp.models.catalog import PartGroups, Subgroup
from realoem_mcp.parsers.partgrp import (
    dedupe_repeated,
    parse_diagram_list,
    parse_part_groups,
    vehicle_brand,
)
from realoem_mcp.services import Services
from realoem_mcp.vehicle_ids import VehicleId
from tests.harness import MakeServices, load_fixture, url

pytestmark = pytest.mark.anyio

E90 = "VB13-USA-10-2005-E90-BMW-325i"
R56 = "MF73-USA-02-2008-R56-Mini-Cooper_S"
K50 = "0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_"


@pytest.fixture
async def services(make_services: MakeServices) -> Services:
    """Offline services: the parsers need its brand registry and client (no requests)."""
    return make_services({})[0]


def _groups(fixture: str, vehicle_id: str, services: Services) -> PartGroups:
    html = load_fixture(fixture)
    return parse_part_groups(html, url=url("partgrp", id=vehicle_id), brands=services.brands)


def _diagrams(
    fixture: str, vehicle_id: str, services: Services, *, dedupe: bool = False
) -> list[Subgroup]:
    return parse_diagram_list(
        load_fixture(fixture),
        url=url("partgrp", id=vehicle_id, mg="11"),
        client=services.client,
        vehicle_id=vehicle_id,
        dedupe_names=dedupe,
    )


async def test_bmw_specs_and_main_groups(services: Services) -> None:
    groups = _groups("common/partgrp_e90_325i.html", E90, services)
    assert groups.specs.model_dump() == {
        "vehicle": {
            "vehicle_id": E90,
            "type_code": "VB13",
            "market": "USA",
            "production_month": "2005-10",
            "series": "E90",
            "brand": "bmw",
            "model": "325i",
        },
        "model_name": "3 Series E90 325i",
        "body": "Sedan",
        "engine": "N52",
        "steering": "Left-hand drive",
        "transmission": None,
    }
    names = {group.mg: group.name for group in groups.main_groups}
    assert len(groups.main_groups) == 39
    assert (groups.main_groups[0].mg, groups.main_groups[-1].mg) == ("01", "91")
    assert {mg: names[mg] for mg in ("11", "12", "13", "17", "18", "21", "23", "24")} == {
        "11": "ENGINE",
        "12": "ENGINE ELECTRICAL SYSTEM",
        "13": "FUEL PREPARATION SYSTEM",
        "17": "RADIATOR",
        "18": "EXHAUST SYSTEM",
        "21": "CLUTCH",
        "23": "MANUAL TRANSMISSION",
        "24": "AUTOMATIC TRANSMISSION",
    }
    assert {mg: names[mg] for mg in ("31", "32", "33", "34", "51", "61", "64")} == {
        "31": "FRONT AXLE",
        "32": "STEERING",
        "33": "REAR AXLE",
        "34": "BRAKES",
        "51": "VEHICLE TRIM",
        "61": "VEHICLE ELECTRICAL SYSTEM",
        "64": "HEATER AND AIR CONDITIONING",
    }
    assert names["88"] == "VALUE PARTS&PACKAGES SERVICE AND REPAIR"


async def test_vehicle_id_comes_from_the_canonical_link(services: Services) -> None:
    garbage = "VB13-USA-03-2006-XXX-YYY-ZZZ"
    groups = _groups("partgrp/e90_325i_garbage_suffix.html", garbage, services)
    vehicle = groups.specs.vehicle
    assert vehicle.vehicle_id == "VB13-USA-03-2006-E90-BMW-325i"
    assert (vehicle.production_month, vehicle.series, vehicle.model) == ("2006-03", "E90", "325i")


async def test_mini_specs(services: Services) -> None:
    groups = _groups("partgrp/r56_cooper_s.html", R56, services)
    assert groups.specs.vehicle.brand == "mini"
    assert groups.specs.vehicle.model == "Cooper_S"
    assert (groups.specs.model_name, groups.specs.body, groups.specs.engine) == (
        "MINI R56 Cooper S",
        "3 doors",
        "N14",
    )
    assert len(groups.main_groups) == 35


async def test_rolls_royce_has_transmission_and_bespoke_group(services: Services) -> None:
    groups = _groups("partgrp/rr4_ghost.html", "FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", services)
    assert groups.specs.vehicle.brand == "rolls-royce"
    assert groups.specs.model_name == "Rolls-Royce Ghost RR4 Ghost"
    assert groups.specs.transmission == "Automatic"
    assert groups.main_groups[-1].model_dump() == {"mg": "92", "name": "BESPOKE"}
    assert len(groups.main_groups) == 33


async def test_motorcycle_has_no_body_engine_or_steering(services: Services) -> None:
    groups = _groups("partgrp/k50_r1250gs.html", K50, services)
    assert groups.specs.model_dump() == {
        "vehicle": {
            "vehicle_id": K50,
            "type_code": "0J93",
            "market": "USA",
            "production_month": "2019-05",
            "series": "K50",
            "brand": "motorrad",
            "model": "R_1250_GS_19_0J91,_0J93_",
        },
        "model_name": "K50 (R 1200 GS, R 1250 GS) R 1250 GS 19 (0J91, 0J93)",
        "body": None,
        "engine": None,
        "steering": None,
        "transmission": None,
    }
    names = {group.mg: group.name for group in groups.main_groups}
    assert (names["13"], names["17"], names["77"]) == (
        "FUEL SYSTEM",
        "COOLING",
        "OPTIONAL EQUIPMENT+ACCESSORIES, MOTORRAD",
    )


async def test_bmw_diagram_list(services: Services) -> None:
    subgroups = _diagrams("partgrp/e90_325i_mg11.html", E90, services)
    assert [(s.code, s.name, len(s.diagrams)) for s in subgroups] == [
        ("05", "Engine", 1),
        ("10", "Engine Housing", 5),
        ("15", "Cylinder Head", 5),
        ("18", "Belt Drive", 2),
        ("20", "Crankshaft Drive", 5),
        ("25", "Valve Train", 4),
        ("30", "Lubrication System", 3),
        ("35", "Engine Cooling", 2),
        ("40", "Intake Manifold", 2),
        ("45", "Vacuum Control", 1),
        ("88", "Inspection Kits", 1),
    ]
    housing = subgroups[1].diagrams
    assert [(d.diagram.diag_id, d.diagram.name) for d in housing] == [
        ("11_3731", "ENGINE BLOCK"),
        ("11_3732", "ENGINE BLOCK MOUNTING PARTS"),
        ("11_3733", "OIL PAN"),
        ("11_3742", "CYLINDER CRANKCASE/HELI-COIL INSERT"),
        ("11_3834", "OIL PAN"),
    ]
    assert housing[2].model_dump() == {
        "diagram": {
            "vehicle_id": E90,
            "diag_id": "11_3733",
            "name": "OIL PAN",
            "url": url("showparts", id=E90, diagId="11_3733"),
        },
        "thumbnail_url": "https://www.realoem.com/bmw/images/thumb_2zas.jpg",
    }


async def test_mini_diagram_list(services: Services) -> None:
    subgroups = _diagrams("partgrp/r56_cooper_s_mg11.html", R56, services)
    assert len(subgroups) == 12
    assert sum(len(s.diagrams) for s in subgroups) == 31
    assert subgroups[1].diagrams[2].diagram.model_dump() == {
        "vehicle_id": R56,
        "diag_id": "11_3910",
        "name": "OIL PAN/OIL LEVEL INDICATOR",
        "url": url("showparts", id=R56, diagId="11_3910"),
    }


async def test_motorcycle_diagram_list_dedupes_doubled_names(services: Services) -> None:
    subgroups = _diagrams("partgrp/k50_r1250gs_mg11.html", K50, services, dedupe=True)
    assert len(subgroups) == 17
    assert (subgroups[0].code, subgroups[0].name) == ("05", "Engine / Running Gear")
    assert [d.diagram.name for d in subgroups[0].diagrams] == [
        "ENGINE",
        "SHORT ENGINE / CYLINDER WITH PISTONS",
        "ENGINE",
    ]
    oil_filter = subgroups[13]
    assert (oil_filter.code, oil_filter.name) == ("42", "Oil Filter And Lines")
    assert oil_filter.diagrams[0].diagram.url == url("showparts", id=K50, diagId="11_3820")


async def test_motorcycle_names_stay_doubled_without_dedupe(services: Services) -> None:
    subgroups = _diagrams("partgrp/k50_r1250gs_mg11.html", K50, services)
    assert subgroups[0].name == "Engine / Running Gear Engine / Running Gear"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Engine / Running Gear Engine / Running Gear", "Engine / Running Gear"),
        ("ENGINE ENGINE", "ENGINE"),
        ("Engine Housing", "Engine Housing"),
        ("OIL PAN", "OIL PAN"),
        ("", ""),
    ],
)
def test_dedupe_repeated(name: str, expected: str) -> None:
    assert dedupe_repeated(name) == expected


@pytest.mark.parametrize(
    ("vehicle_id", "brand"),
    [
        (E90, "bmw"),
        (R56, "mini"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", "rolls-royce"),
        (K50, "motorrad"),
        ("VB13-USA-02_2004_E90_BMW_325i", "bmw"),
    ],
)
async def test_vehicle_brand(services: Services, vehicle_id: str, brand: str) -> None:
    vid = VehicleId.parse(vehicle_id, brand_segments=services.brands.brand_segments())
    assert vehicle_brand(services.brands, vid).id == brand
