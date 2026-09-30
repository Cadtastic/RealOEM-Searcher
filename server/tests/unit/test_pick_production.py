from realoem_mcp.models.vin import ProductionStats
from realoem_mcp.tools.vin import pick_production

WL13 = ProductionStats(
    built_month="2008-07", seq_in_month=321, total_in_month=547, seq_in_type=1, total_in_type=2
)
RE33 = ProductionStats(
    built_month="2004-04", seq_in_month=228, total_in_month=1392, seq_in_type=3, total_in_type=4
)


def test_single_record_for_the_decoded_type() -> None:
    assert pick_production({"WL13": WL13}, "PX22770", "WL13") == (WL13, [])


def test_no_record() -> None:
    assert pick_production({}, "PX22770", "WL13") == (
        None,
        ["RealOEM has no production record for serial PX22770."],
    )


def test_record_for_another_type_is_left_out() -> None:
    assert pick_production({"RE33": RE33}, "PX22770", "WL13") == (
        None,
        [
            "RealOEM's production record for serial PX22770 is for type RE33, not the decoded "
            "type WL13; build statistics were left out."
        ],
    )


def test_records_for_other_types_only_are_left_out() -> None:
    assert pick_production({"RE33": RE33, "RE31": RE33}, "PX22770", "WL13") == (
        None,
        [
            "RealOEM's production records for serial PX22770 are for types RE33, RE31, not the "
            "decoded type WL13; build statistics were left out."
        ],
    )


def test_several_records_pick_the_decoded_type_and_warn() -> None:
    assert pick_production({"RE33": RE33, "WL13": WL13}, "PX22770", "WL13") == (
        WL13,
        [
            "RealOEM's production records list 2 vehicles for serial PX22770 (types RE33, WL13); "
            "the decoded vehicle may not be the right one."
        ],
    )
