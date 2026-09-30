"""skills/fitment/SKILL.md: trigger-oriented frontmatter and the rules the skill must state."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "fitment" / "SKILL.md"


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
    assert meta["name"] == "fitment"
    for trigger in ("fit", "part number", "my car", "compare", "share"):
        assert trigger in meta["description"], trigger
    assert len(meta["description"]) <= 1024


def test_body_explains_the_tool_chain_and_limits() -> None:
    _, body = _read()
    body = " ".join(body.split())  # phrases may wrap across lines
    for phrase in (
        "`decode_vin`",
        "`select_vehicle`",
        "`check_fitment`",
        "`used_part_numbers` differs from `query`",
        "resolved a supersession",
        "`lookup_part`",
        "undated",
        "`compare_vehicles`",
        "Never compare whole vehicles",
        "`list_diagrams`",
        "`ignored_diag_ids_a`",
        "`qty_a` / `qty_b`",
        "`max_requests`",
        "`complete` is false",
        "`unfetched_a` / `unfetched_b`",
        "continues from the cache",
        "`source_urls`",
        "Never fetch RealOEM pages directly",
    ):
        assert phrase in body, phrase
