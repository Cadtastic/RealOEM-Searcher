"""The consent page, the GitHub callback, cookies and headers over HTTP (hosted design 4.6)."""

import base64
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from realoem_mcp.auth.keys import Keys
from realoem_mcp.config import CLAUDE_CALLBACK
from tests.hosted_config import SECRET_KEY, query_of
from tests.http_env import HostedEnv, cookies_of, hidden_field, hosted_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def env(tmp_path: Path):
    async with hosted_app(tmp_path) as created:
        yield created


async def _consent_url(env: HostedEnv, **client: object) -> str:
    registered = await env.register(**client)
    response = await env.authorize(registered)
    assert response.status_code == 302
    return response.headers["location"]


def _set_cookie(response, name: str) -> str:
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))


async def test_the_consent_page_sets_a_strict_host_only_cookie(env: HostedEnv) -> None:
    page = await env.http.get(await _consent_url(env))
    assert page.status_code == 200
    cookie = _set_cookie(page, "__Host-ro_csrf").lower()
    for attribute in ("secure", "httponly", "samesite=strict", "path=/", "max-age=600"):
        assert attribute in cookie
    assert "domain=" not in cookie
    assert "Claude (claude.ai)" in page.text and CLAUDE_CALLBACK in page.text


async def test_a_loopback_client_is_named_as_a_local_program(env: HostedEnv) -> None:
    url = await _consent_url(
        env, redirect_uri="http://localhost:3000/cb", client_name="<b>Claude Code</b>"
    )
    page = await env.http.get(url)
    assert "A program on this computer" in page.text
    assert "&lt;b&gt;Claude Code&lt;/b&gt;" in page.text and "<b>Claude" not in page.text


async def test_allow_hands_over_to_github_with_a_lax_state_cookie(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    assert to_github.status_code == 302
    assert to_github.headers["location"].startswith("https://github.example/")
    cookie = _set_cookie(to_github, "__Host-ro_gh_state").lower()
    for attribute in ("secure", "httponly", "samesite=lax", "path=/", "max-age=600"):
        assert attribute in cookie


async def test_deny_returns_to_claude_with_access_denied(env: HostedEnv) -> None:
    back = await env.consent(await _consent_url(env), decision="deny")
    assert back.status_code == 302
    assert back.headers["location"].startswith(CLAUDE_CALLBACK)
    assert query_of(back.headers["location"]) == {"error": "access_denied", "state": "client-state"}


@pytest.mark.parametrize(
    "tamper", ["no-cookie", "other-cookie", "bad-mac", "expired", "exp-unicode", "replay"]
)
async def test_a_tampered_or_stale_consent_shows_an_error_never_a_redirect(
    env: HostedEnv, tamper: str
) -> None:
    page = await env.http.get(await _consent_url(env))
    form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
    cookie = cookies_of(page)["__Host-ro_csrf"]
    if tamper == "replay":
        first = await env.http.post(
            "/consent",
            data={**form, "decision": "allow"},
            headers={"Cookie": f"__Host-ro_csrf={cookie}"},
        )
        assert first.status_code == 302
    if tamper == "bad-mac":
        form["csrf"] = "0" * 64
    if tamper == "expired":  # correctly signed, but its time is up
        form["exp"] = "1"
        form["csrf"] = Keys(base64.b64decode(SECRET_KEY)).hash(
            "consent", f"consent|{form['req']}|{cookie}|1"
        )
    if tamper == "exp-unicode":  # "²" passes str.isdigit() but int() refuses it
        form["exp"] = "\u00b2"
    headers = {
        "no-cookie": {},
        "other-cookie": {"Cookie": "__Host-ro_csrf=someone-else"},
    }.get(tamper, {"Cookie": f"__Host-ro_csrf={cookie}"})
    response = await env.http.post("/consent", data={**form, "decision": "allow"}, headers=headers)
    assert response.status_code == 400
    assert "location" not in response.headers
    assert "This sign-in request has expired" in response.text


async def test_an_oversized_consent_form_is_refused_unread(env: HostedEnv) -> None:
    page = await env.http.get(await _consent_url(env))
    form = {name: hidden_field(page.text, name) for name in ("req", "exp", "csrf")}
    cookie = {"Cookie": f"__Host-ro_csrf={cookies_of(page)['__Host-ro_csrf']}"}
    for oversized in ({**form, "req": "x" * 2_000}, {**form, **{f"f{n}": "1" for n in range(20)}}):
        response = await env.http.post("/consent", data=oversized, headers=cookie)
        assert response.status_code == 400 and "location" not in response.headers
        assert "expired" not in response.text  # refused by the form parser, before our checks


async def test_the_callback_without_its_cookie_shows_an_error(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    code = env.github.approve(to_github.headers["location"], env.github.add_user(1))
    state = query_of(to_github.headers["location"])["state"]
    response = await env.http.get("/oauth/github/callback", params={"code": code, "state": state})
    assert response.status_code == 400 and "location" not in response.headers
    assert "__Host-ro_gh_state=" in response.headers["set-cookie"]  # cleared either way


async def test_the_callback_clears_its_cookie_and_returns_a_code(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    back = await env.github_returns(to_github, env.github.add_user(1))
    assert back.status_code == 302
    assert set(query_of(back.headers["location"])) == {"code", "state"}
    cleared = _set_cookie(back, "__Host-ro_gh_state").lower()
    assert "max-age=0" in cleared


async def test_a_banned_user_sees_the_suspended_page(env: HostedEnv) -> None:
    to_github = await env.consent(await _consent_url(env))
    with closing(sqlite3.connect(env.settings.auth_path)) as conn:
        conn.execute(
            "INSERT INTO users (subject, github_login, first_seen, banned_at) "
            "VALUES ('github:66', 'x', 0, 1)"
        )
        conn.commit()
    response = await env.github_returns(to_github, env.github.add_user(66))
    assert response.status_code == 403 and "location" not in response.headers
    assert "suspended" in response.text
