"""Unit tests for daf_jev.jaggedness: uniform-deviation statistics and the
run_battery instrument over the real local HTTP stub.

All numeric expectations are hand-computed in comments; the battery tests
drive the real JevClient through the conftest stub server — no patching of
daf_jev internals anywhere.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

import daf_jev
from daf_jev import ChoiceQuestion, RetryPolicy
from daf_jev.jaggedness import (
    COIN,
    COIN_NOUL,
    D6,
    JaggednessFixture,
    chi2_sf,
    max_streak,
    noul_choice_delta,
    position_slope,
    run_battery,
    runs_test_z,
    uniform_chi2,
    uniform_deviation,
)


def _battery_client(stub) -> daf_jev.JevClient:
    return daf_jev.JevClient(
        api_key="test-key",
        base_url=stub.base_url,
        sleep=lambda _seconds: None,  # injected no-op sleep; never patch internals
        retry=RetryPolicy(jitter=0.0),
        timeout=5.0,
    )


def _coin_body(heads: float, choice: str) -> dict:
    return {
        "model": "stub",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": {
            "flip": {
                "type": "choice",
                "choice": choice,
                "probabilities": {"heads": heads, "tails": round(1 - heads, 6)},
                "confidence": 0.5,
            }
        },
    }


def _noul_body(value: float) -> dict:
    return {
        "model": "stub",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": {"is_heads": {"type": "noul", "noul": value}},
    }


# ---------------------------------------------------------------- chi2_sf ---
def test_chi2_sf_matches_df2_closed_form() -> None:
    # For df=2 the sf is exactly exp(-x/2) (gamma shape a=1); both the
    # series branch (x < 4) and the continued-fraction branch must
    # reproduce it.
    for x in (0.5, 1.0, 2.718281828, 4.0, 12.0):
        assert chi2_sf(x, 2) == pytest.approx(math.exp(-x / 2), rel=1e-9)


def test_chi2_sf_reproduces_standard_critical_values() -> None:
    # The x values are the textbook chi-squared upper-0.05 critical points.
    assert chi2_sf(3.841458820694124, 1) == pytest.approx(0.05, rel=1e-6)
    assert chi2_sf(5.991464547107979, 2) == pytest.approx(0.05, rel=1e-6)
    assert chi2_sf(18.307038053275146, 10) == pytest.approx(0.05, rel=1e-6)


def test_chi2_sf_zero_is_one() -> None:
    assert chi2_sf(0.0, 5) == 1.0


def test_chi2_sf_strictly_decreasing_in_x() -> None:
    # Spans the series/fraction switch point (x = 2*(df/2 + 1) = 5 for df=3).
    values = [chi2_sf(x, 3) for x in (0.5, 1.0, 2.0, 5.0, 8.0, 16.0)]
    assert all(a > b for a, b in pairwise(values))

def test_chi2_sf_rejects_bad_arguments() -> None:
    with pytest.raises(ValueError):
        chi2_sf(-1.0, 2)
    with pytest.raises(ValueError):
        chi2_sf(1.0, 0)
    with pytest.raises(ValueError):
        chi2_sf(1.0, -3)


# ------------------------------------------------------------ uniform_chi2 ---
def test_uniform_chi2_hand_example() -> None:
    # {a: 12, b: 8}: total 20, expected 10, stat (4 + 4)/10 = 0.8, df 1.
    stat, df, p = uniform_chi2({"a": 12, "b": 8})
    assert stat == pytest.approx(0.8)
    assert df == 1
    assert p == pytest.approx(chi2_sf(0.8, 1))
    # Independent closed form for df=1: Q = erfc(sqrt(x/2)).
    assert chi2_sf(0.8, 1) == pytest.approx(math.erfc(math.sqrt(0.4)), rel=1e-9)


def test_uniform_chi2_zero_counts_keep_df_minus_one() -> None:
    # Full-outcome counts with zeros still span k=2 outcomes: {2, 0} ->
    # expected 1, stat (1 + 1)/1 = 2.0, df 1.
    stat, df, p = uniform_chi2({"heads": 2, "tails": 0})
    assert stat == pytest.approx(2.0)
    assert df == 1
    assert p == pytest.approx(chi2_sf(2.0, 1))


def test_uniform_chi2_rejects_bad_counts() -> None:
    with pytest.raises(ValueError):
        uniform_chi2({})  # empty
    with pytest.raises(ValueError):
        uniform_chi2({"a": 0, "b": 0})  # all zero
    with pytest.raises(ValueError):
        uniform_chi2({"a": 6, "b": -1})  # negative count
    with pytest.raises(ValueError):
        uniform_chi2({"a": 5})  # fewer than two outcomes


# -------------------------------------------------------- uniform_deviation ---
def test_uniform_deviation_hand_example() -> None:
    # {a: 0.7, b: 0.3} vs uniform 0.5: max_abs 0.2, tv 0.2 + 0.2 = 0.4,
    # chi2_per_n = 0.2^2/0.5 + 0.2^2/0.5 = 0.16.
    deviation = uniform_deviation({"a": 0.7, "b": 0.3})
    assert deviation["k"] == 2
    assert deviation["max_abs"] == pytest.approx(0.2)
    assert deviation["total_variation"] == pytest.approx(0.4)
    assert deviation["chi2_per_n"] == pytest.approx(0.16)


def test_uniform_deviation_single_outcome_is_perfectly_uniform() -> None:
    deviation = uniform_deviation({"a": 1.0})
    assert deviation == {
        "k": 1,
        "max_abs": pytest.approx(0.0),
        "total_variation": pytest.approx(0.0),
        "chi2_per_n": pytest.approx(0.0),
    }


def test_uniform_deviation_rejects_unnormalized_and_empty() -> None:
    with pytest.raises(ValueError):
        uniform_deviation({})
    with pytest.raises(ValueError):
        uniform_deviation({"a": 0.6, "b": 0.3})  # sums to 0.9


# --------------------------------------------------------------- runs_test_z ---
def test_runs_test_z_hand_example() -> None:
    # H T H T H T H T: n=8, n1=n2=4, R=8 runs; mu = 2*4*4/8 + 1 = 5,
    # var = (5-1)(5-2)/7 = 12/7; z = (8-5)/sqrt(12/7) = 2.2913...
    z = runs_test_z([1, 0, 1, 0, 1, 0, 1, 0])
    assert z == pytest.approx(3.0 / math.sqrt(12.0 / 7.0), rel=1e-9)
    assert z == pytest.approx(2.2913, rel=1e-3)


def test_runs_test_z_none_for_degenerate_inputs() -> None:
    assert runs_test_z([1, 1, 1, 1]) is None  # all-same
    assert runs_test_z([0, 0]) is None
    assert runs_test_z([1]) is None  # fewer than two bits
    assert runs_test_z([]) is None


def test_runs_test_z_rejects_nonbinary() -> None:
    with pytest.raises(ValueError):
        runs_test_z([1, 2, 0])
    with pytest.raises(ValueError):
        runs_test_z([0.5, 0, 1])


# --------------------------------------------------------------- max_streak ---
def test_max_streak_hand_example() -> None:
    # H T T T H T -> longest identical run is TTT = 3.
    assert max_streak([0, 1, 1, 1, 0, 1]) == 3


def test_max_streak_edges() -> None:
    assert max_streak([]) == 0
    assert max_streak([1, 1, 1]) == 3
    assert max_streak([0, 1, 0, 1]) == 1


def test_max_streak_rejects_nonbinary() -> None:
    with pytest.raises(ValueError):
        max_streak([1, 3, 1])


# ----------------------------------------------------------- position_slope ---
def test_position_slope_hand_example() -> None:
    # L stated p rises 0.1 -> 0.2 -> 0.3 across positions 0..2: slope 0.1.
    slope = position_slope([("L", 0, 0.1), ("L", 1, 0.2), ("L", 2, 0.3)])
    assert slope == pytest.approx(0.1)


def test_position_slope_averages_over_labels() -> None:
    # L rises 0.1/step (slope 0.1); M falls 0.1/step (slope -0.1); avg 0.0.
    observations = [
        ("L", 0, 0.1),
        ("L", 1, 0.2),
        ("L", 2, 0.3),
        ("M", 0, 0.9),
        ("M", 1, 0.8),
        ("M", 2, 0.7),
    ]
    assert position_slope(observations) == pytest.approx(0.0, abs=1e-9)


def test_position_slope_rejects_degenerate_geometry() -> None:
    with pytest.raises(ValueError):
        position_slope([])  # empty
    with pytest.raises(ValueError):
        position_slope([("L", 0, 0.1), ("L", 0, 0.2)])  # one distinct position
    with pytest.raises(ValueError):
        # M is only ever observed at position 0: no per-label x-variance.
        position_slope([("L", 0, 0.1), ("L", 1, 0.2), ("M", 0, 0.5)])


# -------------------------------------------------------- noul_choice_delta ---
def test_noul_choice_delta() -> None:
    assert noul_choice_delta(0.819, 0.682) == pytest.approx(0.137)
    assert noul_choice_delta(0.3, 0.7) == pytest.approx(0.4)
    assert noul_choice_delta(0.5, 0.5) == 0.0


# ----------------------------------------------------------------- fixtures ---
def test_fixture_constants_match_pinned_texts() -> None:
    assert COIN.name == "coin"
    assert COIN.state == "A fair coin is flipped once. Which face lands up?"
    assert COIN.question_id == "flip"
    assert COIN.kind == "choice"
    assert COIN.question.to_wire() == {
        "type": "choice",
        "instructions": "Which face lands up?",
        "criteria": {"heads": None, "tails": None},
    }
    assert D6.name == "d6"
    assert D6.kind == "choice"
    assert list(D6.question.to_wire()["criteria"]) == ["1", "2", "3", "4", "5", "6"]
    assert COIN_NOUL.name == "coin_noul"
    assert COIN_NOUL.kind == "noul"
    assert COIN_NOUL.question.to_wire() == {
        "type": "noul",
        "instructions": "Does the coin land heads?",
    }


def test_fixture_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        JaggednessFixture(
            name="x",
            state="s",
            question_id="q",
            kind="score",
            question=ChoiceQuestion(instructions="i", criteria={"a": None}),
        )


def test_package_exports_jaggedness_surface() -> None:
    assert daf_jev.COIN is COIN
    for name in (
        "COIN",
        "COIN_NOUL",
        "D6",
        "JaggednessFixture",
        "chi2_sf",
        "max_streak",
        "noul_choice_delta",
        "position_slope",
        "run_battery",
        "runs_test_z",
        "uniform_chi2",
        "uniform_deviation",
    ):
        assert name in daf_jev.__all__
        assert hasattr(daf_jev, name)


# -------------------------------------------------------------- run_battery ---
def test_run_battery_rejects_bad_configuration(stub) -> None:
    client = _battery_client(stub)
    try:
        with pytest.raises(ValueError):
            run_battery(client, COIN, repeats=0)
        with pytest.raises(ValueError):
            run_battery(client, COIN, concurrent=0)
        with pytest.raises(ValueError):
            run_battery(client, [])
        with pytest.raises(ValueError):
            run_battery(client, [COIN, COIN])  # duplicate fixture names
        assert stub.hits == []  # validation happens before any ask
    finally:
        client.close()


def test_run_battery_coin_deterministic_server(stub) -> None:
    # Same response on every hit: a deterministic server answers identical
    # asks with one point mass, so degeneracy is the measured finding.
    repeats = 4
    for _ in range(repeats + 4):  # sequential + 2 order asks + 2 concurrent
        stub.enqueue(body=_coin_body(0.68, "heads"))
    client = _battery_client(stub)
    try:
        battery = run_battery(client, COIN, repeats=repeats, concurrent=2, timeout=5.0)
    finally:
        client.close()

    coin = battery["coin"]
    assert coin["n_outcomes"] == 2
    assert coin["repeats"] == 4
    assert coin["n_errors"] == 0
    assert coin["choice_counts"] == {"heads": 4, "tails": 0}
    assert coin["degenerate"] is True
    # counts {heads: 4, tails: 0}: total 4, expected 2,
    # stat (4-2)^2/2 + (0-2)^2/2 = 4.0.
    assert coin["uniform_chi2"]["stat"] == pytest.approx(4.0)
    assert coin["uniform_chi2"]["p"] == round(chi2_sf(4.0, 1), 6)  # battery rounds to 6 decimals
    assert coin["prob_mean"] == {"heads": 0.68, "tails": 0.32}
    assert coin["prob_std"] == {"heads": 0.0, "tails": 0.0}
    assert coin["wobble_max"] == 0.0
    # means (0.68, 0.32) vs uniform 0.5: max_abs 0.18, tv 0.36,
    # chi2_per_n = 2 * 0.18^2/0.5 = 0.1296.
    assert coin["uniform_deviation"] == {
        "k": 2,
        "max_abs": pytest.approx(0.18),
        "total_variation": pytest.approx(0.36),
        "chi2_per_n": pytest.approx(0.1296),
    }
    assert coin["runs_z"] is None  # all bits identical -> degenerate statistic
    assert coin["max_streak"] == repeats
    orders = coin["orders"]
    assert orders["n"] == 2  # rotations + reversal deduped
    assert orders["position_bias_slope"] == pytest.approx(0.0)
    assert orders["order_shift_max"] == 0.0
    assert orders["argmax_flips"] == 0
    assert coin["concurrent"] == {"n": 2, "wobble_max": 0.0, "distinct": 1}
    assert len(stub.hits) == repeats + 4
    # Order-study wire shape: criteria insertion order follows the rotation
    # (base first, then reversed), while state/instructions stay identical.
    order_keys = [
        list(hit["json"]["questions"]["flip"]["criteria"].keys())
        for hit in stub.hits[repeats : repeats + 2]
    ]
    assert order_keys == [["heads", "tails"], ["tails", "heads"]]


def test_run_battery_coin_varying_responses(stub) -> None:
    # Scripted per-hit probabilities; every stat below is hand-computed
    # over the four sequential vectors, the 2 order asks, then the 2
    # concurrent asks.
    sequential = [(0.6, "heads"), (0.5, "tails"), (0.7, "heads"), (0.6, "heads")]
    for heads, choice in sequential:
        stub.enqueue(body=_coin_body(heads, choice))
    stub.enqueue(body=_coin_body(0.6, "heads"))  # order ask: base rotation
    stub.enqueue(body=_coin_body(0.1, "tails"))  # order ask: reversed
    for _ in range(2):
        stub.enqueue(body=_coin_body(0.65, "heads"))  # concurrent batch
    client = _battery_client(stub)
    try:
        battery = run_battery(client, COIN, repeats=4, concurrent=2, timeout=5.0)
    finally:
        client.close()

    coin = battery["coin"]
    assert coin["n_errors"] == 0
    assert coin["choice_counts"] == {"heads": 3, "tails": 1}
    assert coin["degenerate"] is False
    # counts {3, 1}: expected 2, stat (1 + 1)/2 = 1.0.
    assert coin["uniform_chi2"]["stat"] == pytest.approx(1.0)
    assert coin["uniform_chi2"]["df"] == 1
    assert coin["uniform_chi2"]["p"] == round(chi2_sf(1.0, 1), 6)  # battery rounds to 6 decimals
    # Sequential means: heads (0.6+0.5+0.7+0.6)/4 = 0.6, tails 0.4; each
    # label's population std = sqrt((0 + 0.01 + 0.01 + 0)/4) = sqrt(0.005)
    # = 0.070711 (rounded to 6 decimals).
    assert coin["prob_mean"] == {"heads": pytest.approx(0.6), "tails": pytest.approx(0.4)}
    assert coin["prob_std"]["heads"] == pytest.approx(0.070711)
    assert coin["prob_std"]["tails"] == pytest.approx(0.070711)
    # max pairwise |Δp| per label = 0.7 - 0.5 = 0.2.
    assert coin["wobble_max"] == pytest.approx(0.2)
    # means vs uniform 0.5: max_abs 0.1, tv 0.2, chi2_per_n = 0.02/0.5.
    assert coin["uniform_deviation"]["max_abs"] == pytest.approx(0.1)
    assert coin["uniform_deviation"]["total_variation"] == pytest.approx(0.2)
    assert coin["uniform_deviation"]["chi2_per_n"] == pytest.approx(0.04)
    # Modal heads (3 vs 1) -> bits [1, 0, 1, 1]: R=3, n1=3, n2=1,
    # mu = 2*3*1/4 + 1 = 2.5, var = 1.5*0.5/3 = 0.25, z = 0.5/0.5 = 1.0.
    assert coin["runs_z"] == pytest.approx(1.0)
    assert coin["max_streak"] == 2
    orders = coin["orders"]
    assert orders["n"] == 2
    # heads: 0.6 at position 0 (base), 0.1 at position 1 (reversed) -> slope
    # -0.5; tails: 0.4 at position 1, 0.9 at position 0 -> slope -0.5.
    assert orders["position_bias_slope"] == pytest.approx(-0.5)
    # |0.1 - 0.6| = 0.5 and |0.9 - 0.4| = 0.5.
    assert orders["order_shift_max"] == pytest.approx(0.5)
    # Base argmax heads; reversed argmax tails -> one flip.
    assert orders["argmax_flips"] == 1
    # Concurrent 0.65/0.35 vs sequential means 0.6/0.4 -> |Δ| 0.05 per
    # label; both vectors identical -> one distinct tuple.
    assert coin["concurrent"] == {
        "n": 2,
        "wobble_max": pytest.approx(0.05),
        "distinct": 1,
    }


def test_run_battery_failure_isolation(stub) -> None:
    # One 500 in the sequential loop, good asks around it, the reversed
    # order rotation 500s, and both concurrent asks 500. Status 500 is not
    # retryable, so each failed program is exactly one hit.
    stub.enqueue(status=500, text="upstream exploded", content_type="text/plain")
    stub.enqueue(body=_coin_body(0.6, "heads"))
    stub.enqueue(body=_coin_body(0.6, "heads"))
    stub.enqueue(body=_coin_body(0.6, "heads"))  # order ask: base rotation
    stub.enqueue(status=500, text="boom", content_type="text/plain")  # reversed
    stub.enqueue(status=500, text="boom", content_type="text/plain")  # concurrent
    stub.enqueue(status=500, text="boom", content_type="text/plain")  # concurrent
    client = _battery_client(stub)
    try:
        battery = run_battery(client, COIN, repeats=3, concurrent=2, timeout=5.0)
    finally:
        client.close()

    coin = battery["coin"]
    assert coin["n_errors"] == 4  # 1 sequential + 1 order + 2 concurrent
    assert coin["choice_counts"] == {"heads": 2, "tails": 0}
    assert coin["degenerate"] is True
    # counts {2, 0}: expected 1, stat (1 + 1)/1 = 2.0.
    assert coin["uniform_chi2"]["stat"] == pytest.approx(2.0)
    assert coin["prob_mean"] == {"heads": pytest.approx(0.6), "tails": pytest.approx(0.4)}
    assert coin["prob_std"] == {"heads": 0.0, "tails": 0.0}
    assert coin["wobble_max"] == 0.0
    # means (0.6, 0.4) vs uniform 0.5: max_abs 0.1, tv 0.2, chi2_per_n 0.04.
    assert coin["uniform_deviation"]["max_abs"] == pytest.approx(0.1)
    assert coin["uniform_deviation"]["total_variation"] == pytest.approx(0.2)
    assert coin["uniform_deviation"]["chi2_per_n"] == pytest.approx(0.04)
    assert coin["runs_z"] is None
    assert coin["max_streak"] == 2
    orders = coin["orders"]
    assert orders["n"] == 1  # only the base rotation succeeded
    assert "position_bias_slope" not in orders  # one order -> no defined slope
    assert orders["order_shift_max"] == 0.0
    assert orders["argmax_flips"] == 0
    assert "concurrent" not in coin  # both concurrent asks failed


def test_run_battery_all_asks_fail_leaves_derived_keys_absent(stub) -> None:
    # The order study is self-contained and still runs (both of its asks
    # fail); the concurrent batch is skipped without a sequential baseline,
    # so only 5 of the 7 queued programs are consumed.
    for _ in range(3 + 2 + 2):  # sequential + 2 order asks + 2 concurrent
        stub.enqueue(status=500, text="boom", content_type="text/plain")
    client = _battery_client(stub)
    try:
        battery = run_battery(client, COIN, repeats=3, concurrent=2, timeout=5.0)
    finally:
        client.close()

    coin = battery["coin"]
    assert coin["n_errors"] == 5  # 3 sequential + 2 order-rotation failures
    assert len(stub.hits) == 5  # concurrent batch never issued
    for absent in (
        "choice_counts",
        "degenerate",
        "uniform_chi2",
        "prob_mean",
        "prob_std",
        "wobble_max",
        "uniform_deviation",
        "runs_z",
        "max_streak",
        "orders",
        "concurrent",
    ):
        assert absent not in coin


def test_run_battery_noul_path(stub) -> None:
    for value in (0.8, 0.6, 0.9, 0.7):
        stub.enqueue(body=_noul_body(value))
    stub.enqueue(body=_noul_body(0.75))  # concurrent batch: 0.75 then 0.8
    stub.enqueue(body=_noul_body(0.8))
    stub.enqueue(body=_noul_body(0.8))  # leftover: must NOT be consumed
    client = _battery_client(stub)
    try:
        battery = run_battery(
            client, COIN_NOUL, repeats=4, concurrent=2, timeout=5.0
        )
    finally:
        client.close()

    noul = battery["coin_noul"]
    assert noul["kind"] == "noul"
    assert noul["repeats"] == 4
    assert noul["n_errors"] == 0
    # mean of (0.8, 0.6, 0.9, 0.7) = 0.75; population var
    # (0.05^2 + 0.15^2 + 0.15^2 + 0.05^2)/4 = 0.0125 -> std 0.111803.
    assert noul["noul_mean"] == pytest.approx(0.75)
    assert noul["noul_std"] == pytest.approx(math.sqrt(0.0125), rel=1e-5)
    assert noul["noul_min"] == pytest.approx(0.6)
    assert noul["noul_max"] == pytest.approx(0.9)
    assert "orders" not in noul  # the order study is choice-only
    # Concurrent vs mean 0.75: |0.75-0.75| = 0 and |0.8-0.75| = 0.05;
    # distinct rounded values {0.75, 0.8}.
    assert noul["concurrent"] == {
        "n": 2,
        "wobble_max": pytest.approx(0.05),
        "distinct": 2,
    }
    # The leftover program proves exactly 6 asks were issued (7 enqueued).
    assert len(stub.hits) == 6
