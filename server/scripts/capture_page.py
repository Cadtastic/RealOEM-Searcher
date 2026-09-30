"""Politely capture one RealOEM page (raw HTML + response headers) into .research-raw/.

One page per run; do not loop this script over many pages.

Goes through RealOemClient, so the user agent, cookie, rate limit and challenge detection are the
same as the server's. Raw captures are git-ignored; turn them into fixtures with trim_fixture.py.

Usage (from server/):
    uv run python scripts/capture_page.py partxref oil_filter_series q=11427953129 series=E90
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

import httpx

from realoem_mcp.config import Settings
from realoem_mcp.errors import RealOemError
from realoem_mcp.page_types import PageType
from realoem_mcp.services import create_services

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / ".research-raw"
_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]+")


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wraps a transport and keeps every response (redirect hops included) for the headers file."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.responses: list[httpx.Response] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        self.responses.append(response)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def check_name(name: str) -> str:
    """The capture name becomes a file name, so allow only letters, digits, _ and -."""
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"name must match [A-Za-z0-9_-]+, got {name!r}")
    return name


def _name_arg(value: str) -> str:
    try:
        return check_name(value)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from None


def parse_params(pairs: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {pair!r}")
        params[key] = value
    return params


def format_headers(responses: Sequence[httpx.Response]) -> str:
    """One block per request sent; redirect hops and retried attempts each get their own."""
    blocks = []
    seen: set[str] = set()
    for number, response in enumerate(responses, start=1):
        url = str(response.request.url)
        label = f"# attempt {number}: GET {url}" + (" (retry)" if url in seen else "")
        seen.add(url)
        lines = [label, f"HTTP/1.1 {response.status_code} {response.reason_phrase}"]
        lines += [f"{name}: {value}" for name, value in response.headers.multi_items()]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


async def capture(
    page_type: PageType,
    name: str,
    params: Mapping[str, str],
    *,
    settings: Settings,
    out_dir: Path = DEFAULT_OUT_DIR,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> tuple[Path, Path]:
    check_name(name)
    recorder = RecordingTransport(transport)
    services = create_services(settings, transport=recorder, clock=clock, sleep=sleep)
    try:
        # The client only spaces requests within one process; wait once so back-to-back runs
        # of this script are spaced too.
        await (sleep or asyncio.sleep)(settings.min_interval_s)
        page = await services.client.fetch(page_type, page_type.value, params, refresh=True)
    finally:
        await services.aclose()
    folder = out_dir / page_type.value
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{name}.html"
    headers_path = folder / f"{name}.headers"
    html_path.write_text(page.html, encoding="utf-8", newline="\n")
    headers_path.write_text(format_headers(recorder.responses), encoding="utf-8", newline="\n")
    return html_path, headers_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture one RealOEM page into .research-raw/. One page per run; do not loop."
    )
    parser.add_argument("page_type", choices=[p.value for p in PageType])
    parser.add_argument(
        "name", type=_name_arg, help="file name without extension, e.g. oil_filter_series"
    )
    parser.add_argument("params", nargs="*", help="query parameters as key=value, in send order")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    try:
        html_path, headers_path = asyncio.run(
            capture(
                PageType(args.page_type),
                args.name,
                parse_params(args.params),
                settings=Settings.from_env(),
                out_dir=args.out_dir,
            )
        )
    except (RealOemError, ValueError) as err:
        print(f"capture failed: {err}", file=sys.stderr)
        return 1
    print(f"wrote {html_path} and {headers_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
