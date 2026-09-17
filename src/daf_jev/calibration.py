"""Reliability calibration over (confidence, correct) pairs.

Pure, deterministic statistics for confidence calibration: bucketed
reliability tables, expected calibration error (ECE), and the Brier score.
No I/O.
"""

from collections.abc import Iterable

__all__ = [
    "bucket_index",
    "reliability_table",
    "expected_calibration_error",
    "brier_score",
]


def bucket_index(confidence: float, n_buckets: int = 10) -> int:
    """Map a confidence in [0, 1] to a bucket index in [0, n_buckets - 1].

    Uniform-width buckets: index ``i`` covers ``[i/n, (i+1)/n)`` except the
    final bucket, which is closed at 1.0. Raises ``ValueError`` when
    ``confidence`` is outside [0, 1] or ``n_buckets`` is less than 1.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence {confidence!r} is outside [0, 1]")
    if n_buckets < 1:
        raise ValueError(f"n_buckets must be at least 1, got {n_buckets}")
    return min(int(confidence * n_buckets), n_buckets - 1)


def reliability_table(
    pairs: Iterable[tuple[float, bool]],
    *,
    n_buckets: int = 10,
) -> list[dict]:
    """Per-bucket mean confidence and accuracy over (confidence, correct) pairs.

    Returns one ``{"bucket_lo", "bucket_hi", "n", "mean_confidence",
    "accuracy"}`` dict per non-empty bucket, ascending. ``bucket_lo`` is
    inclusive and ``bucket_hi`` exclusive, except the final bucket where the
    upper edge is inclusive at 1.0. Raises ``ValueError`` when ``pairs`` is
    empty or ``n_buckets`` is less than 1.
    """
    pairs = list(pairs)
    if not pairs:
        raise ValueError("pairs must not be empty")
    if n_buckets < 1:
        raise ValueError(f"n_buckets must be at least 1, got {n_buckets}")

    buckets: list[dict] = [
        {"lo": i / n_buckets, "hi": (i + 1) / n_buckets, "n": 0, "conf": 0.0, "acc": 0.0}
        for i in range(n_buckets)
    ]
    for confidence, correct in pairs:
        b = buckets[bucket_index(confidence, n_buckets)]
        b["n"] += 1
        b["conf"] += confidence
        b["acc"] += 1.0 if correct else 0.0

    table = []
    for i, b in enumerate(buckets):
        if b["n"] == 0:
            continue
        table.append(
            {
                "bucket_lo": b["lo"],
                "bucket_hi": b["hi"],
                "n": b["n"],
                "mean_confidence": b["conf"] / b["n"],
                "accuracy": b["acc"] / b["n"],
            }
        )
    return table


def expected_calibration_error(
    pairs: Iterable[tuple[float, bool]],
    *,
    n_buckets: int = 10,
) -> float:
    """Expected calibration error: Σ (n_b/N)·|acc_b − conf_b|.

    Empty buckets contribute nothing. Raises ``ValueError`` when ``pairs`` is
    empty or ``n_buckets`` is less than 1.
    """
    table = reliability_table(pairs, n_buckets=n_buckets)
    total = sum(row["n"] for row in table)
    return sum(row["n"] / total * abs(row["accuracy"] - row["mean_confidence"]) for row in table)


def brier_score(pairs: Iterable[tuple[float, bool]]) -> float:
    """Mean of (confidence − correct)² over (confidence, correct) pairs.

    Raises ``ValueError`` when ``pairs`` is empty.
    """
    pairs = list(pairs)
    if not pairs:
        raise ValueError("pairs must not be empty")
    return sum((conf - (1.0 if correct else 0.0)) ** 2 for conf, correct in pairs) / len(pairs)
