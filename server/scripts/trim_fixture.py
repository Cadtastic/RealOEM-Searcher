"""Turn a raw RealOEM capture into a small, committable test fixture (ARD section 8).

Usage (from server/):
    uv run python scripts/trim_fixture.py <raw.html> tests/fixtures/<page-type>/<slug>.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser, LexborNode

# Uppercase VIN alphabet (no I, O, Q) with at least one digit and one letter, standing alone or
# right after any percent-encoded character, as in next=%2fenUS%2fselect%3fvin%3dWBA...
_VIN = re.compile(
    r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2}))"
    r"(?=[A-HJ-NPR-Z0-9]{0,16}[0-9])(?=[A-HJ-NPR-Z0-9]{0,16}[A-HJ-NPR-Z])"
    r"[A-HJ-NPR-Z0-9]{17}"
    r"(?![A-Za-z0-9])"
)
# Servlet session id path parameter, e.g. /bmw/login;jsessionid=9EDE...?next=%2f
_JSESSIONID = re.compile(r";jsessionid=[^?#;&<>\"'\s]*", re.IGNORECASE)
_REMOVE = "style, iframe, ins, [id^='realoem-com_']"
_ECS_KEEP = ("class", "data-ecs-part-name")
_BLANK_LINES = re.compile(r"\n[ \t\r\n]*\n")


def mask_vins(html: str) -> str:
    """Replace every 17-character VIN with XXXXXXXXXX + its last 7 characters."""
    return _VIN.sub(lambda m: "XXXXXXXXXX" + m.group(0)[-7:], html)


def strip_session_ids(html: str) -> str:
    """Drop ;jsessionid=<value> path parameters, keeping the rest of the URL."""
    return _JSESSIONID.sub("", html)


def _keep_script(script: LexborNode) -> bool:
    if (script.attributes.get("type") or "").lower() == "application/ld+json":
        return True
    return "partsimgmap" in script.text(deep=True)


def _drop_trailing_whitespace(body: LexborNode | None) -> None:
    # Keeps trim() idempotent: a newline after </html> is re-parsed into <body>.
    while body is not None and body.last_child is not None:
        last = body.last_child
        if not last.is_text_node or last.text(deep=False).strip():
            return
        last.decompose()


def trim(html: str) -> str:
    tree = LexborHTMLParser(html)
    for node in tree.css("script"):
        if not _keep_script(node):
            node.decompose()
    for node in tree.css("link"):
        if (node.attributes.get("rel") or "").lower() != "canonical":
            node.decompose()
    for node in tree.css(_REMOVE):
        node.decompose()
    for node in [n for n in tree.root.traverse() if n.is_comment_node]:
        node.decompose()
    for node in tree.css("a.ecs-tuning-link"):
        node.decompose()
    for cell in tree.css("td.ecs-tuning-cell"):  # keep the empty cell: part rows have 11 tds
        for child in list(cell.iter(include_text=True)):
            child.decompose()
    for button in tree.css("a.ecs-tuning-button[data-ecs-part-name]"):
        for child in list(button.iter(include_text=True)):
            child.decompose()
        for name in [n for n in button.attributes if n not in _ECS_KEEP]:
            del button.attrs[name]
    _drop_trailing_whitespace(tree.body)
    compact = _BLANK_LINES.sub("\n", tree.html or "")
    return mask_vins(strip_session_ids(compact)).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trim a raw RealOEM page into a test fixture.")
    parser.add_argument("raw", type=Path, help="raw capture, e.g. ../.research-raw/xref/x.html")
    parser.add_argument("out", type=Path, help="fixture path under tests/fixtures/")
    args = parser.parse_args(argv)
    trimmed = trim(args.raw.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(trimmed, encoding="utf-8", newline="\n")
    before, after = args.raw.stat().st_size, len(trimmed.encode("utf-8"))
    print(f"{args.out}: {before} -> {after} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
