"""Plugin manifests, pyproject and __version__ stay consistent (ARD sections 5.1 and 7)."""

import json
import tomllib

from realoem_mcp import __version__
from tests.harness import REPO_ROOT

PLUGIN = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MARKETPLACE = json.loads(
    (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
)
PYPROJECT = tomllib.loads((REPO_ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8"))


def test_versions_are_equal_everywhere() -> None:
    (entry,) = MARKETPLACE["plugins"]
    assert PLUGIN["version"] == entry["version"] == PYPROJECT["project"]["version"] == __version__


def test_marketplace_lists_this_repo_as_the_plugin() -> None:
    assert MARKETPLACE["name"] == "realoem-searcher"
    assert MARKETPLACE["owner"] == {"name": "Cadtastic"}
    (entry,) = MARKETPLACE["plugins"]
    assert (entry["name"], entry["source"]) == ("realoem-searcher", ".")


def test_mcp_server_launches_the_console_script_with_uv() -> None:
    server = PLUGIN["mcpServers"]["realoem"]
    assert server["command"] == "uv"
    assert server["args"] == [
        "run",
        "--quiet",
        "--no-dev",
        "--frozen",
        "--directory",
        "${CLAUDE_PLUGIN_ROOT}/server",
        "realoem-mcp",
    ]
    assert server["env"] == {"REALOEM_BRANDS_DIR": "${CLAUDE_PLUGIN_ROOT}/brands"}
    assert PYPROJECT["project"]["scripts"]["realoem-mcp"] == "realoem_mcp.server:main"
