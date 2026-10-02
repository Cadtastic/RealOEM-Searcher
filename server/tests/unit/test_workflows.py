"""The deploy and uptime workflows (hosted design 4.10).

Checked line by line: no YAML parser is a dependency, and GitHub validates the syntax when a
workflow runs.
"""

import re

from tests.harness import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _lines(name: str) -> list[str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_a_tag_deploys_after_the_offline_tests() -> None:
    lines = _lines("deploy.yml")
    assert 'tags: ["v*"]' in lines
    for step in ("run: uv run ruff check", "run: uv run ruff format --check"):
        assert step in lines
    assert 'run: uv run pytest -m "not live"' in lines
    assert "needs: test" in lines and "environment: production" in lines
    assert "run: flyctl deploy --remote-only --ha=false" in lines
    assert "FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}" in lines
    setup = next(line for line in lines if "setup-flyctl@" in line)
    assert len(setup.split("@")[1].split()[0]) == 40  # pinned to a commit
    assert any(re.fullmatch(r"version: \d+\.\d+\.\d+", line) for line in lines)  # and flyctl
    # Only a pushed v* tag deploys: no other trigger, and no branch filter.
    assert lines[lines.index("on:") + 1 : lines.index("permissions:")] == ["push:", 'tags: ["v*"]']


def test_an_uptime_check_watches_the_health_endpoint() -> None:
    lines = _lines("uptime.yml")
    assert '- cron: "*/15 * * * *"' in lines
    assert "https://realoem-searcher.fly.dev/healthz" in lines
