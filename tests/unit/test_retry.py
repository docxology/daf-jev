"""Unit tests for daf_jev._retry: pure next_delay math and the retryable set."""

from __future__ import annotations

from daf_jev._retry import RetryPolicy


def test_default_retryable_statuses() -> None:
    policy = RetryPolicy()
    assert policy.retryable_statuses == frozenset({429, 529})
    assert policy.max_attempts == 3
    assert policy.respect_retry_after is True


def test_exponential_backoff_with_zero_jitter() -> None:
    policy = RetryPolicy(jitter=0.0)
    assert policy.next_delay(1, None) == 0.5
    assert policy.next_delay(2, None) == 1.0
    assert policy.next_delay(3, None) == 2.0
    assert policy.next_delay(4, None) == 4.0


def test_backoff_capped_at_backoff_max() -> None:
    policy = RetryPolicy(jitter=0.0, backoff_max=8.0)
    assert policy.next_delay(5, None) == 8.0
    assert policy.next_delay(50, None) == 8.0


def test_retry_after_wins_when_respected() -> None:
    policy = RetryPolicy(jitter=0.0, respect_retry_after=True)
    assert policy.next_delay(1, 3.25) == 3.25
    assert policy.next_delay(10, 0.0) == 0.0


def test_retry_after_ignored_when_disabled() -> None:
    policy = RetryPolicy(jitter=0.0, respect_retry_after=False)
    assert policy.next_delay(1, 3.25) == 0.5


def test_negative_retry_after_clamped_to_zero() -> None:
    policy = RetryPolicy(jitter=0.0, respect_retry_after=True)
    assert policy.next_delay(1, -5.0) == 0.0


def test_next_delay_is_pure() -> None:
    policy = RetryPolicy(jitter=0.0)
    first = policy.next_delay(2, None)
    second = policy.next_delay(2, None)
    assert first == second == 1.0


def test_jitter_adds_bounded_noise() -> None:
    policy = RetryPolicy(jitter=0.5)
    for _ in range(50):
        assert 0.25 <= policy.next_delay(1, None) <= 0.75
