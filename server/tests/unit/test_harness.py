import httpx
import pytest

from tests.harness import (
    LANDING_URL,
    UNMATCHED_STATUS,
    FakeClock,
    FixtureTransport,
    Route,
    load_fixture,
    url,
)

pytestmark = pytest.mark.anyio


def test_url_matches_client_encoding() -> None:
    assert url("partxref", q="11427953129", series="E90") == (
        "https://www.realoem.com/bmw/enUS/partxref?q=11427953129&series=E90"
    )
    assert url("showparts", id="0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91,_0J93_") == (
        "https://www.realoem.com/bmw/enUS/showparts"
        "?id=0J93-USA-05-2019-K50-BMW-R_1250_GS_19_0J91%2C_0J93_"
    )


def test_load_fixture_reads_utf8_text() -> None:
    assert "<title>Just a moment...</title>" in load_fixture("common/cloudflare_challenge.html")


async def test_routes_serve_fixture_status_and_headers() -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport(
        {target: Route("common/cloudflare_challenge.html", 403, {"cf-mitigated": "challenge"})}
    )
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(target)
    assert response.status_code == 403
    assert response.headers["cf-mitigated"] == "challenge"
    assert "Just a moment..." in response.text
    assert [str(r.url) for r in transport.requests] == [target]
    assert transport.unmatched == []


async def test_string_route_is_a_fixture_path() -> None:
    target = url("partgrp", id="VB13-USA-10-2005-E90-BMW-325i")
    transport = FixtureTransport({target: "common/partgrp_e90_325i.html"})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(target)
    assert response.status_code == 200
    assert 'rel="canonical"' in response.text


async def test_redirect_to_unrouted_landing_is_empty_200() -> None:
    target = url("partgrp", id="VB13")
    transport = FixtureTransport({target: Route(redirect_to=LANDING_URL)})
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
        response = await http.get(target)
    assert response.status_code == 200
    assert str(response.url) == LANDING_URL
    assert response.text == ""
    assert [str(r.url) for r in transport.requests] == [target, LANDING_URL]
    assert transport.unmatched == []


async def test_unmatched_url_is_recorded_and_answered_with_404() -> None:
    transport = FixtureTransport({})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(url("part", q="1"))
    assert response.status_code == UNMATCHED_STATUS == 404
    assert transport.unmatched == [url("part", q="1")]


async def test_route_keys_are_normalized_like_httpx() -> None:
    # A hand-written key with unencoded characters still matches what httpx sends.
    transport = FixtureTransport({"https://www.realoem.com/bmw/enUS/select?model=R 1250": Route()})
    async with httpx.AsyncClient(transport=transport) as http:
        response = await http.get(url("select", model="R 1250"))
    assert response.status_code == 200
    assert transport.unmatched == []


async def test_fake_clock_advances_on_sleep() -> None:
    clock = FakeClock(start=10.0)
    await clock.sleep(2.5)
    assert clock() == 12.5
    assert clock.sleeps == [2.5]
