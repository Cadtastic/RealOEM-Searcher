from pathlib import Path

import httpx
import pytest

from realoem_mcp.cache import PageCache
from realoem_mcp.config import Settings
from realoem_mcp.errors import BotChallenge, LayoutChanged, UpstreamError
from realoem_mcp.http_client import RealOemClient
from realoem_mcp.page_types import PageType
from tests.harness import FakeClock, load_fixture, url

pytestmark = pytest.mark.anyio

PARAMS = {"q": "11427953129"}
XREF = url("partxref", **PARAMS)
CHALLENGE = load_fixture("common/cloudflare_challenge.html")


class Script:
    """httpx handler that plays back responses (or exceptions) in order."""

    def __init__(self, *steps: httpx.Response | Exception) -> None:
        self.steps = list(steps)
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
async def run(tmp_path: Path):
    made: list[tuple[RealOemClient, PageCache]] = []

    async def fetch(script: Script):
        clock = FakeClock()
        cache = PageCache(tmp_path / f"cache{len(made)}")
        client = RealOemClient(
            Settings(cache_dir=tmp_path),
            cache,
            transport=httpx.MockTransport(script),
            clock=clock,
            sleep=clock.sleep,
        )
        made.append((client, cache))
        page = await client.fetch(PageType.PARTXREF, "partxref", PARAMS)
        return page, clock, client

    yield fetch
    for client, cache in made:
        await client.aclose()
        cache.close()


async def test_cloudflare_403_is_a_bot_challenge_and_never_retried(run) -> None:
    script = Script(httpx.Response(403, headers={"cf-mitigated": "challenge"}, text=CHALLENGE))
    with pytest.raises(BotChallenge) as info:
        await run(script)
    assert script.calls == 1
    assert info.value.url == XREF


async def test_challenge_title_is_detected_even_with_status_200(run) -> None:
    with pytest.raises(BotChallenge):
        await run(Script(httpx.Response(200, text=CHALLENGE)))


async def test_503_challenge_is_not_retried(run) -> None:
    script = Script(httpx.Response(503, headers={"cf-mitigated": "challenge"}, text=""))
    with pytest.raises(BotChallenge):
        await run(script)
    assert script.calls == 1


async def test_5xx_is_retried_after_5_seconds(run) -> None:
    script = Script(httpx.Response(503, text="busy"), httpx.Response(200, text="<p>ok</p>"))
    page, clock, client = await run(script)
    assert page.html == "<p>ok</p>"
    assert script.calls == 2
    assert clock.sleeps == [5.0]
    assert client.requests_made == 2  # every attempt sent is counted


async def test_retry_after_is_honoured_and_capped_at_30_seconds(run) -> None:
    script = Script(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429, headers={"Retry-After": "120"}),
        httpx.Response(200, text="ok"),
    )
    _, clock, _ = await run(script)
    assert clock.sleeps == [7.0, 30.0]


async def test_non_finite_retry_after_falls_back_to_default_backoff(run) -> None:
    script = Script(
        httpx.Response(429, headers={"Retry-After": "nan"}),
        httpx.Response(429, headers={"Retry-After": "inf"}),
        httpx.Response(200, text="ok"),
    )
    _, clock, _ = await run(script)
    assert clock.sleeps == [5.0, 15.0]


async def test_gives_up_after_two_retries(run) -> None:
    script = Script(*(httpx.Response(500) for _ in range(3)))
    with pytest.raises(UpstreamError) as info:
        await run(script)
    assert info.value.status == 500
    assert script.calls == 3


async def test_backoff_is_5_then_15_seconds(run) -> None:
    script = Script(httpx.Response(502), httpx.Response(502), httpx.Response(200, text="ok"))
    _, clock, _ = await run(script)
    assert clock.sleeps == [5.0, 15.0]


async def test_timeouts_are_retried(run) -> None:
    script = Script(httpx.ReadTimeout("slow"), httpx.Response(200, text="ok"))
    page, clock, _ = await run(script)
    assert page.status == 200
    assert clock.sleeps == [5.0]


async def test_repeated_timeouts_raise_upstream_error(run) -> None:
    script = Script(*(httpx.ReadTimeout("slow") for _ in range(3)))
    with pytest.raises(UpstreamError) as info:
        await run(script)
    assert info.value.status is None
    assert "timed out" in info.value.message


async def test_network_error_raises_upstream_error(run) -> None:
    with pytest.raises(UpstreamError, match="ConnectError"):
        await run(Script(httpx.ConnectError("refused")))


async def test_ui_variant_other_than_v2_is_a_layout_change(run) -> None:
    with pytest.raises(LayoutChanged) as info:
        await run(Script(httpx.Response(200, headers={"X-RO-UI": "v1"}, text="ok")))
    assert info.value.page_type == "partxref"
    assert "X-RO-UI" in info.value.detail


async def test_ui_variant_v2_new_is_accepted(run) -> None:
    page, _, _ = await run(Script(httpx.Response(200, headers={"X-RO-UI": "v2+new"}, text="ok")))
    assert page.status == 200
