"""Keeps VINs out of the hosted server's logs (hosted design 4.9).

The client masks the URLs it logs itself; this filter covers every other log line: vin= query
values are masked anywhere (tracebacks included), and the MCP SDK's line for a failed decode_vin
call loses its message, which can quote the user's input.
"""

from __future__ import annotations

import contextlib
import logging
import re

SDK_TOOL_LOGGER = "mcp.server.mcpserver.server"
SDK_TOOL_FAILED = "Tool %r failed: %r"
VIN_TOOLS = frozenset({"decode_vin"})
WITHHELD = "<withheld: it may contain a VIN>"
_VIN_VALUE = re.compile(r"(?i)\b(vin=)[^&#\s'\"]+")


def mask_vins(text: str) -> str:
    return _VIN_VALUE.sub(r"\1***", text)


class VinFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # A malformed log call must still reach logging's own error report, never raise here.
        with contextlib.suppress(Exception):
            self._mask(record)
        return True

    @staticmethod
    def _mask(record: logging.LogRecord) -> None:
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:  # also a traceback another handler formatted first
            record.exc_text = mask_vins(record.exc_text)
        if (
            record.name == SDK_TOOL_LOGGER
            and record.msg == SDK_TOOL_FAILED
            and isinstance(record.args, tuple)
            and record.args[:1]
            and record.args[0] in VIN_TOOLS
        ):
            record.args = (record.args[0], WITHHELD)
        try:
            message = record.getMessage()
        except Exception:
            # A malformed call: logging's error report prints the raw message and arguments.
            record.msg = mask_vins(str(record.msg))
            if isinstance(record.args, tuple):
                record.args = tuple(mask_vins(str(arg)) for arg in record.args)
            return
        masked = mask_vins(message)
        if masked != message:
            record.msg, record.args = masked, ()


def install_vin_filter(logger: logging.Logger | None = None) -> None:
    """Add the filter to every handler of the root logger (where all records end up)."""
    for handler in (logger or logging.getLogger()).handlers:
        handler.addFilter(VinFilter())
