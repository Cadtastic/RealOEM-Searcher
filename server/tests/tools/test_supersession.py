from pathlib import Path

import pytest
from mcp import Client
from mcp.types import CallToolResult

from realoem_mcp.server import build_server
from realoem_mcp.services import Services
from tests.harness import MakeServices, Route, load_fixture, url

pytestmark = pytest.mark.anyio

OIL_FILTER = url("partxref", q="11427953129")  # current
SUPERSEDED = url("partxref", q="11427541827")  # ended; successors ...566327, ...683196, ...953129
INTERMEDIATE = url("partxref", q="11427566327")  # ended; successors ...683196, ...953129
SPARK_PLUG = url("partxref", q="12120037244")  # current
SPARK_PLUG_PRED = url("partxref", q="12120034087")  # ended; successor 12120037244
REAL = {
    OIL_FILTER: "partxref/oil_filter_11427953129.html",
    SUPERSEDED: "partxref/superseded_11427541827.html",
    INTERMEDIATE: "partxref/intermediate_11427566327.html",
    SPARK_PLUG: "partxref/spark_plug_12120037244.html",
    SPARK_PLUG_PRED: "supersession/spark_plug_pred_12120034087.html",
}
RETRO = "Exchangeable retrospectively"
OIL_FILTER_HISTORY = ["11428683196", "11427566327", "11427541827"]


async def _trace(services: Services, **arguments: object) -> CallToolResult:
    async with Client(build_server(services)) as client:
        return await client.call_tool("trace_supersession", arguments)


def _numbers(entries: list[dict[str, object]]) -> list[object]:
    return [entry["part_number"] for entry in entries]


async def test_current_part(make_services: MakeServices) -> None:
    services, transport = make_services(REAL)
    result = await _trace(services, part_number="11 42 7 953 129")
    assert result.is_error is False
    data = result.structured_content
    assert (data["query"], data["status"]) == ("11427953129", "current")
    assert data["current_part_number"] == "11427953129"
    assert data["chain"] == [
        {
            "part_number": "11427953129",
            "description": "Set oil-filter element",
            "valid_from": "2017-06-01",
            "valid_to": None,
            "remark": None,
        }
    ]
    assert data["alternatives"] == []
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert data["history"][2]["in_catalog"] is False
    assert (data["complete"], data["warnings"]) == (True, [])
    assert (data["source_urls"], data["from_cache"], data["requests_made"]) == (
        [OIL_FILTER],
        False,
        1,
    )
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER]


