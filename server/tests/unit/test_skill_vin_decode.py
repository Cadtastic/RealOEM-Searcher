"""skills/vin-decode/SKILL.md: trigger-oriented frontmatter and the facts the PRD requires."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "vin-decode" / "SKILL.md"


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
    assert meta["name"] == "vin-decode"
    for trigger in ("VIN", "decode my VIN", "what car is this VIN", "last 7"):
        assert trigger in meta["description"]
    assert len(meta["description"]) <= 1024


def test_body_explains_tool_use_limits_and_next_steps() -> None:
    _, body = _read()
    for phrase in (
        "`decode_vin`",
        "`include_production=true`",
        "without `include_production`",
        "underscores as spaces",
        "RealOEM's best match",
        "`confidence` is `low`",
        "option codes",
        "paint",
        "upholstery",
        "`list_part_groups`",
        "`check_fitment`",
        "`vehicle.vehicle_id`",
        "Never fetch RealOEM pages directly",
    ):
        assert phrase in body, phrase
