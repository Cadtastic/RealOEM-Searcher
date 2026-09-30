"""skills/supersession/SKILL.md: frontmatter and the rules the skill must state (ARD 5.12)."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "supersession" / "SKILL.md"


def _split() -> tuple[dict[str, str], str]:
    lines = SKILL.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", "SKILL.md must start with YAML frontmatter"
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, "\n".join(lines[end + 1 :])


def test_frontmatter_names_the_skill_and_its_triggers() -> None:
    fields, _ = _split()
    assert set(fields) == {"name", "description"}
    assert fields["name"] == "supersession"
    description = fields["description"]
    assert len(description) <= 1024
    for trigger in ("part number", "current", "superseded", "replaced", "history"):
        assert trigger in description


def test_body_explains_statuses_and_rules() -> None:
    _, body = _split()
    for required in (
        "trace_supersession",
        "current_part_number",
        "complete",
        "warnings",
        "loop detected",
        "no_successor",
        "ambiguous",
        "alternatives",
        "history",
        "source_urls",
        "Exchangeable retrospectively",
        "also fits",
        "short-lived",
        "Motorsport",
        "page title",
    ):
        assert required in body, required
    assert "Never fetch realoem.com" in body