async def test_replaced_part_jumps_to_the_open_ended_successor(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(REAL)
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert data["chain"] == [
        {
            "part_number": "11427541827",
            "description": "Set oil-filter element",
            "valid_from": "2004-09-01",
            "valid_to": "2006-03-17",
            "remark": None,
        },
        {
            "part_number": "11427953129",
            "description": "Set oil-filter element",
            "valid_from": "2017-06-01",
            "valid_to": None,
            "remark": RETRO,
        },
    ]
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert data["alternatives"] == []
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert data["requests_made"] == 2
    assert (data["complete"], data["warnings"]) == (True, [])
    # the short-lived intermediates 11427566327 and 11428683196 are never fetched
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


@pytest.mark.parametrize(
    ("start", "current", "start_url", "current_url"),
    [
        ("11427566327", "11427953129", INTERMEDIATE, OIL_FILTER),
        ("12120034087", "12120037244", SPARK_PLUG_PRED, SPARK_PLUG),
    ],
)
async def test_other_real_chains(
    make_services: MakeServices,
    start: str,
    current: str,
    start_url: str,
    current_url: str,
) -> None:
    services, _ = make_services(REAL)
    data = (await _trace(services, part_number=start)).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", current)
    assert [hop["part_number"] for hop in data["chain"]] == [start, current]
    assert [hop["remark"] for hop in data["chain"]] == [None, RETRO]
    assert start in _numbers(data["history"])
    assert data["source_urls"] == [start_url, current_url]
    assert (data["complete"], data["warnings"]) == (True, [])


async def test_seven_digit_short_form(make_services: MakeServices) -> None:
    short = url("partxref", q="7953129")
    services, transport = make_services({short: "partxref/short_7953129.html"})
    data = (await _trace(services, part_number="795-3129")).structured_content
    assert (data["query"], data["status"]) == ("7953129", "current")
    assert data["current_part_number"] == "11427953129"
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [short]


async def test_repeat_trace_uses_the_cache_until_refresh(make_services: MakeServices) -> None:
    services, transport = make_services(REAL)
    await _trace(services, part_number="11427541827")
    cached = (await _trace(services, part_number="11427541827")).structured_content
    assert (cached["from_cache"], cached["requests_made"]) == (True, 0)
    assert len(transport.requests) == 2
    fresh = (await _trace(services, part_number="11427541827", refresh=True)).structured_content
    assert (fresh["from_cache"], fresh["requests_made"]) == (False, 2)
    assert len(transport.requests) == 4


async def test_not_found(make_services: MakeServices) -> None:
    missing = url("partxref", q="11426666661")
    services, transport = make_services({missing: "partxref/not_found_11426666661.html"})
    data = (await _trace(services, part_number="11426666661")).structured_content
    assert (data["status"], data["current_part_number"]) == ("not_found", None)
    assert (data["chain"], data["alternatives"], data["history"]) == ([], [], [])
    assert (data["complete"], data["warnings"]) == (True, [])
    assert data["source_urls"] == [missing]
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"part_number": "abc"}, "is not a BMW part number"),
        ({"part_number": "1142754182"}, "is not a BMW part number"),
        ({"part_number": "11427541827", "max_hops": 0}, "max_hops must be between 1 and 10"),
        ({"part_number": "11427541827", "max_hops": 11}, "max_hops must be between 1 and 10"),
    ],
)
async def test_invalid_input_is_rejected_before_any_request(
    make_services: MakeServices, arguments: dict[str, object], message: str
) -> None:
    services, transport = make_services({})
    result = await _trace(services, **arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert transport.requests == []


async def test_unexpected_page_structure_is_reported(make_services: MakeServices) -> None:
    services, _ = make_services({SUPERSEDED: Route(fixture=None)})  # empty 200 page
    result = await _trace(services, part_number="11427541827")
    assert result.is_error is True
    assert "did not have the expected structure" in result.content[0].text


async def test_unparseable_successor_page_is_not_kept_in_the_cache(
    make_services: MakeServices,
) -> None:
    services, transport = make_services(
        {SUPERSEDED: REAL[SUPERSEDED], OIL_FILTER: Route(fixture=None)}  # empty 200 page
    )
    first = await _trace(services, part_number="11427541827")
    second = await _trace(services, part_number="11427541827")
    assert (first.is_error, second.is_error) == (True, True)
    # the predecessor comes from the cache; the broken successor page is fetched again
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER, OIL_FILTER]


# --- Synthetic pages -------------------------------------------------------------------------
# RealOEM has no captured example of these cases, so each test below edits a real fixture with
# plain string replacements and serves the result from tmp_path (pathlib: FIXTURES / <absolute
# path> is that absolute path). Every edit asserts that its "old" text is present.

SUPERSEDED_BLOCK = '<div class="superseded">'
SUPERSEDES_BLOCK = '<div class="supersedes">'
END_683196 = "(09/01/2016 — 09/21/2017)"  # 11428683196 in the 11427541827 page
END_953129 = "(06/01/2017 — )"  # 11427953129 in the 11427541827 page


def _synthetic(tmp_path: Path, fixture: str, *edits: tuple[str, str]) -> str:
    html = load_fixture(fixture)
    for old, new in edits:
        assert old in html, f"{fixture} no longer contains {old!r}"
        html = html.replace(old, new)
    path = tmp_path / Path(fixture).name
    path.write_text(html, encoding="utf-8")
    return str(path)


