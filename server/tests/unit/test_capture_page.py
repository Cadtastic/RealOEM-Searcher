from pathlib import Path

import httpx
import pytest

from realoem_mcp.config import Settings
from realoem_mcp.errors import BotChallenge
from realoem_mcp.page_types import PageType
from scripts.capture_page import capture, format_headers, main, parse_params
from tests.harness import BRANDS_DIR, LANDING_URL, FakeClock, FixtureTransport, Route, url

pytestmark = pytest.mark.anyio


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", data_dir=tmp_path / "data", brands_dir=BRANDS_DIR)


def test_parse_params_keeps_order() -> None:
    assert list(parse_params(["q=11427953129", "series=E90"]).items()) == [
        ("q", "11427953129"),
        ("series", "E90"),
    ]
    with pytest.raises(ValueError, match="key=value"):
        parse_params(["q"])


def test_format_headers_labels_each_attempt() -> None:
    request = httpx.Request("GET", "https://www.realoem.com/bmw/enUS/partgrp?id=VB13")
    moved = httpx.Response(301, headers={"Location": "/bmw/", "X-RO-UI": "v2"}, request=request)
    busy = httpx.Response(503, request=request)
    assert format_headers([moved, busy]) == (
        "# attempt 1: GET https://www.realoem.com/bmw/enUS/partgrp?id=VB13\n"
        "HTTP/1.1 301 Moved Permanently\nlocation: /bmw/\nx-ro-ui: v2\n"
        "\n"
        "# attempt 2: GET https://www.realoem.com/bmw/enUS/partgrp?id=VB13 (retry)\n"
        "HTTP/1.1 503 Service Unavailable\n"
    )


async def test_capture_writes_html_and_headers(tmp_path: Path) -> None:
    target = url("partgrp", id="VB13")
    redirect = Route(redirect_to=LANDING_URL, headers={"X-RO-UI": "v2"})
    transport = FixtureTransport({target: redirect})
    clock = FakeClock()
    html_path, headers_path = await capture(
        PageType.PARTGRP,
        "typecode_only",
        {"id": "VB13"},
        settings=_settings(tmp_path),
        out_dir=tmp_path / "raw",
        transport=transport,
        clock=clock,
        sleep=clock.sleep,
    )
    # One min-interval wait before the fetch (spacing across runs), one between the two hops.
    assert clock.sleeps == [2.0, 2.0]
    assert html_path == tmp_path / "raw" / "partgrp" / "typecode_only.html"
    assert html_path.read_text(encoding="utf-8") == ""
    headers = headers_path.read_text(encoding="utf-8")
    assert headers.startswith(f"# attempt 1: GET {target}\nHTTP/1.1 301 Moved Permanently\n")
    assert "location: https://www.realoem.com/bmw/" in headers
    assert "\n\n# attempt 2: GET https://www.realoem.com/bmw/\nHTTP/1.1 200 OK\n" in headers
    assert [r.headers["Cookie"] for r in transport.requests] == ["ro_ui=v2", "ro_ui=v2"]


async def test_capture_refuses_challenge_pages(tmp_path: Path) -> None:
    target = url("partxref", q="11427953129")
    transport = FixtureTransport(
        {target: Route("common/cloudflare_challenge.html", 403, {"cf-mitigated": "challenge"})}
    )
    clock = FakeClock()
    with pytest.raises(BotChallenge):
        await capture(
            PageType.PARTXREF,
            "blocked",
            {"q": "11427953129"},
            settings=_settings(tmp_path),
            out_dir=tmp_path / "raw",
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
        )
    assert not (tmp_path / "raw").exists()


@pytest.mark.parametrize("name", ["../evil", "a/b", "a\\b", "", "x.html", "sp ace", "C:x"])
async def test_capture_rejects_unsafe_names_before_any_request(tmp_path: Path, name: str) -> None:
    transport = FixtureTransport({})
    clock = FakeClock()
    with pytest.raises(ValueError, match="name"):
        await capture(
            PageType.PARTXREF,
            name,
            {"q": "1"},
            settings=_settings(tmp_path),
            out_dir=tmp_path / "raw",
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
        )
    assert transport.requests == []
    assert clock.sleeps == []
    assert not (tmp_path / "raw").exists()


def test_cli_rejects_unsafe_names(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        main(["partxref", "../evil", "q=1", "--out-dir", str(tmp_path)])
    assert info.value.code == 2
