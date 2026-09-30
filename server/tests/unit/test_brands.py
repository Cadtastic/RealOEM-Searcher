import copy
import dataclasses
import pickle
from pathlib import Path

import pytest

from realoem_mcp import vehicle_ids
from realoem_mcp.brands import Brand, BrandRegistry
from realoem_mcp.vehicle_ids import VehicleId
from tests.harness import BRANDS_DIR


@pytest.fixture(scope="module")
def registry() -> BrandRegistry:
    return BrandRegistry.load(BRANDS_DIR)


def test_loads_all_four_brands_in_priority_order(registry: BrandRegistry) -> None:
    assert [(b.id, b.priority) for b in registry] == [
        ("mini", 10),
        ("rolls-royce", 20),
        ("motorrad", 30),
        ("bmw", 100),
    ]


def test_brand_toml_values(registry: BrandRegistry) -> None:
    mini = registry.get("mini")
    assert mini == Brand(
        id="mini",
        display_name="MINI",
        product="P",
        id_brand_segments=("Mini",),
        series_patterns=(r"^R5\d$", r"^R6\d$", r"^F5[4-7]$", r"^F60$", r"^J0\d$", r"^U25$"),
        label_keywords=("MINI",),
        wmi=("WMW", "WMZ"),
        notes="Classic catalog (archive=1) holds R50/R52/R53.",
        dedupe_repeated_names=False,
        priority=10,
    )
    assert registry.get("motorrad").product == "M"
    assert registry.get("motorrad").dedupe_repeated_names is True
    assert registry.get("rolls-royce").id_brand_segments == ("Rolls_Royce",)
    assert registry.get("bmw").wmi == (
        "WBA",
        "WBS",
        "WBY",
        "WBX",
        "5UX",
        "5UM",
        "5YM",
        "4US",
        "3MW",
        "LBV",
    )


def test_brands_are_hashable(registry: BrandRegistry) -> None:
    assert hash(registry.get("bmw")) == hash(registry.get("bmw"))
    assert len(set(registry)) == 4


def test_brand_segments(registry: BrandRegistry) -> None:
    assert set(registry.brand_segments()) == {"Mini", "Rolls_Royce", "BMW", "Zinoro"}


@pytest.mark.parametrize(
    ("code", "label", "product", "expected"),
    [
        ("R56", None, None, "mini"),
        ("F56", None, None, "mini"),
        ("RR4", None, None, "rolls-royce"),
        ("R21N", None, None, "rolls-royce"),
        ("K50", None, None, "motorrad"),
        ("KR1", None, None, "motorrad"),
        ("T24", None, None, "motorrad"),
        ("E90", None, None, "bmw"),
        ("E90N", None, "P", "bmw"),
        ("K25", "BMW K25 (R 1200 GS)", "M", "motorrad"),
        ("XYZ", "BMW MINI R56", None, "mini"),
        ("R11N", "BMW Phantom R11N", None, "rolls-royce"),
        ("K12", None, "P", "bmw"),
        ("ZZZ", None, "M", "motorrad"),
    ],
)
def test_for_series(
    registry: BrandRegistry, code: str, label: str | None, product: str | None, expected: str
) -> None:
    assert registry.for_series(code, label=label, product=product).id == expected


@pytest.mark.parametrize(
    ("raw", "product", "expected"),
    [
        ("MF73-USA-02-2008-R56-Mini-Cooper_S", None, "mini"),
        ("FK43-USA-06-2010-RR4-Rolls_Royce-Ghost", None, "rolls-royce"),
        ("VB13-USA-10-2005-E90-BMW-325i", None, "bmw"),
        ("XXXX-CHN-01-2016-M13-Zinoro-60H", None, "bmw"),
        ("0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", None, "motorrad"),
        ("0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_", "M", "motorrad"),
        ("VB13-USA-10-2005-E90-BMW-325i", "P", "bmw"),
        ("VB13-USA", None, "bmw"),
    ],
)
def test_for_vehicle_id(
    registry: BrandRegistry, raw: str, product: str | None, expected: str
) -> None:
    vid = VehicleId.parse(raw, brand_segments=registry.brand_segments())
    assert registry.for_vehicle_id(vid, product=product).id == expected