def _superseded_by(number: str, description: str, dates: str) -> str:
    """A one-entry "Superseded by" block in RealOEM's markup, inserted before "Supersedes"."""
    return (
        f'<div class="superseded"><h3>Superseded by:</h3><dl><dt class="sup-by-{{$t.count}}">'
        f'<a href="part?id=VB13-USA-10-2005-E90-BMW-325i&amp;q={number}">{number} - '
        f"{description}</a></dt><dd>{dates}, {RETRO}</dd></dl></div>{SUPERSEDES_BLOCK}"
    )


async def test_ended_without_successor(make_services: MakeServices, tmp_path: Path) -> None:
    # synthetic: 11427541827 (ENDED) with its "Superseded by" block renamed away
    page = _synthetic(
        tmp_path, "partxref/superseded_11427541827.html", (SUPERSEDED_BLOCK, '<div class="x">')
    )
    services, transport = make_services({SUPERSEDED: page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("no_successor", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["chain"][0]["valid_to"] == "2006-03-17"
    assert (data["alternatives"], data["history"]) == ([], [])
    assert (data["complete"], data["warnings"]) == (True, [])
    assert len(transport.requests) == 1


async def test_without_open_ended_successor_the_latest_end_is_followed(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 given an end date, so no successor of 11427541827 is open-ended
    page = _synthetic(
        tmp_path,
        "partxref/superseded_11427541827.html",
        (END_953129, "(06/01/2017 — 01/31/2025)"),
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: REAL[OIL_FILTER]})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


async def test_open_ended_predecessor_of_the_latest_successor_is_not_ambiguous(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11428683196 left open-ended; 11427953129 starts later and lists it as supersedes
    page = _synthetic(
        tmp_path, "partxref/superseded_11427541827.html", (END_683196, "(09/01/2016 — )")
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: REAL[OIL_FILTER]})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", "11427953129")
    assert data["alternatives"] == []
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


@pytest.mark.parametrize(
    ("max_hops", "requests", "chain", "warnings"),
    [
        (2, 3, ["11427541827", "11427953129", "12120037244"], []),
        (
            1,
            2,
            ["11427541827", "11427953129"],
            ["hop limit reached (max_hops=1): the page of successor 12120037244 was not read"],
        ),
    ],
)
async def test_hop_limit(
    make_services: MakeServices,
    tmp_path: Path,
    max_hops: int,
    requests: int,
    chain: list[str],
    warnings: list[str],
) -> None:
    # synthetic: 11427953129 "superseded by" 12120037244 (a real current page; only the numbers
    # matter), making a two-hop chain 11427541827 -> 11427953129 -> 12120037244
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        (SUPERSEDES_BLOCK, _superseded_by("12120037244", "Spark plug", "(01/01/2025 — )")),
    )
    services, transport = make_services({**REAL, OIL_FILTER: page})
    data = (await _trace(services, part_number="11427541827", max_hops=max_hops)).structured_content
    # at the limit the successor's number is reported but its page is not read
    assert (data["status"], data["current_part_number"]) == ("replaced", "12120037244")
    assert [hop["part_number"] for hop in data["chain"]] == chain
    assert (data["complete"], data["warnings"]) == (not warnings, warnings)
    assert data["requests_made"] == requests
    assert len(transport.requests) == requests


@pytest.mark.parametrize(
    ("end_953129", "current"),
    [(END_953129, "11427953129"), ("(06/01/2017 — 01/31/2025)", None)],
    ids=["open-ended-successor", "no-open-ended-successor"],
)
async def test_successor_without_a_page_ends_the_trace(
    make_services: MakeServices, tmp_path: Path, end_953129: str, current: str | None
) -> None:
    # synthetic routing: RealOEM answers "not found" for the chosen successor 11427953129;
    # synthetic page in the second case: 11427953129 given an end date in the 11427541827 page,
    # so the newest successor RealOEM names is not open-ended and no current part is known
    page = _synthetic(tmp_path, "partxref/superseded_11427541827.html", (END_953129, end_953129))
    services, _ = make_services(
        {SUPERSEDED: page, OIL_FILTER: "partxref/not_found_11426666661.html"}
    )
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("replaced", current)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["history"] == []
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert data["complete"] is False
    assert data["warnings"] == ["successor page missing: RealOEM has no page for 11427953129"]


async def test_successor_ended_without_successor(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 marked ENDED with no "Superseded by" block, one hop after 11427541827
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        ("<dd>-</dd>", "<dd>01/31/2025 (ENDED)</dd>"),
    )
    services, transport = make_services({SUPERSEDED: REAL[SUPERSEDED], OIL_FILTER: page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("no_successor", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827", "11427953129"]
    assert data["chain"][1]["valid_to"] == "2025-01-31"
    assert _numbers(data["history"]) == OIL_FILTER_HISTORY
    assert (data["complete"], data["warnings"]) == (True, [])
    assert [str(r.url) for r in transport.requests] == [SUPERSEDED, OIL_FILTER]


# --- Ambiguity and loops ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("successor_page", "warnings"),
    [
        (REAL[OIL_FILTER], []),
        (
            "partxref/not_found_11426666661.html",
            ["successor page missing: RealOEM has no page for 11427953129"],
        ),
    ],
    ids=["successor-does-not-list-it", "successor-has-no-page"],
)
async def test_distinct_open_ended_successors_are_ambiguous(
    make_services: MakeServices, tmp_path: Path, successor_page: str, warnings: list[str]
) -> None:
    # synthetic: 11428683196 renamed to 11427000001 (unknown to 11427953129) and left open-ended
    page = _synthetic(
        tmp_path,
        "partxref/superseded_11427541827.html",
        ("11428683196", "11427000001"),
        (END_683196, "(09/01/2016 — )"),
    )
    services, transport = make_services({SUPERSEDED: page, OIL_FILTER: successor_page})
    data = (await _trace(services, part_number="11427541827")).structured_content
    assert (data["status"], data["current_part_number"]) == ("ambiguous", None)
    assert _numbers(data["alternatives"]) == ["11427000001", "11427953129"]
    assert [a["valid_to"] for a in data["alternatives"]] == [None, None]
    assert [hop["part_number"] for hop in data["chain"]] == ["11427541827"]
    assert data["history"] == []
    # the latest successor's page was read to check whether it replaces the other one
    assert data["source_urls"] == [SUPERSEDED, OIL_FILTER]
    assert (data["complete"], data["warnings"]) == (not warnings, warnings)
    assert len(transport.requests) == 2


async def test_links_looping_back_stop_the_trace(
    make_services: MakeServices, tmp_path: Path
) -> None:
    # synthetic: 11427953129 "superseded by" 11427541827, which points back to 11427953129
    page = _synthetic(
        tmp_path,
        "partxref/oil_filter_11427953129.html",
        (SUPERSEDES_BLOCK, _superseded_by("11427541827", "Set oil-filter element", END_953129)),
    )
    services, transport = make_services({OIL_FILTER: page, SUPERSEDED: REAL[SUPERSEDED]})
    data = (await _trace(services, part_number="11427953129")).structured_content
    assert (data["status"], data["current_part_number"]) == ("ambiguous", None)
    assert [hop["part_number"] for hop in data["chain"]] == ["11427953129", "11427541827"]
    assert _numbers(data["alternatives"]) == ["11427953129"]
    assert data["complete"] is False
    assert data["warnings"] == [
        "loop detected: 11427541827 is superseded by 11427953129, which is already in the chain"
    ]
    assert [str(r.url) for r in transport.requests] == [OIL_FILTER, SUPERSEDED]
