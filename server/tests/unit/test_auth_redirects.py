"""The redirect allow-list, a security invariant (hosted design 4.3)."""

import pytest
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl

from realoem_mcp.auth.redirects import ClaudeClient, is_allowed, is_loopback
from realoem_mcp.config import CLAUDE_CALLBACK

ALLOWLIST = (CLAUDE_CALLBACK,)


@pytest.mark.parametrize(
    "uri",
    [
        CLAUDE_CALLBACK,
        "http://localhost:33418/callback",
        "http://127.0.0.1:8765/oauth/callback?x=1",
        "http://localhost/callback",
    ],
)
def test_claude_and_loopback_redirects_are_allowed(uri: str) -> None:
    assert is_allowed(uri, ALLOWLIST)


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback/",  # not the exact string
        "https://evil.example/callback",
        "http://localhost.evil.com/callback",
        "http://localhost@evil.com/callback",
        "http://user@localhost/callback",
        "http://127.0.0.1.nip.io/callback",
        "http://localhost:3000/callback#fragment",
        "https://localhost:3000/callback",  # loopback means plain http
        "http://[::1]:3000/callback",
        "http://localhost:99999/callback",  # a port that cannot exist
        "http://localhost:3000/" + "x" * 491,  # 513 characters
    ],
)
def test_everything_else_is_refused(uri: str) -> None:
    assert not is_allowed(uri, ALLOWLIST)


def test_the_length_limit_is_512() -> None:
    base = "http://localhost:3000/"
    assert is_loopback(base + "x" * (512 - len(base)))
    assert not is_loopback(base + "x" * (513 - len(base)))


def _client(*uris: str) -> ClaudeClient:
    return ClaudeClient(client_id="c", redirect_uris=[AnyUrl(uri) for uri in uris])


def test_a_loopback_redirect_matches_on_any_port() -> None:
    client = _client("http://localhost:3000/callback")
    requested = AnyUrl("http://localhost:41234/callback")
    assert client.validate_redirect_uri(requested) == requested  # keeps the requested port
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://localhost:41234/other"))
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://127.0.0.1:41234/callback"))  # another host
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("http://localhost:41234/callback?x=1"))  # query


def test_a_loopback_redirect_without_a_path_matches_too() -> None:
    # Registered as the client sent it (the SDK keeps the empty path); requested with "/".
    client = ClaudeClient.model_validate(
        {"client_id": "c", "redirect_uris": ["http://127.0.0.1:33418"]}
    )
    requested = AnyUrl("http://127.0.0.1:40000")
    assert client.validate_redirect_uri(requested) == requested


def test_other_redirects_must_match_exactly() -> None:
    client = _client(CLAUDE_CALLBACK)
    assert client.validate_redirect_uri(AnyUrl(CLAUDE_CALLBACK)) == AnyUrl(CLAUDE_CALLBACK)
    assert client.validate_redirect_uri(None) == AnyUrl(CLAUDE_CALLBACK)  # the only one
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://claude.ai/api/mcp/other"))
