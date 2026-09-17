"""Token and request accounting across ``ask()`` call loops.

The client's ``ask()`` method returns per-call usage on every
:class:`~daf_jev._types.SystemOneResponse`, and ``Evaluator.summary()``
aggregates usage for evaluation runs. Neither accumulates usage across an
arbitrary loop of client calls, so consumers making many requests outside
an :class:`~daf_jev.evaluate.Evaluator` have no running total.

``UsageLedger`` fills that gap: a small, thread-safe accumulator that
accepts ``Usage`` instances, ``SystemOneResponse`` instances, or ``None``
(error paths in evaluation loops often produce no response) and maintains
running request counts and token totals. Read ``UsageLedger.snapshot()``
at any point for an immutable :class:`UsageSnapshot`, or ``reset()`` to
collect-and-zero in one step.

Example:
    >>> from daf_jev.ledger import UsageLedger
    >>> from daf_jev._types import Usage
    >>> ledger = UsageLedger()
    >>> for source in [Usage(input_tokens=1, output_tokens=2), None]:
    ...     ledger.record(source)  # None entries are silently skipped
    >>> ledger.snapshot().total_tokens > 0
    True

"""

from __future__ import annotations

import dataclasses
import threading

from daf_jev._types import SystemOneResponse, Usage

__all__ = ["UsageLedger", "UsageSnapshot"]


@dataclasses.dataclass(frozen=True)
class UsageSnapshot:
    """Immutable point-in-time totals from a :class:`UsageLedger`."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens billed (input plus output)."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-safe dict of all totals."""
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


class UsageLedger:
    """Thread-safe accumulator of request counts and token totals.

    A single instance may be shared across threads; every read and write
    takes an internal lock, so ``record()`` calls from concurrent workers
    never lose counts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def record(self, source: Usage | SystemOneResponse | None) -> None:
        """Add one call's usage to the running totals.

        ``source`` may be:

        - a :class:`~daf_jev._types.Usage` — counted directly;
        - a :class:`~daf_jev._types.SystemOneResponse` — its ``usage`` is
          counted;
        - ``None`` — a silent no-op (error paths in evaluation loops pass
          ``None`` when no response was produced).

        Returns ``None`` by design: the caller already holds per-call usage
        on the response; the ledger exists for aggregates.
        """
        if source is None:
            return
        usage = source if isinstance(source, Usage) else source.usage
        with self._lock:
            self._requests += 1
            self._input_tokens += usage.input_tokens
            self._output_tokens += usage.output_tokens

    def snapshot(self) -> UsageSnapshot:
        """Return the current totals as an immutable snapshot."""
        with self._lock:
            return UsageSnapshot(
                requests=self._requests,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )

    def reset(self) -> UsageSnapshot:
        """Return the pre-reset totals, then zero the ledger."""
        with self._lock:
            prior = UsageSnapshot(
                requests=self._requests,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
            )
            self._requests = 0
            self._input_tokens = 0
            self._output_tokens = 0
            return prior
