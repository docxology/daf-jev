"""Client-side circuit breaker: composable failure isolation that
complements the per-request :class:`~daf_jev._retry.RetryPolicy`.

The retry policy governs a single request (retryable statuses, exponential
backoff). Consumers running long evaluation loops need a coarser failure
isolation layer: after ``failure_threshold`` consecutive failures the
circuit opens and calls fail fast for ``cooldown_seconds``; after the
cooldown a single probe call is allowed through to test whether the remote
has recovered.

The breaker is a pure client-side wrapper over any callable. It never
touches the transport, never sleeps (waiting out the cooldown is the
caller's choice — the same pure-computation philosophy as
:class:`~daf_jev._retry.RetryPolicy`), and is opt-in: it is not wired into
:class:`~daf_jev.client.JevClient` by default. Thread safety: all state
transitions happen under a lock, and the wrapped callable always runs
outside the lock.
"""

from __future__ import annotations

import enum
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from daf_jev._errors import TypeSafeError

__all__ = ["CircuitBreaker", "CircuitOpenError", "CircuitState"]

T = TypeVar("T")


class CircuitState(enum.Enum):
    """The three states of the breaker's finite state machine."""

    CLOSED = "closed"  # normal operation
    OPEN = "open"  # failing fast after consecutive failures
    HALF_OPEN = "half_open"  # one probe allowed through after the cooldown


class CircuitOpenError(TypeSafeError):
    """Raised instead of calling the wrapped callable while the circuit is open."""

    def __init__(
        self, message: str, *, remaining_seconds: float | None = None
    ) -> None:
        super().__init__(message)
        #: Seconds until the cooldown expires and a probe is allowed through.
        #: :meth:`CircuitBreaker.call` always passes a non-negative float:
        #: positive is the remaining cooldown; ``0.0`` means a retry is
        #: permitted immediately, subject to the single-probe rule (the
        #: rejected call raced a HALF_OPEN probe already in flight).
        #: ``None`` only when omitted at direct construction.
        self.remaining_seconds = remaining_seconds


class CircuitBreaker:
    """Opt-in failure isolation wrapper over any callable.

    Wrap an evaluation-loop step::

        breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)
        answer = breaker.call(client.ask, text, questions)

    Consecutive failures open the circuit for ``cooldown_seconds``; while
    open, :meth:`call` raises :class:`CircuitOpenError` without invoking the
    callable. After the cooldown expires exactly one probe is allowed
    through (the single-probe rule): a concurrent call while the probe is in
    flight also raises :class:`CircuitOpenError`. A successful probe closes
    the circuit; a failed probe reopens it with a fresh cooldown.

    Only consecutive failures trip the breaker: a success resets the
    counter, so isolated failures never open the circuit.

    ``clock`` defaults to :func:`time.monotonic` and is injectable for
    deterministic tests (never patched). The breaker never sleeps; callers
    decide whether to wait out the cooldown or back off externally.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Invoke ``fn(*args, **kwargs)`` behind the breaker.

        Raises :class:`CircuitOpenError` without invoking ``fn`` while the
        circuit is open (cooldown not elapsed) or while a HALF_OPEN probe is
        already in flight. On success the circuit closes and the
        consecutive-failure counter resets; on failure — any exception,
        including ``BaseException`` subclasses such as ``KeyboardInterrupt``
        — the counter increments and may trip the breaker; the exception
        is always re-raised, never swallowed.
        """
        with self._lock:
            now = self._clock()
            if self._state is CircuitState.OPEN:
                if now >= self._opened_at + self._cooldown_seconds:
                    # Reserve the single probe before leaving the lock.
                    self._state = CircuitState.HALF_OPEN
                else:
                    remaining = max(
                        0.0, self._opened_at + self._cooldown_seconds - now
                    )
                    raise CircuitOpenError(
                        "circuit is open: probe allowed in "
                        f"{remaining:.3f} seconds",
                        remaining_seconds=remaining,
                    )
            elif self._state is CircuitState.HALF_OPEN:
                # Single-probe rule: one probe is already in flight.
                raise CircuitOpenError(
                    "circuit is half-open: a probe is already in flight",
                    remaining_seconds=0.0,
                )
        try:
            result = fn(*args, **kwargs)
        except BaseException:
            # Counts BaseException too (KeyboardInterrupt, SystemExit,
            # asyncio.CancelledError): a HALF_OPEN probe that dies this way
            # would otherwise never record, wedging the breaker half-open
            # forever ("a probe is already in flight"). record_failure()
            # from HALF_OPEN reopens with a fresh stamp. Re-raised, never
            # swallowed.
            self.record_failure()
            raise
        self.record_success()
        return result

    def record_success(self) -> None:
        """Record a success manually (same transitions as :meth:`call`).

        Closes the circuit and resets the consecutive-failure counter from
        any state.
        """
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Record a failure manually (same transitions as :meth:`call`).

        A HALF_OPEN probe failure reopens the circuit with a fresh cooldown
        stamp. From CLOSED, reaching ``failure_threshold`` consecutive
        failures opens the circuit; below the threshold the breaker stays
        closed. A failure while already open keeps the existing cooldown.
        """
        with self._lock:
            self._consecutive_failures += 1
            if self._state is CircuitState.HALF_OPEN or (
                self._state is CircuitState.CLOSED
                and self._consecutive_failures >= self._failure_threshold
            ):
                # A HALF_OPEN probe failure reopens unconditionally; from
                # CLOSED only the threshold trips.
                self._open_locked()

    def _open_locked(self) -> None:
        """Open the circuit, stamping the cooldown start (lock held)."""
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()

    @property
    def state(self) -> CircuitState:
        """Current state (pure read; never transitions lazily).

        OPEN persists past the cooldown until a :meth:`call` or
        :meth:`record_failure`/ :meth:`record_success` drives the
        transition to HALF_OPEN or CLOSED.
        """
        with self._lock:
            return self._state

    @property
    def consecutive_failures(self) -> int:
        """Number of failures recorded since the last success or close."""
        with self._lock:
            return self._consecutive_failures

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot of the breaker for dashboards and logs."""
        with self._lock:
            if self._state is CircuitState.OPEN:
                now = self._clock()
                open_remaining_s = max(
                    0.0, self._opened_at + self._cooldown_seconds - now
                )
            else:
                open_remaining_s = 0.0
            return {
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown_seconds,
                "open_remaining_s": open_remaining_s,
            }
