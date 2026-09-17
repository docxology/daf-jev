"""Unit tests for daf_jev.calibration: pure bucketing/ECE math, no I/O."""

from __future__ import annotations

import pytest

from daf_jev.calibration import (
    bucket_index,
    brier_score,
    expected_calibration_error,
    reliability_table,
)
import math

# Hand-computed fixture shared by the table and ECE tests:
# buckets of size 0.5 over [(0.1, F), (0.2, T), (0.7, T), (0.8, T), (0.8, F)]
#   bucket 0 [0.0, 0.5): confidences 0.1, 0.2   -> n=2, mean 0.15, acc 0.5
#   bucket 1 [0.5, 1.0]: confidences 0.7, 0.8, 0.8 -> n=3, mean 23/30, acc 2/3
_PAIRS = [(0.1, False), (0.2, True), (0.7, True), (0.8, True), (0.8, False)]


# ------------------------------------------------------------ bucket_index ---
def test_bucket_index_scales_confidence_into_buckets() -> None:
    assert bucket_index(0.0, 10) == 0
    assert bucket_index(0.35, 10) == 3
    assert bucket_index(0.5, 10) == 5  # exact edge belongs to the upper bucket
    assert bucket_index(0.999, 10) == 9


def test_bucket_index_clamps_one_point_zero() -> None:
    # 1.0 maps to bucket n, which is clamped back into the last bucket.
    assert bucket_index(1.0, 10) == 9
    assert bucket_index(1.0, 4) == 3


def test_bucket_index_single_bucket() -> None:
    assert bucket_index(0.0, 1) == 0
    assert bucket_index(1.0, 1) == 0


def test_bucket_index_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        bucket_index(-0.01, 10)
    with pytest.raises(ValueError):
        bucket_index(1.01, 10)


def test_bucket_index_rejects_invalid_bucket_count() -> None:
    with pytest.raises(ValueError):
        bucket_index(0.5, 0)
    with pytest.raises(ValueError):
        bucket_index(0.5, -3)


# -------------------------------------------------------- reliability_table ---
def test_reliability_table_bucket_math() -> None:
    table = reliability_table(_PAIRS, n_buckets=2)
    assert table == [
        {
            "bucket_lo": 0.0,
            "bucket_hi": 0.5,
            "n": 2,
            "mean_confidence": pytest.approx(0.15),
            "accuracy": pytest.approx(0.5),
        },
        {
            "bucket_lo": 0.5,
            "bucket_hi": 1.0,
            "n": 3,
            "mean_confidence": pytest.approx(23.0 / 30.0),
            "accuracy": pytest.approx(2.0 / 3.0),
        },
    ]


def test_reliability_table_omits_empty_buckets_and_is_ascending() -> None:
    # With ten buckets only buckets 0 and 9 are populated: the eight empty
    # middle buckets must not appear.
    table = reliability_table([(0.05, True), (0.95, False)], n_buckets=10)
    assert [row["n"] for row in table] == [1, 1]
    assert [row["bucket_lo"] for row in table] == pytest.approx([0.0, 0.9])
    assert [row["bucket_hi"] for row in table] == pytest.approx([0.1, 1.0])
    assert table[0]["accuracy"] == pytest.approx(1.0)
    assert table[1]["accuracy"] == pytest.approx(0.0)


def test_reliability_table_covers_confidence_one_point_zero() -> None:
    # 1.0 clamps into the last bucket, whose upper edge is 1.0.
    table = reliability_table([(1.0, True)], n_buckets=4)
    assert len(table) == 1
    assert table[0]["bucket_lo"] == pytest.approx(0.75)
    assert table[0]["bucket_hi"] == pytest.approx(1.0)
    assert table[0]["n"] == 1


# --------------------------------------------- expected_calibration_error ---
def test_expected_calibration_error_hand_computed() -> None:
    # (2/5)*|0.5 - 0.15| + (3/5)*|2/3 - 23/30| = 0.14 + 0.06 = 0.2
    assert expected_calibration_error(_PAIRS, n_buckets=2) == pytest.approx(0.2)


def test_expected_calibration_error_zero_when_perfectly_calibrated() -> None:
    pairs = [(0.5, False), (0.5, True)]
    assert expected_calibration_error(pairs, n_buckets=1) == pytest.approx(0.0)


def test_expected_calibration_error_rejects_empty_pairs() -> None:
    with pytest.raises(ValueError):
        expected_calibration_error([], n_buckets=2)


# --------------------------------------------------------------- brier_score ---
def test_brier_score_hand_computed() -> None:
    pairs = [(0.8, True), (0.6, False), (1.0, True)]
    # (0.8-1)^2 + (0.6-0)^2 + (1.0-1)^2 = 0.04 + 0.36 + 0.0
    assert brier_score(pairs) == pytest.approx(0.4 / 3.0)


def test_brier_score_bounds() -> None:
    assert brier_score([(0.0, True)]) == pytest.approx(1.0)
    assert brier_score([(1.0, True)]) == pytest.approx(0.0)


def test_brier_score_rejects_empty_pairs() -> None:
    with pytest.raises(ValueError):
        brier_score([])
