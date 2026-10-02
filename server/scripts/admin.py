"""MAINTAINER ONLY: look after the hosted server's users (hosted design 4.8, 4.9).

Run it on the server as the app user, never as root, so SQLite's WAL files never become
root-owned; it refuses to run as root. On the hosted server use the image's own Python (`uv run`
would install the development tools first):

    /app/server/.venv/bin/python /app/server/scripts/admin.py usage [--day YYYY-MM-DD]
    ... ban <github id> --reason "..."
    ... unban <github id>
    ... revoke <github id>
    ... prune

Locally, from server/: uv run python scripts/admin.py usage

<github id> is the numeric GitHub id (the number in "github:<id>" in the logs).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TextIO

from realoem_mcp.auth.store import AuthStore
from realoem_mcp.config import Settings


def _subject(github_id: str) -> str:
    if not (github_id.isascii() and github_id.isdigit()):
        raise argparse.ArgumentTypeError(f"a GitHub id is a number, got {github_id!r}")
    return f"github:{github_id}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    usage = commands.add_parser("usage", help="requests per user for one UTC day")
    usage.add_argument("--day", help="YYYY-MM-DD (default: today, UTC)")
    ban = commands.add_parser("ban", help="refuse a user's sign-ins and tokens")
    ban.add_argument("subject", type=_subject, metavar="github_id")
    ban.add_argument("--reason", required=True)
    for name, text in (("unban", "lift a ban"), ("revoke", "sign a user out everywhere")):
        command = commands.add_parser(name, help=text)
        command.add_argument("subject", type=_subject, metavar="github_id")
    commands.add_parser("prune", help="run the hourly purge now")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    now: Callable[[], float] = time.time,
    out: TextIO = sys.stdout,
) -> int:
    args = _parser().parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(
            "Run this as the app user, not root: root-owned files stop the server.", file=sys.stderr
        )
        return 2
    path = (settings or Settings.from_env()).auth_path
    if not path.exists():  # never create a new, empty database: a ban there would do nothing
        print(
            f"No auth database at {path}; set REALOEM_DATA_DIR (or REALOEM_AUTH_DIR).",
            file=sys.stderr,
        )
        return 2
    print(f"Auth database: {path}", file=out)
    store = AuthStore.open(path)
    try:
        if args.command == "usage":
            day = args.day or datetime.fromtimestamp(now(), UTC).date().isoformat()
            rows = store.usage(day)
            print(f"Requests on {day} (UTC):", file=out)
            for subject, login, requests in rows:
                name = "everyone" if subject == "*" else f"{subject} ({login or '?'})"
                print(f"  {requests:>6}  {name}", file=out)
            if not rows:
                print("  none", file=out)
        elif args.command == "ban":
            store.ban(args.subject, args.reason, int(now()))
            print(f"Banned {args.subject}; its tokens are revoked.", file=out)
        elif args.command == "unban":
            done = store.unban(args.subject)
            print(
                f"Unbanned {args.subject}." if done else f"{args.subject} was not banned.", file=out
            )
        elif args.command == "revoke":
            count = store.revoke_subject(args.subject)
            print(f"Revoked {count} sign-in(s) of {args.subject}.", file=out)
        else:
            removed = store.purge(int(now()))
            summary = ", ".join(f"{count} {table}" for table, count in removed.items() if count)
            print(f"Pruned: {summary or 'nothing'}.", file=out)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
