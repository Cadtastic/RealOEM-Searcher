"""The consent and error pages (hosted design 4.6)."""

from realoem_mcp.auth.html import (
    CONTINUE_ONLY,
    GRANTED,
    consent_page,
    error_page,
    requester,
    shown_name,
)
from realoem_mcp.auth.outcomes import ConsentDetails
from realoem_mcp.config import CLAUDE_CALLBACK

ALLOWLIST = (CLAUDE_CALLBACK, "https://claude.com/api/mcp/auth_callback")


def _details(redirect_uri: str, name: str | None = "Claude") -> ConsentDetails:
    return ConsentDetails("req-1", name, redirect_uri, ("realoem",))


def test_client_names_are_cleaned_shortened_and_escaped() -> None:
    assert shown_name("<b>Evil</b>") == "&lt;b&gt;Evil&lt;/b&gt;"
    assert shown_name("Claude\u202eedoC\x07") == "ClaudeedoC"  # bidi override and BEL removed
    assert shown_name("x" * 100) == "x" * 64
    assert shown_name(None) == ""


def test_the_requester_is_named_by_where_the_answer_goes() -> None:
    assert requester(_details(CLAUDE_CALLBACK, "Totally Not Claude"), ALLOWLIST) == (
        "Claude (claude.ai)"
    )
    assert requester(_details("https://claude.com/api/mcp/auth_callback"), ALLOWLIST) == (
        "Claude (claude.com)"
    )
    local = requester(_details("http://localhost:3000/cb", "<i>Claude Code</i>"), ALLOWLIST)
    assert local == (
        "A program on this computer (<code>http://localhost:3000/cb</code>) that calls itself "
        "&#8216;&lt;i&gt;Claude Code&lt;/i&gt;&#8217;"
    )


def test_the_consent_page_says_what_is_granted_and_where_it_goes() -> None:
    page = consent_page(
        _details("http://localhost:3000/cb?x=<1>"), csrf="mac", expires_at=123, allowlist=ALLOWLIST
    )
    assert CONTINUE_ONLY in page and GRANTED in page
    assert "http://localhost:3000/cb?x=&lt;1&gt;" in page  # the full redirect URI, escaped
    for hidden in ('name="req" value="req-1"', 'name="exp" value="123"', 'name="csrf" value="mac"'):
        assert hidden in page
    assert 'value="allow">Allow</button>' in page and 'value="deny">Deny</button>' in page
    assert "<script" not in page


def test_error_pages_have_a_status_and_no_echo() -> None:
    assert error_page("expired")[0] == 400
    assert "Start again from Claude" in error_page("expired")[1]
    status, page = error_page("banned")
    assert status == 403 and "suspended" in page and "/issues" in page
    assert error_page("github_unavailable")[0] == 503
    status, page = error_page("busy")
    assert status == 503 and "busy" in page
