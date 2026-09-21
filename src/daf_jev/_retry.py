"""Retry policy: pure delay computation; sleeping happens in the client
(injectable clock/sleep for tests). See docs/reference/sdk/python/api/
retries.md for the documented SDK semantics.
"""

from __future__ import annotations

import dataclasses
import random

__all__ = ["RetryPolicy"]


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior.

    ``max_attempts`` counts the initial request plus retries (3 = up to two
    retries). ``retryable_statuses`` are the HTTP status codes worth retrying.
    """

    max_attempts: int = 3
    retryable_statuses: frozenset[int] = frozenset({429, 529})
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    jitter: float = 0.1
    respect_retry_after: bool = True

    def next_delay(self, attempt: int, retry_after: float | None) -> float:
        """Pure: the delay in seconds before retrying after ``attempt``.

        Exponential ``backoff_base * 2**(attempt-1)`` capped at
        ``backoff_max``, plus uniform ``+-jitter/2``. When
        ``respect_retry_after`` is set and ``retry_after`` is provided (the
        client passes the Retry-After header value already clamped to
        [0, 300] seconds; an unsupported or unparseable header yields
        ``None``), the server-requested delay wins verbatim. The result is
        never negative; tests get determinism by passing ``jitter=0``.
        """
        if self.respect_retry_after and retry_after is not None:
            return max(float(retry_after), 0.0)
        exponent = max(attempt, 1) - 1
        delay = min(self.backoff_base * (2**exponent), self.backoff_max)
        if self.jitter:
            delay += random.uniform(-self.jitter / 2, self.jitter / 2)
        return max(delay, 0.0)
