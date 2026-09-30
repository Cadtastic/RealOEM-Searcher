"""skills/part-lookup/SKILL.md: frontmatter and the rules the skill must state (ARD 5.12)."""

from tests.harness import REPO_ROOT

SKILL = REPO_ROOT / "skills" / "part-lookup" / "SKILL.md"


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
    assert fields["name"] == "part-lookup"
    description = fields["description"]
    assert len(description) <= 1024
    for trigger in (
        "part number",
        "MINI",
        "Rolls-Royce",
        "Motorrad",
        "fits",
        "current",
        "replaced",
    ):
        assert trigger in description


def test_body_routes_everything_through_lookup_part() -> None:
    _, body = _split()
    for required in ("lookup_part", "series", "superseded_by", "source_urls", "brand"):
        assert required in body
    assert "Never fetch realoem.com" in body
