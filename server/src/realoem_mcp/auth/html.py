"""The sign-in pages: plain HTML, no scripts, every value escaped (hosted design 4.6)."""

from __future__ import annotations

import html
import unicodedata
from collections.abc import Iterable
from urllib.parse import urlsplit

from realoem_mcp.auth.outcomes import ConsentDetails
from realoem_mcp.auth.redirects import is_loopback
from realoem_mcp.config import CLAUDE_CALLBACK, REPO_URL

MAX_SHOWN_NAME = 64
CONTINUE_ONLY = "Continue only if you just connected RealOEM Searcher in Claude."
GRANTED = (
    "RealOEM Searcher tools, counted against your daily quota; reads only the id, username and "
    "creation date of your public GitHub profile"
)
ERRORS = {  # kind -> (status, message)
    "expired": (400, "This sign-in request has expired. Start again from Claude."),
    "banned": (403, "Access to RealOEM Searcher is suspended."),
    "github_unavailable": (503, "GitHub sign-in is unavailable right now; try again shortly."),
    "busy": (503, "RealOEM Searcher is busy; try again in a minute."),
}
_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem;"
    "line-height:1.5}code{word-break:break-all}button{font-size:1rem;padding:.5rem 1.25rem;"
    "margin-right:.5rem}"
)


def shown_name(name: str | None) -> str:
    """A self-asserted client name made safe to show: no control or bidi-override characters,
    at most 64 characters, HTML-escaped."""
    if not name:
        return ""
    kept = "".join(char for char in name if unicodedata.category(char) not in ("Cc", "Cf"))
    return html.escape(kept[:MAX_SHOWN_NAME], quote=True)


def requester(details: ConsentDetails, allowlist: Iterable[str]) -> str:
    """Who is asking, named by where the answer goes, never by the name the client chose."""
    uri = details.redirect_uri
    if uri == CLAUDE_CALLBACK:
        return "Claude (claude.ai)"
    if is_loopback(uri):
        name = shown_name(details.client_name)
        calls_itself = f" that calls itself &#8216;{name}&#8217;" if name else ""
        return f"A program on this computer (<code>{html.escape(uri)}</code>){calls_itself}"
    if uri in tuple(allowlist):
        return f"Claude ({html.escape(urlsplit(uri).hostname or uri)})"
    return html.escape(uri)  # registration admits nothing else; shown plainly if it ever did


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def consent_page(
    details: ConsentDetails, *, csrf: str, expires_at: int, allowlist: Iterable[str]
) -> str:
    fields = {"req": details.request_id, "exp": str(expires_at), "csrf": csrf}
    hidden = "".join(
        f'<input type="hidden" name="{name}" value="{html.escape(value, quote=True)}">'
        for name, value in fields.items()
    )
    return _page(
        "Connect RealOEM Searcher",
        "<h1>Connect RealOEM Searcher?</h1>"
        f"<p><strong>{requester(details, allowlist)}</strong> wants to use RealOEM Searcher "
        "with your GitHub account.</p>"
        f"<p>{CONTINUE_ONLY}</p>"
        f"<p>It gets: {GRANTED}.</p>"
        f"<p>You will be sent back to <code>{html.escape(details.redirect_uri)}</code>.</p>"
        f'<form method="post" action="/consent">{hidden}'
        '<button type="submit" name="decision" value="allow">Allow</button>'
        '<button type="submit" name="decision" value="deny">Deny</button></form>',
    )


def error_page(kind: str) -> tuple[int, str]:
    """(status, HTML) for an error kind. No stack traces and no echo of the request."""
    status, message = ERRORS[kind]
    contact = (
        f'<p>If you think this is a mistake, <a href="{REPO_URL}/issues">open an issue</a>.</p>'
        if kind == "banned"
        else ""
    )
    return status, _page("RealOEM Searcher", f"<h1>RealOEM Searcher</h1><p>{message}</p>{contact}")
