"""Errors of the hosted server: quota, busy and call-deadline messages (hosted design 4.7)."""

from realoem_mcp.errors import Busy, CallDeadline, QuotaExceeded, RealOemError


def test_quota_exceeded_names_the_callers_limit() -> None:
    err = QuotaExceeded(300)
    assert isinstance(err, RealOemError)
    assert (err.limit, err.server_wide) == (300, False)
    assert err.message == (
        "You've used your 300 RealOEM lookups for today; the limit resets at 00:00 UTC. "
        "Cached results remain available."
    )


def test_server_wide_quota_message_names_no_number() -> None:
    err = QuotaExceeded(2000, server_wide=True)
    assert (err.limit, err.server_wide) == (2000, True)
    assert err.message == (
        "RealOEM Searcher has reached its daily request limit; try again after 00:00 UTC."
    )


def test_busy_and_call_deadline_are_user_facing_errors() -> None:
    assert isinstance(Busy(), RealOemError)
    assert isinstance(CallDeadline(), RealOemError)
    assert Busy().message == "RealOEM Searcher is busy; try again in a minute."
    assert CallDeadline().message == (
        "This call took too long; call again to continue (pages already fetched are cached)."
    )
