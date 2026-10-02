"""The VIN log filter (hosted design 4.9)."""

import logging

import pytest

from realoem_mcp.log_privacy import WITHHELD, VinFilter, install_vin_filter, mask_vins


def _record(name: str, msg: str, *args: object, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, exc_info)


def _formatted(record: logging.LogRecord) -> str:
    assert VinFilter().filter(record) is True  # the filter changes records, never drops them
    return logging.Formatter("%(message)s").format(record)


def test_vin_query_values_are_masked() -> None:
    assert (
        mask_vins("GET https://www.realoem.com/bmw/enUS/select?vin=PX22770&x=1 failed")
        == "GET https://www.realoem.com/bmw/enUS/select?vin=***&x=1 failed"
    )
    assert mask_vins("production?VIN=WBA12345678901234'") == "production?VIN=***'"
    assert mask_vins("no vins here") == "no vins here"


def test_any_logger_s_vin_urls_are_masked() -> None:
    record = _record("httpx", "HTTP Request: GET %s", "https://x/select?vin=PX22770")
    assert _formatted(record) == "HTTP Request: GET https://x/select?vin=***"


def test_a_failed_decode_vin_keeps_only_the_tool_name() -> None:
    sdk = "mcp.server.mcpserver.server"
    failed = _record(sdk, "Tool %r failed: %r", "decode_vin", "'PX2277' is not a VIN")
    assert _formatted(failed) == f"Tool 'decode_vin' failed: '{WITHHELD}'"
    other = _record(sdk, "Tool %r failed: %r", "lookup_part", "no such part 123")
    assert _formatted(other) == "Tool 'lookup_part' failed: 'no such part 123'"


def test_tracebacks_are_masked_too() -> None:
    try:
        raise RuntimeError("fetching https://x/production?vin=PX22770 broke")
    except RuntimeError:
        import sys

        record = _record("realoem_mcp", "boom", exc_info=sys.exc_info())
    text = _formatted(record)
    assert "PX22770" not in text and "production?vin=***" in text


def test_a_traceback_formatted_earlier_is_masked_too() -> None:
    record = _record("realoem_mcp", "boom")
    record.exc_text = "Traceback ...\nRuntimeError: https://x/select?vin=PX22770"
    assert "PX22770" not in _formatted(record)


def test_a_malformed_log_call_still_passes_the_filter() -> None:
    record = _record("realoem_mcp", "fetch %s %s for vin=PX22770", "https://x/select?vin=PX22770")
    assert VinFilter().filter(record) is True  # logging itself reports the bad call later
    # ... printing the raw message and arguments, so those are masked too
    assert record.msg == "fetch %s %s for vin=***"
    assert record.args == ("https://x/select?vin=***",)


def test_install_adds_the_filter_to_every_root_handler(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test_log_privacy")
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    try:
        install_vin_filter(logger)
        assert any(isinstance(f, VinFilter) for f in handler.filters)
    finally:
        logger.removeHandler(handler)
