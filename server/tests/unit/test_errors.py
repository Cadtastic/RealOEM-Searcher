from realoem_mcp.errors import (
    BotChallenge,
    InvalidInput,
    LayoutChanged,
    NotFound,
    RealOemError,
    UpstreamError,
)


def test_hierarchy() -> None:
    for cls in (InvalidInput, NotFound, BotChallenge, LayoutChanged, UpstreamError):
        assert issubclass(cls, RealOemError)


def test_message_is_user_facing() -> None:
    err = InvalidInput("Part numbers have 7 or 11 digits.")
    assert err.message == "Part numbers have 7 or 11 digits."
    assert str(err) == err.message


def test_bot_challenge_names_the_url() -> None:
    err = BotChallenge("https://www.realoem.com/bmw/enUS/partxref?q=11427953129")
    assert err.url.endswith("q=11427953129")
    assert "bot challenge" in err.message
    assert "open https://www.realoem.com/bmw/enUS/partxref?q=11427953129 in a browser" in (
        err.message
    )


def test_layout_changed_fields() -> None:
    err = LayoutChanged("partxref", "missing 'div.content > h1'", "https://x/partxref?q=1")
    assert (err.page_type, err.detail, err.url) == (
        "partxref",
        "missing 'div.content > h1'",
        "https://x/partxref?q=1",
    )
    assert "partxref" in err.message
    assert "missing 'div.content > h1'" in err.message


def test_upstream_error_status_or_detail() -> None:
    assert "HTTP 503" in UpstreamError(503, "https://x/a").message
    timeout = UpstreamError(None, "https://x/a", "timed out")
    assert timeout.status is None
    assert "timed out" in timeout.message
