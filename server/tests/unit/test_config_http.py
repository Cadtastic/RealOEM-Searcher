"""The hosted server's sign-in settings (hosted design 4.8)."""

from pathlib import Path

import pytest

from realoem_mcp.config import CLAUDE_CALLBACK, HOSTED_CLIENT_RANGE, Settings
from tests.hosted_config import SECRET_KEY, hosted_settings


def test_defaults() -> None:
    settings = Settings(data_dir=Path("/srv/data"))
    assert settings.public_url is None
    assert settings.redirect_allowlist == (CLAUDE_CALLBACK,)
    assert settings.hosted_client_range == HOSTED_CLIENT_RANGE == "160.79.104.0/21"
    assert settings.auth_path == Path("/srv/data") / "auth.sqlite3"
    assert Settings(data_dir=Path("/d"), auth_dir=Path("/a")).auth_path == Path("/a/auth.sqlite3")


def test_from_env_reads_the_sign_in_settings() -> None:
    settings = Settings.from_env(
        {
            "REALOEM_PUBLIC_URL": "https://realoem-searcher.fly.dev/",
            "REALOEM_GITHUB_CLIENT_ID": "Iv1.abc",
            "REALOEM_GITHUB_CLIENT_SECRET": "shh",
            "REALOEM_SECRET_KEY": SECRET_KEY,
            "REALOEM_REDIRECT_ALLOWLIST": f"{CLAUDE_CALLBACK}, https://claude.com/cb",
            "REALOEM_HOSTED_CLIENT_RANGE": "10.0.0.0/8",
            "REALOEM_AUTH_DIR": "/auth",
        }
    )
    assert settings.public_url == "https://realoem-searcher.fly.dev"  # no trailing slash
    assert (settings.github_client_id, settings.github_client_secret) == ("Iv1.abc", "shh")
    assert settings.secret_key_bytes == b"0123456789abcdef0123456789abcdef"
    assert settings.redirect_allowlist == (CLAUDE_CALLBACK, "https://claude.com/cb")
    assert settings.hosted_client_range == "10.0.0.0/8"
    assert settings.auth_path == Path("/auth/auth.sqlite3")
    assert settings.mode == "stdio"  # only the entry point sets the mode


@pytest.mark.parametrize(
    "given",
    [
        " HTTPS://Realoem-Searcher.FLY.dev/ ",
        "https://realoem-searcher.fly.dev:443",
        "https://realoem-searcher.fly.dev:",
    ],
)
def test_the_public_url_is_kept_in_canonical_form(tmp_path: Path, given: str) -> None:
    settings = hosted_settings(tmp_path, public_url=given)
    assert settings.public_url == "https://realoem-searcher.fly.dev"
    settings.validate_http()
    assert hosted_settings(tmp_path, public_url="http://LOCALHOST:8080").public_url == (
        "http://localhost:8080"
    )


def test_the_allow_list_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="redirect_allowlist must be a list"):
        Settings(redirect_allowlist="https://claude.ai/api/mcp/auth_callback")  # type: ignore[arg-type]


def test_secrets_never_appear_in_repr(tmp_path: Path) -> None:
    text = repr(hosted_settings(tmp_path))
    for secret in ("github-client", "github-secret", SECRET_KEY):
        assert secret not in text


def test_complete_hosted_settings_pass(tmp_path: Path) -> None:
    hosted_settings(tmp_path).validate_http()
    hosted_settings(tmp_path, public_url="https://realoem-searcher.fly.dev").validate_http()


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"public_url": None}, "REALOEM_PUBLIC_URL is required"),
        ({"public_url": "http://realoem-searcher.fly.dev"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com/mcp"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com?x=1"}, "REALOEM_PUBLIC_URL must be"),
        ({"github_client_id": None}, "REALOEM_GITHUB_CLIENT_ID is required"),
        ({"github_client_secret": ""}, "REALOEM_GITHUB_CLIENT_SECRET is required"),
        ({"secret_key": None}, "REALOEM_SECRET_KEY is required"),
        ({"secret_key": "not base64!"}, "REALOEM_SECRET_KEY must be base64"),
        ({"secret_key": "c2hvcnQ="}, "at least 32 random bytes"),
        ({"redirect_allowlist": ()}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("http://evil.example/cb",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("claude.ai/api/mcp/auth_callback",)}, "REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://claude.ai/cb#frag",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://user@claude.ai/cb",)}, "REALOEM_REDIRECT_ALLOWLIST"),
        ({"redirect_allowlist": ("https://claude.ai/" + "a" * 512,)}, "REDIRECT_ALLOWLIST"),
        ({"public_url": "https://exa mple.com"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com#"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com?"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com:abc"}, "REALOEM_PUBLIC_URL must be"),
        ({"public_url": "https://example.com:99999"}, "REALOEM_PUBLIC_URL must be"),
        ({"hosted_client_range": "not a network"}, "REALOEM_HOSTED_CLIENT_RANGE"),
    ],
)
def test_a_missing_or_malformed_value_stops_the_server(
    tmp_path: Path, overrides: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match="The hosted server cannot start") as refused:
        hosted_settings(tmp_path, **overrides).validate_http()
    assert problem in str(refused.value)


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as refused:
        Settings(mode="http").validate_http()
    for name in ("PUBLIC_URL", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "SECRET_KEY"):
        assert f"REALOEM_{name}" in str(refused.value)
