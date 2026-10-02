"""The hosted server's image: what goes in, and how it runs (hosted design 4.10)."""

from tests.harness import REPO_ROOT

DOCKERFILE = (REPO_ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "server" / "docker-entrypoint.sh").read_text(encoding="utf-8")
DOCKERIGNORE = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_only_server_and_brands_reach_the_image() -> None:
    lines = [line for line in _lines(DOCKERIGNORE) if not line.startswith("#")]
    assert lines[0] == "*"  # everything is left out unless listed below
    assert [line for line in lines if line.startswith("!")] == ["!server/", "!brands/"]
    assert {"server/.venv/", "server/tests/", "**/.env*"} <= set(lines)


def test_the_image_runs_the_http_server_as_the_app_user() -> None:
    lines = [line for line in _lines(DOCKERFILE) if not line.startswith("#")]
    assert lines[0] == "FROM python:3.13-slim"
    assert "COPY server/ ./" in lines and "COPY brands/ /app/brands/" in lines
    assert "RUN uv sync --frozen --no-dev --no-install-project" in lines
    assert 'ENTRYPOINT ["/app/server/docker-entrypoint.sh"]' in lines
    assert lines[-1] == 'CMD ["realoem-mcp-http"]'
    assert "USER root" not in lines
    assert ENTRYPOINT.startswith("#!/bin/sh\n")
    # read_text() hides CRLF line endings, which would break the script inside Linux.
    assert b"\r" not in (REPO_ROOT / "server" / "docker-entrypoint.sh").read_bytes()
    assert _lines(ENTRYPOINT)[-1] == 'exec setpriv --reuid=app --regid=app --init-groups -- "$@"'
