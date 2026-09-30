"""skills/diagram-browse/SKILL.md: trigger-oriented frontmatter and the facts the PRD requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "diagram-browse" / "SKILL.md"


def _read() -> tuple[dict[str, str], str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    head, sep, body = text[4:].partition("\n---\n")
    assert sep, "frontmatter is not closed with ---"
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    return meta, body


def test_frontmatter_names_the_skill_and_its_triggers() -> None:
    meta, _ = _read()
    assert set(meta) == {"name", "description"}
    assert meta["name"] == "diagram-browse"
    for trigger in ("parts diagram", "parts groups", "production month"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_the_tool_chain() -> None:
    _, body = _read()
    for phrase in (
        "`decode_vin`",
        "`find_vehicle`",
        "`select_vehicle`",
        "`list_part_groups`",
        "`list_diagrams`",
        "`get_diagram_parts`",
        "every value from `selected`",
        "The parameter for the level `catalog` is `archive`",
        "auto-selected",
        "`YYYYMM00`",
    ):
        assert phrase in body, phrase


def test_body_lists_main_groups_as_named_by_realoem() -> None:
    _, body = _read()
    for row in (
        "| 11 | Engine |",
        "| 12 | Engine electrical system |",
        "| 13 | Fuel preparation system |",
        "| 17 | Radiator (cooling) |",
        "| 18 | Exhaust system |",
        "| 21 | Clutch |",
        "| 23 / 24 | Manual / automatic transmission |",
        "| 31 | Front axle |",
        "| 32 | Steering |",
        "| 33 | Rear axle |",
        "| 34 | Brakes |",
        "| 51 | Vehicle trim |",
        "| 61 | Vehicle electrical system |",
        "| 64 | Heater and air conditioning |",
    ):
        assert row in body, row


def test_body_explains_parts_lists_and_limits() -> None:
    _, body = _read()
    for phrase in (
        "Condition rows",
        "option code `S205A`",
        "production-date filtering",
        "nominal production date",
        "not date-filtered to a build month",
        "display space",
        "`image_width` x `image_height`",
        "`notes_legend`",
        "`--`",
        "Never fetch RealOEM pages directly",
        "`source_urls`",
    ):
        assert phrase in body, phrase