def test_for_wmi(registry: BrandRegistry) -> None:
    assert registry.for_wmi("WBA").id == "bmw"
    assert registry.for_wmi("LBV").id == "bmw"
    assert registry.for_wmi("wmw").id == "mini"
    assert registry.for_wmi("SCA1234").id == "rolls-royce"
    assert registry.for_wmi("WB1").id == "motorrad"
    assert registry.for_wmi("1FT") is None


def test_unknown_keys_go_to_extra(tmp_path: Path) -> None:
    path = tmp_path / "zinoro" / "brand.toml"
    path.parent.mkdir()
    path.write_text(
        'id = "zinoro"\ndisplay_name = "Zinoro"\nproduct = "P"\nlogo = "z.png"\n',
        encoding="utf-8",
    )
    brand = Brand.from_toml(path)
    assert brand.extra == {"logo": "z.png"}
    assert (brand.series_patterns, brand.dedupe_repeated_names, brand.priority) == ((), False, 100)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('display_name = "X"\nproduct = "P"\n', "missing required key 'id'"),
        ('id = "x"\ndisplay_name = "X"\nproduct = "Q"\n', "product must be 'P' or 'M'"),
        ('id = "other"\ndisplay_name = "X"\nproduct = "P"\n', "must match its directory"),
    ],
)
def test_invalid_brand_files(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "brand.toml").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        BrandRegistry.load(tmp_path)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BrandRegistry.load(tmp_path)


_BASE = 'id = "x"\ndisplay_name = "X"\nproduct = "P"\n'


def _write_brand(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "x" / "brand.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(_BASE + extra, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ('id_brand_segments = "BMW"', "id_brand_segments"),
        ("series_patterns = [1, 2]", "series_patterns"),
        ('label_keywords = ["ok", 3]', "label_keywords"),
        ('wmi = { a = "b" }', "wmi"),
        ('dedupe_repeated_names = "yes"', "dedupe_repeated_names"),
        ("dedupe_repeated_names = 1", "dedupe_repeated_names"),
        ('priority = "10"', "priority"),
        ("priority = 1.5", "priority"),
        ("priority = true", "priority"),
    ],
)
def test_wrong_value_types_name_the_file_and_key(tmp_path: Path, line: str, key: str) -> None:
    path = _write_brand(tmp_path, line + "\n")
    with pytest.raises(ValueError, match=key) as info:
        Brand.from_toml(path)
    assert str(path) in str(info.value)


def test_invalid_series_pattern_names_file_and_pattern(tmp_path: Path) -> None:
    path = _write_brand(tmp_path, 'series_patterns = ["^ok$", "([unclosed"]\n')
    with pytest.raises(ValueError, match=r"series_patterns.*\(\[unclosed") as info:
        Brand.from_toml(path)
    assert str(path) in str(info.value)


def test_brand_stays_hashable_copyable_and_serializable(tmp_path: Path) -> None:
    path = _write_brand(tmp_path, 'logo = "x.png"\n')
    brand = Brand.from_toml(path)
    assert brand.extra == {"logo": "x.png"}
    assert hash(brand) == hash(Brand.from_toml(path))
    assert dataclasses.asdict(brand)["extra"] == {"logo": "x.png"}
    assert copy.deepcopy(brand) == brand
    assert pickle.loads(pickle.dumps(brand)) == brand
    assert pickle.loads(pickle.dumps(brand)).extra == {"logo": "x.png"}


def test_directly_constructed_brand_validates_series_patterns() -> None:
    with pytest.raises(ValueError, match=r"series_patterns.*\(\[unclosed"):
        Brand(id="x", display_name="X", product="P", series_patterns=("([unclosed",))
    assert Brand(
        id="x", display_name="X", product="P", series_patterns=(r"^E\d+$",)
    ).matches_series("E90")


def test_load_requires_the_fallback_brands(tmp_path: Path) -> None:
    for brand_id in ("bmw", "mini"):
        path = tmp_path / brand_id / "brand.toml"
        path.parent.mkdir()
        path.write_text(f'id = "{brand_id}"\ndisplay_name = "X"\nproduct = "P"\n')
    with pytest.raises(ValueError, match="motorrad"):
        BrandRegistry.load(tmp_path)


def test_default_brand_segments_match_the_shipped_brands(registry: BrandRegistry) -> None:
    assert set(vehicle_ids.DEFAULT_BRAND_SEGMENTS) == set(registry.brand_segments())
