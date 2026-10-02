"""skills/vehicle-index/SKILL.md: trigger-oriented frontmatter and the facts PRD F6.5 requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "vehicle-index" / "SKILL.md"


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
    assert meta["name"] == "vehicle-index"
    for trigger in ("2019 R 1250 GS", "E90 325i", "type code", "vehicle id", "update the vehicle"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_the_workflow_and_its_limits() -> None:
    _, body = _read()
    text = " ".join(body.split())  # line breaks in the Markdown do not matter
    for phrase in (
        "Call `find_vehicle` first",
        "call `update_vehicle_index`, then call `find_vehicle` again",
        "It continues where the previous call stopped",
        "no vehicle index baseline is installed",
        "https://www.realoem.com/bmw/enUS/partgrp?id=<url-encoded vehicle_id>",
        "`up_to_date`",
        "`updated`",
        "`partial`",
        "`drift`",
        "`cooldown`",
        "production START month",
        '"as of `built_at`"',
        "`select_vehicle`",
        "`decode_vin`",
        "`list_part_groups(vehicle_id)`",
        "Never fetch RealOEM pages directly",
    ):
        assert phrase in text, phrase
