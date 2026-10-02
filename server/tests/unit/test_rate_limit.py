"""SlidingWindow (hosted design 4.9)."""

from realoem_mcp.rate_limit import SWEEP_EVERY, SlidingWindow


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_allows_the_limit_then_says_when_to_retry() -> None:
    clock = Clock()
    window = SlidingWindow(2, 60.0, clock=clock)
    for _ in range(2):
        assert window.retry_after("a") is None
        window.record("a")
        clock.now += 10
    assert window.retry_after("a") == 40.0  # the first event leaves the window in 40 s
    assert window.retry_after("b") is None  # other keys are counted separately
    clock.now += 40
    assert window.retry_after("a") is None


def test_a_refusal_records_nothing() -> None:
    clock = Clock()
    window = SlidingWindow(1, 60.0, clock=clock)
    window.record("a")
    for _ in range(5):
        assert window.retry_after("a") is not None
    clock.now += 60
    assert window.retry_after("a") is None


def test_idle_keys_are_forgotten() -> None:
    clock = Clock()
    window = SlidingWindow(5, 60.0, clock=clock)
    window.record("old")
    clock.now += 61
    for i in range(SWEEP_EVERY):
        window.record(f"new{i % 3}")
    assert "old" not in window._events


def test_a_key_emptied_by_a_lookup_is_forgotten_and_never_breaks_the_sweep() -> None:
    clock = Clock()
    window = SlidingWindow(5, 60.0, clock=clock)
    window.record("a")
    clock.now += 61
    assert window.retry_after("a") is None  # its only event left the window
    for i in range(SWEEP_EVERY):  # the sweep runs once in here
        window.record(f"other{i % 3}")
    assert "a" not in window._events
