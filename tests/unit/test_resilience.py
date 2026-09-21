"""Unit tests for daf_jev.resilience: the client-side circuit breaker.

The breaker is driven through an injected fake clock — daf_jev internals
are never patched or monkeypatched anywhere in this module. Integration
tests wire the breaker around a real :class:`~daf_jev.JevClient` talking
to the conftest stub HTTP server.
"""

from __future__ import annotations

import json
import threading

import pytest

import daf_jev
from daf_jev import NoulQuestion, RetryPolicy
from daf_jev._errors import InternalServerError, TypeSafeError
from daf_jev.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


class _SentinelError(Exception):
    """The wrapped callable's own failure signature."""


class FakeClock:
    """Injectable monotonic clock: deterministic, never patched."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(
    clock: FakeClock, *, threshold: int = 3, cooldown: float = 30.0
) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=threshold, cooldown_seconds=cooldown, clock=clock
    )


def _fail() -> None:
    raise _SentinelError("boom")


def test_passthrough_return_value_and_kwargs() -> None:
    breaker = _breaker(FakeClock())
    calls: list[tuple[tuple, dict]] = []

    def echo(*args: object, **kwargs: object) -> dict:
        calls.append((args, kwargs))
        return {"ok": True}

    assert breaker.call(echo, 1, 2, key="value") == {"ok": True}
    assert calls == [((1, 2), {"key": "value"})]
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_invalid_failure_threshold_raises_value_error() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=bad)


def test_invalid_cooldown_raises_value_error() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(cooldown_seconds=-0.1)
    # Boundary values are legal.
    CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)


def test_failures_below_threshold_stay_closed() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=3)

    for _ in range(2):
        with pytest.raises(_SentinelError):
            breaker.call(_fail)
        clock.advance(1.0)

    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 2


def test_nth_consecutive_failure_opens() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=3)

    for _ in range(2):
        with pytest.raises(_SentinelError):
            breaker.call(_fail)
        clock.advance(1.0)
    assert breaker.state is CircuitState.CLOSED

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    assert breaker.state is CircuitState.OPEN
    assert breaker.consecutive_failures == 3
    snapshot = breaker.to_dict()
    assert snapshot["state"] == "open"
    assert snapshot["open_remaining_s"] == pytest.approx(30.0)


def test_open_raises_without_invoking_fn_and_reports_remaining() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=30.0)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(5.0)

    invocations = 0

    def never() -> str:
        nonlocal invocations
        invocations += 1
        return "nope"

    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.call(never)
    assert invocations == 0
    assert excinfo.value.remaining_seconds == pytest.approx(25.0)
    assert "25.000" in str(excinfo.value)


def test_probe_runs_exactly_once_and_concurrent_call_raises() -> None:
    """After the cooldown exactly one probe runs; a second concurrent call
    (modeled by the probe re-entering call()) is rejected."""
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=10.0)
    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(10.0)

    invocations = 0
    half_open_snapshot: dict = {}

    def probe() -> str:
        nonlocal invocations
        invocations += 1
        half_open_snapshot.update(breaker.to_dict())
        with pytest.raises(CircuitOpenError) as excinfo:
            breaker.call(lambda: "concurrent")
        assert excinfo.value.remaining_seconds == 0.0
        return "recovered"

    assert breaker.call(probe) == "recovered"
    assert invocations == 1
    assert half_open_snapshot["state"] == "half_open"
    assert breaker.state is CircuitState.CLOSED


def test_probe_success_closes_and_resets() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=10.0)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(10.0)
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0
    assert breaker.to_dict()["state"] == "closed"


def test_probe_failure_reopens_with_fresh_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=10.0)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)  # opened at t=0
    clock.advance(11.0)  # cooldown elapsed at t=10

    with pytest.raises(_SentinelError):
        breaker.call(_fail)  # probe fails at t=11: fresh stamp

    assert breaker.state is CircuitState.OPEN
    # A stale stamp would have expired at t=10 (remaining 0); the fresh
    # stamp taken at t=11 leaves the full cooldown again.
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.call(_fail)
    assert excinfo.value.remaining_seconds == pytest.approx(10.0)
    assert breaker.to_dict()["open_remaining_s"] == pytest.approx(10.0)


def test_success_resets_consecutive_counter() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=3)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(1.0)
    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(1.0)
    breaker.call(lambda: "ok")  # resets the counter
    clock.advance(1.0)
    with pytest.raises(_SentinelError):
        breaker.call(_fail)

    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 1


def test_manual_driving_matches_call_transitions() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=2, cooldown=30.0)

    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 1

    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert breaker.consecutive_failures == 2

    # A manual failure while open keeps the existing cooldown stamp.
    clock.advance(10.0)
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert breaker.to_dict()["open_remaining_s"] == pytest.approx(20.0)

    # Manual success closes from any state.
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0

    # A HALF_OPEN probe recorded manually as a success closes cleanly.
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(40.0)
    assert breaker.call(lambda: "probe") == "probe"  # CLOSED again
    assert breaker.state is CircuitState.CLOSED


def test_manual_probe_failure_reopens_with_fresh_cooldown() -> None:
    """record_failure() while HALF_OPEN reopens with a fresh stamp even when
    the threshold alone would not trip (threshold=2 here)."""
    clock = FakeClock()
    breaker = _breaker(clock, threshold=2, cooldown=10.0)

    class _FailingProbe:
        def __call__(self) -> str:
            # Record the failure manually while the probe is in flight
            # (HALF_OPEN), then surface it to call() as well.
            breaker.record_failure()
            raise _SentinelError("boom")

    with pytest.raises(_SentinelError):
        breaker.call(_fail)  # first failure at t=0
    clock.advance(1.0)
    with pytest.raises(_SentinelError):
        breaker.call(_fail)  # second failure at t=1 -> opened
    clock.advance(10.0)
    with pytest.raises(_SentinelError):
        breaker.call(_FailingProbe())  # probe fails at t=11: fresh stamp

    assert breaker.state is CircuitState.OPEN
    # A stale stamp would have expired at t=10 (remaining 0); the fresh
    # stamp leaves the full cooldown again.
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.call(lambda: "x")
    assert excinfo.value.remaining_seconds == pytest.approx(10.0)


def test_state_property_is_pure_read() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=5.0)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    clock.advance(100.0)
    # Reading state never lazily transitions OPEN -> HALF_OPEN.
    assert breaker.state is CircuitState.OPEN
    assert breaker.state is CircuitState.OPEN
    assert breaker.to_dict()["open_remaining_s"] == 0.0


def test_record_success_closes_from_open() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1)

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    assert breaker.state is CircuitState.OPEN
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_circuit_open_error_without_remaining() -> None:
    error = CircuitOpenError("circuit is open")
    assert error.remaining_seconds is None
    assert str(error) == "circuit is open"
    assert isinstance(error, TypeSafeError)


def test_to_dict_json_safe_in_every_state() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=10.0)

    closed = breaker.to_dict()
    json.dumps(closed)
    assert closed["state"] == "closed"
    assert closed["failure_threshold"] == 1
    assert closed["cooldown_seconds"] == 10.0
    assert closed["open_remaining_s"] == 0.0

    with pytest.raises(_SentinelError):
        breaker.call(_fail)
    opened = breaker.to_dict()
    json.dumps(opened)
    assert opened["state"] == "open"
    assert opened["consecutive_failures"] == 1
    assert opened["open_remaining_s"] == pytest.approx(10.0)


def test_to_dict_json_safe_during_half_open_probe() -> None:
    clock = FakeClock()
    breaker = _breaker(clock, threshold=1, cooldown=0.0)
    with pytest.raises(_SentinelError):
        breaker.call(_fail)

    captured: dict = {}

    def probe() -> str:
        captured.update(breaker.to_dict())
        return "ok"

    breaker.call(probe)
    json.dumps(captured)
    assert captured["state"] == "half_open"
    assert captured["open_remaining_s"] == 0.0


def test_thread_safety_smoke_no_deadlock_exact_counts() -> None:
    """Threads hammer call() with a failing fn against a frozen clock:
    no deadlock, every call either ran fn or raised CircuitOpenError, and
    the recorded failure count matches the actual invocation count."""
    clock = FakeClock()
    threshold = 3
    threads_n, calls_per_thread = 8, 5
    breaker = _breaker(clock, threshold=threshold, cooldown=60.0)

    invocations = 0
    invocations_lock = threading.Lock()

    def fail() -> None:
        nonlocal invocations
        with invocations_lock:
            invocations += 1
        raise _SentinelError("boom")

    outcomes: list[type[BaseException]] = []
    outcomes_lock = threading.Lock()
    barrier = threading.Barrier(threads_n)

    def worker() -> None:
        barrier.wait()
        for _ in range(calls_per_thread):
            try:
                breaker.call(fail)
                outcome = RuntimeError  # call() returned: not allowed here
            except Exception as exc:  # classify every outcome
                outcome = type(exc)
            with outcomes_lock:
                outcomes.append(outcome)

    workers = [
        threading.Thread(target=worker, name=f"hammer-{i}")
        for i in range(threads_n)
    ]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=10)
    assert not any(worker_thread.is_alive() for worker_thread in workers)

    total = threads_n * calls_per_thread
    assert len(outcomes) == total
    assert all(
        outcome in (_SentinelError, CircuitOpenError) for outcome in outcomes
    )
    assert breaker.state is CircuitState.OPEN
    assert breaker.consecutive_failures == invocations
    assert threshold <= invocations <= threads_n
    assert outcomes.count(CircuitOpenError) == total - invocations

    # Cooldown never elapses on the frozen clock: every further call fails
    # fast without touching fn.
    for _ in range(20):
        with pytest.raises(CircuitOpenError) as excinfo:
            breaker.call(fail)
        assert excinfo.value.remaining_seconds == pytest.approx(60.0)
    assert invocations == breaker.consecutive_failures


def _questions() -> dict:
    return {"billing": NoulQuestion(instructions="Is this about billing?")}


def _answers_body() -> dict:
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "answers": {"billing": {"type": "noul", "noul": 0.9}},
    }


def _make_client(stub, **overrides):
    kwargs = {
        "api_key": "test-key",
        "base_url": stub.base_url,
        "sleep": lambda _seconds: None,  # injected no-op sleep; never patched
        "retry": RetryPolicy(jitter=0.0),
    }
    kwargs.update(overrides)
    return daf_jev.JevClient(**kwargs)


def test_circuit_breaker_passes_200_responses_through(stub) -> None:
    stub.enqueue(body=_answers_body())
    breaker = _breaker(FakeClock(), threshold=2, cooldown=10.0)
    client = _make_client(stub)
    try:
        resp = breaker.call(client.ask, "state", _questions())
    finally:
        client.close()

    assert "billing" in resp.answers
    assert len(stub.hits) == 1
    assert breaker.state is CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


def test_circuit_breaker_opens_after_5xx_run(stub) -> None:
    for _ in range(2):
        stub.enqueue(status=500, body={"error": {"message": "internal"}})
    breaker = _breaker(FakeClock(), threshold=2, cooldown=10.0)
    client = _make_client(stub, retry=RetryPolicy(max_attempts=1, jitter=0.0))

    for _ in range(2):
        with pytest.raises(InternalServerError):
            breaker.call(client.ask, "state", _questions())
    assert breaker.state is CircuitState.OPEN

    # The circuit now fails fast without touching the server.
    with pytest.raises(CircuitOpenError):
        breaker.call(client.ask, "state", _questions())
    assert len(stub.hits) == 2  # nothing new was requested
    client.close()

    # After the cooldown a failing probe reopens; a successful probe closes.
    breaker2 = _breaker(FakeClock(), threshold=1, cooldown=0.0)
    client2 = _make_client(stub, retry=RetryPolicy(max_attempts=1, jitter=0.0))
    stub.enqueue(status=500, body={"error": {"message": "internal"}})
    with pytest.raises(InternalServerError):
        breaker2.call(client2.ask, "state", _questions())
    assert breaker2.state is CircuitState.OPEN
    stub.enqueue(body=_answers_body())
    resp = breaker2.call(client2.ask, "state", _questions())  # probe
    client2.close()
    assert "billing" in resp.answers
    assert breaker2.state is CircuitState.CLOSED
