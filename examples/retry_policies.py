"""Retry policies: pure RetryPolicy delay math and env resolution.

Demonstrates:
- the frozen ``RetryPolicy`` fields (``max_attempts`` counts the initial
  request plus retries; ``retryable_statuses`` is {429, 529})
- ``next_delay`` exponential backoff with a cap, printed deterministically
  via ``jitter=0`` configs (with jitter > 0 the table would vary per run)
- ``Retry-After`` precedence: the server-requested delay wins verbatim
  while ``respect_retry_after=True``, and pure exponential backoff when
  ``respect_retry_after=False``
- ``resolve_retry`` env overrides plus silent fallback on invalid values
- where the resolved policy comes from: ``JevClient`` resolves it when
  ``retry=`` is omitted, ``load_settings().retry`` carries the same
  policy, and the Decider's default client pins ``max_attempts=1``

Run: python examples/retry_policies.py
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import Any

from daf_jev import RetryPolicy, load_settings, resolve_retry

ATTEMPTS = (1, 2, 3, 4)
NO_JITTER = RetryPolicy(jitter=0.0)


def cfg(**overrides: Any) -> RetryPolicy:
    """Deterministic policy variant: jitter=0 so printed tables never vary."""
    return dataclasses.replace(NO_JITTER, **overrides)


def fmt_policy(policy: RetryPolicy) -> str:
    return (
        f"max_attempts={policy.max_attempts} "
        f"backoff_base={policy.backoff_base} "
        f"backoff_max={policy.backoff_max} "
        f"jitter={policy.jitter}"
    )


def print_default_fields() -> None:
    print("Default RetryPolicy fields:")
    for field, value in dataclasses.asdict(RetryPolicy()).items():
        print(f"  {field}={value}")
    print()


def print_table() -> None:
    rows: list[tuple[str, RetryPolicy, float | None]] = [
        ("default", cfg(), None),
        ("fast", cfg(backoff_base=0.25, max_attempts=5, backoff_max=4.0), None),
        ("big-base-capped", cfg(backoff_base=2.0, backoff_max=5.0), None),
        ("single-attempt", cfg(max_attempts=1), None),
        ("retry_after=2.5", cfg(), 2.5),
        ("retry_after=2.5 (ignored)", cfg(respect_retry_after=False), 2.5),
    ]
    header = f"{'config':<26}{'max':>3}" + "".join(
        f"{'att=' + str(a):>8}" for a in ATTEMPTS
    )
    print("next_delay(attempt, retry_after) per config (all jitter=0; the")
    print("stock default policy uses jitter=0.1, which would randomize it):")
    print(header)
    for label, policy, retry_after in rows:
        prefix = f"{label:<26}{policy.max_attempts:>3}"
        if retry_after is not None:
            cells = [
                f"{policy.next_delay(a, retry_after):>8.2f}" for a in ATTEMPTS
            ]
        else:
            # A client never asks for a delay once attempts are exhausted,
            # so cells at or past max_attempts are marked not-applicable.
            cells = [
                f"{policy.next_delay(a, None):>8.2f}"
                if a < policy.max_attempts else f"{'n/a':>8}"
                for a in ATTEMPTS
            ]
        print(prefix + "".join(cells))
    print()
    print(
        "* retry_after=2.5 (ignored): respect_retry_after=False drops the\n"
        "  server hint and applies exponential backoff instead\n"
        "  (backoff_base * 2**(attempt-1), capped at backoff_max); with\n"
        "  respect_retry_after=True the 2.5s Retry-After wins verbatim.\n"
        "  single-attempt (the Decider's default) never reaches a retry."
    )
    print()


def print_env_resolution() -> None:
    print("resolve_retry(env) resolution:")
    default = resolve_retry({})
    print(f"  {'<empty>':>18} -> {fmt_policy(default)}")

    custom = resolve_retry(
        {
            "JEV_MAX_ATTEMPTS": "5",
            "JEV_BACKOFF_BASE": "0.25",
            "JEV_BACKOFF_MAX": "10.0",
            "JEV_JITTER": "0",
        }
    )
    print(f"  {'valid overrides':>18} -> {fmt_policy(custom)}")

    invalid = resolve_retry({"JEV_MAX_ATTEMPTS": "0"})
    print(
        f"  {'JEV_MAX_ATTEMPTS=0':>18} -> {fmt_policy(invalid)}"
        "  (invalid values silently keep defaults)"
    )
    print()
    print(
        "Notes: .env is consulted in addition to the process environment;\n"
        "JevClient resolves the policy automatically when retry= is not\n"
        "passed; load_settings().retry carries the same resolved policy;\n"
        "the Decider's default client pins RetryPolicy(max_attempts=1) so\n"
        "each ask is a single attempt with no retries."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RetryPolicy delay comparison and env resolution (no network)."
    )
    parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    print("Jev retry behavior, computed offline (no requests are made).")
    print(f"Retryable HTTP statuses: {sorted(RetryPolicy().retryable_statuses)}")
    print()
    print_default_fields()
    print_table()
    print_env_resolution()


if __name__ == "__main__":
    main()
