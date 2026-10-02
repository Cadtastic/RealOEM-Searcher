"""Settings and constants for hosted-server tests (no app import, so any task can use them)."""

from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from realoem_mcp.config import Settings
from tests.harness import BRANDS_DIR

BASE = "http://localhost:8080"
MCP_URL = f"{BASE}/mcp"
SECRET_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def hosted_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Complete hosted-server settings on temporary folders (a loopback public URL)."""
    values: dict[str, object] = {
        "mode": "http",
        "cache_dir": tmp_path / "cache",
        "data_dir": tmp_path / "data",
        "brands_dir": BRANDS_DIR,
        "public_url": BASE,
        "github_client_id": "github-client",
        "github_client_secret": "github-secret",
        "secret_key": SECRET_KEY,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def query_of(url: str) -> dict[str, str]:
    """The query parameters of a URL, one value each."""
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
