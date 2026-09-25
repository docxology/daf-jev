"""Model jaggedness: how far a model's stated distributions stray from fair.

Repeated identical asks of a stochastic prompt (a coin flip, a die roll)
turn a model into a sampleable source: each ask returns the chosen label
plus the stated outcome distribution. A fair stochastic process implies a
uniform distribution over the outcomes, so jaggedness is every measurable
way the model deviates from that uniform: stated probabilities biased away
from ``1/k``, sensitivity to the order in which options are presented, and
degeneracy (the same label chosen on every ask). System One returns typed
distributions per ask and is deterministic per identical input, so a
deterministic server answers every identical ask with the same point mass —
degeneracy is itself a measured finding, while order-permutation
sensitivity and stated-probability bias carry the real signal.

The statistics are pure (stdlib ``math`` only). :func:`run_battery` drives
a duck-typed ``ask`` client and reduces its responses to the pinned battery
schema. No I/O beyond the calls made through the injected client.
"""

import contextlib
import dataclasses
import math
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from typing import Any

from daf_jev._types import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    JSONContent,
    NoulAnswer,
    NoulQuestion,
    Question,
)

__all__ = [
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
]


# ---------------------------------------------------------------------------
# Chi-squared survival function
# ---------------------------------------------------------------------------

# Numerical-Recipes incomplete-gamma constants shared by the series and the
# Lentz continued fraction used by :func:`chi2_sf`.
_GAMMA_EPS = 1e-14
_GAMMA_MAX_ITER = 200
_GAMMA_FPMIN = 1e-300


def _gamma_q_series(a: float, x: float) -> float:
    """Q(a, x) for small x (x < a + 1) from the convergent series for P."""
    ap = a
    total = 1.0 / a
    term = total
    for _ in range(_GAMMA_MAX_ITER):
        ap += 1.0
        term *= x / ap
        total += term
        if abs(term) < abs(total) * _GAMMA_EPS:
            break
    return 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_q_fraction(a: float, x: float) -> float:
    """Q(a, x) for large x (x >= a + 1) via the Lentz continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _GAMMA_FPMIN
    d = 1.0 / b
    h = d
    for i in range(1, _GAMMA_MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _GAMMA_FPMIN:
            d = _GAMMA_FPMIN
        c = b + an / c
        if abs(c) < _GAMMA_FPMIN:
            c = _GAMMA_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _GAMMA_EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x: float, df: int) -> float:
    """Survival function of the chi-squared distribution: Q(df/2, x/2).

    Upper regularized incomplete gamma via the Numerical-Recipes pair — a
    convergent series below the switch point (x/2 < df/2 + 1) and a Lentz
    continued fraction above it, with eps 1e-14 and at most 200
    iterations. ``Q(0, df)`` is exactly 1. Raises ``ValueError`` when
    ``x`` is negative or ``df`` is not positive.
    """
    if x < 0:
        raise ValueError(f"x must be non-negative, got {x!r}")
    if df <= 0:
        raise ValueError(f"df must be positive, got {df!r}")
    if x == 0.0:
        return 1.0
    a = df / 2.0
    argument = x / 2.0
    if argument < a + 1.0:
        return _gamma_q_series(a, argument)
    return _gamma_q_fraction(a, argument)


# ---------------------------------------------------------------------------
# Uniformity statistics
# ---------------------------------------------------------------------------


def uniform_chi2(counts: Mapping[str, int]) -> tuple[float, int, float]:
    """Chi-squared goodness-of-fit of observed counts against uniformity.

    The expected count is ``total / k`` over **all** keys present (zeros
    included, as :func:`run_battery` guarantees), with ``df = k - 1``.
    Returns ``(stat, df, p)`` where ``p = chi2_sf(stat, df)``. Raises
    ``ValueError`` when ``counts`` is empty, any count is negative, the
    total is zero, or fewer than two outcomes are present.
    """
    if not counts:
        raise ValueError("counts must not be empty")
    for label, count in counts.items():
        if count < 0:
            raise ValueError(f"count for {label!r} is negative: {count}")
    total = sum(counts.values())
    if total == 0:
        raise ValueError("counts must not all be zero")
    k = len(counts)
    if k < 2:
        raise ValueError(f"counts must span at least 2 outcomes, got {k}")
    expected = total / k
    stat = sum((count - expected) ** 2 for count in counts.values()) / expected
    df = k - 1
    return stat, df, chi2_sf(stat, df)


def uniform_deviation(probs: Mapping[str, float]) -> dict[str, Any]:
    """Deviation of a stated distribution from the uniform over its labels.

    Returns ``{"k", "max_abs", "total_variation", "chi2_per_n"}``:
    ``max_abs`` is the largest ``|p - 1/k|``, ``total_variation`` is the
    total absolute deviation ``Σ|p - 1/k|`` (twice the classical TV
    distance), and ``chi2_per_n`` is the dimensionless
    ``Σ(p - 1/k)² / (1/k)`` — multiplying it by ``n`` draws reproduces the
    chi-squared statistic of ``n`` uniform draws. Raises ``ValueError``
    when ``probs`` is empty or does not sum to 1 within 1e-6.
    """
    if not probs:
        raise ValueError("probs must not be empty")
    total = sum(probs.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"probs must sum to 1, got {total!r}")
    k = len(probs)
    uniform = 1.0 / k
    deviations = [p - uniform for p in probs.values()]
    return {
        "k": k,
        "max_abs": max(abs(d) for d in deviations),
        "total_variation": sum(abs(d) for d in deviations),
        "chi2_per_n": sum(d * d for d in deviations) / uniform,
    }


def runs_test_z(bits: Sequence[int]) -> float | None:
    """Wald-Wolfowitz runs-test z-score over 0/1 bits.

    Counts ``R`` runs against the null of independent fair bits with
    ``mu = 2·n1·n2/n + 1`` and ``var = (mu - 1)(mu - 2)/(n - 1)``, with no
    continuity correction. Returns ``None`` when the bits are all
    identical, there are fewer than two bits, or the variance is not
    positive (the statistic is degenerate). Raises ``ValueError`` when any
    value is not 0 or 1.
    """
    for bit in bits:
        if bit not in (0, 1):
            raise ValueError(f"bits must be 0/1, got {bit!r}")
    n = len(bits)
    if n < 2:
        return None
    n1 = sum(bits)
    n2 = n - n1
    if n1 == 0 or n2 == 0:
        return None
    runs = 1 + sum(1 for left, right in pairwise(bits) if left != right)
    mu = 2 * n1 * n2 / n + 1
    var = (mu - 1) * (mu - 2) / (n - 1)
    if var <= 0:
        return None
    return (runs - mu) / math.sqrt(var)


def max_streak(bits: Sequence[int]) -> int:
    """Longest run of identical values in a 0/1 bit sequence (0 when empty).

    Raises ``ValueError`` when any value is not 0 or 1.
    """
    for bit in bits:
        if bit not in (0, 1):
            raise ValueError(f"bits must be 0/1, got {bit!r}")
    longest = 0
    current = 0
    previous: int | None = None
    for bit in bits:
        current = current + 1 if bit == previous else 1
        longest = max(longest, current)
        previous = bit
    return longest


def position_slope(observations: Sequence[tuple[str, int, float]]) -> float:
    """Order-sensitivity slope of stated probabilities against position.

    Each observation is ``(label, position, probability)``. The OLS slope
    of probability against 0-based position is computed per label and
    averaged over labels; a non-zero slope means the stated probability
    tracks where an option was presented rather than the outcome itself.
    Raises ``ValueError`` when ``observations`` is empty, spans fewer than
    two distinct positions, or leaves any label with zero x-variance (a
    label seen at a single repeated position has no defined slope).
    """
    if not observations:
        raise ValueError("observations must not be empty")
    by_label: dict[str, list[tuple[int, float]]] = {}
    positions: list[int] = []
    for label, position, probability in observations:
        by_label.setdefault(label, []).append((position, probability))
        positions.append(position)
    if len(set(positions)) < 2:
        raise ValueError(
            "observations must span at least 2 distinct positions, "
            f"got {len(set(positions))}"
        )
    slopes: list[float] = []
    for points in by_label.values():
        x_mean = sum(x for x, _ in points) / len(points)
        y_mean = sum(y for _, y in points) / len(points)
        sxx = sum((x - x_mean) ** 2 for x, _ in points)
        if sxx == 0.0:
            raise ValueError(
                "label observed at a single repeated position; "
                "per-label x-variance is zero"
            )
        sxy = sum((x - x_mean) * (y - y_mean) for x, y in points)
        slopes.append(sxy / sxx)
    return sum(slopes) / len(slopes)


def noul_choice_delta(noul_p: float, choice_p: float) -> float:
    """Absolute gap between the noul (yes/no) and choice phrasings of the
    same underlying question: ``|noul_p - choice_p|``.

    No validation beyond the argument types — both numbers are used as
    given.
    """
    return abs(noul_p - choice_p)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class JaggednessFixture:
    """One stochastic prompt ready for repeated asking through a client.

    ``kind`` is ``"choice"`` (typed distribution over named options) or
    ``"noul"`` (a single yes/no value); ``question`` matches that kind.
    """

    name: str
    state: JSONContent
    question_id: str
    kind: str
    question: Question

    def __post_init__(self) -> None:
        if self.kind not in ("choice", "noul"):
            raise ValueError(f"kind must be 'choice' or 'noul', got {self.kind!r}")


COIN = JaggednessFixture(
    name="coin",
    state="A fair coin is flipped once. Which face lands up?",
    question_id="flip",
    kind="choice",
    question=ChoiceQuestion(
        instructions="Which face lands up?",
        criteria={"heads": None, "tails": None},
    ),
)

D6 = JaggednessFixture(
    name="d6",
    state="A fair six-sided die is rolled once. Which number comes up?",
    question_id="roll",
    kind="choice",
    question=ChoiceQuestion(
        instructions="Which number comes up?",
        criteria={"1": None, "2": None, "3": None, "4": None, "5": None, "6": None},
    ),
)

COIN_NOUL = JaggednessFixture(
    name="coin_noul",
    state="A fair coin is flipped once.",
    question_id="is_heads",
    kind="noul",
    question=NoulQuestion(instructions="Does the coin land heads?"),
)


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-6


def _round6(value: float) -> float:
    """Round one battery float to the pinned 6-decimal precision."""
    return round(value, 6)


def _round6_or_none(value: float | None) -> float | None:
    return None if value is None else _round6(value)


def _ask_once(
    client: Any,
    state: JSONContent,
    question_id: str,
    question: Question,
    timeout: float | None,
) -> Answer:
    """One duck-typed ask; the asked question_id must come back answered."""
    response = client.ask(state, {question_id: question}, timeout=timeout)
    return response.answers[question_id]


def _choice_vector(
    fixture: JaggednessFixture, answer: Answer
) -> tuple[str, dict[str, float]]:
    """Normalize one answer into ``(chosen, {label: stated p})`` over all
    criteria labels in wire order, or raise ``ValueError`` for wire
    violations (the battery counts those as errors, like transport
    failures).
    """
    question = fixture.question
    if not isinstance(question, ChoiceQuestion):
        raise ValueError(f"fixture {fixture.name!r} is not a choice fixture")
    if not isinstance(answer, ChoiceAnswer):
        raise ValueError(f"expected a choice answer, got {type(answer).__name__}")
    labels = list(question.criteria)
    missing = [label for label in labels if label not in answer.probabilities]
    if missing:
        raise ValueError(f"choice answer is missing probabilities for {missing}")
    if answer.choice not in question.criteria:
        raise ValueError(f"choice {answer.choice!r} is not one of {labels}")
    return answer.choice, {label: answer.probabilities[label] for label in labels}


def _noul_value(answer: Answer) -> float:
    """Extract the noul value from one answer, or raise ``ValueError``."""
    if not isinstance(answer, NoulAnswer):
        raise ValueError(f"expected a noul answer, got {type(answer).__name__}")
    return answer.noul


def _option_orders(labels: list[str]) -> list[list[str]]:
    """Cyclic rotations of the base option order plus its reversal, deduped
    preserving first occurrence (two options -> 2 orders, six -> 7).
    """
    orders = [labels[i:] + labels[:i] for i in range(len(labels))]
    orders.append(labels[::-1])
    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for order in orders:
        key = tuple(order)
        if key not in seen:
            seen.add(key)
            unique.append(order)
    return unique


def _argmax(order: Sequence[str], vector: Mapping[str, float]) -> str:
    """Highest-probability label; ties go to the earliest in ``order``."""
    best = order[0]
    for label in order[1:]:
        if vector[label] > vector[best]:
            best = label
    return best


def _modal_count(chosen_labels: Sequence[str]) -> str:
    """Most common chosen label; ties go to the first occurrence."""
    counts: dict[str, int] = {}
    for chosen in chosen_labels:
        counts[chosen] = counts.get(chosen, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _choice_battery(
    client: Any,
    fixture: JaggednessFixture,
    repeats: int,
    concurrent: int,
    timeout: float | None,
) -> dict[str, Any]:
    """Reduce a choice fixture to the pinned battery dict (see
    :func:`run_battery` for the schema and absence rules).
    """
    question = fixture.question
    if not isinstance(question, ChoiceQuestion):
        raise ValueError(f"fixture {fixture.name!r} is not a choice fixture")
    labels = list(question.criteria)
    battery: dict[str, Any] = {
        "fixture": fixture.name,
        "kind": "choice",
        "n_outcomes": len(labels),
        "repeats": repeats,
    }

    # Sequential identical asks.
    chosen_labels: list[str] = []
    vectors: list[dict[str, float]] = []
    n_errors = 0
    for _ in range(repeats):
        try:
            chosen, vector = _choice_vector(
                fixture,
                _ask_once(
                    client, fixture.state, fixture.question_id, question, timeout
                ),
            )
        except Exception:
            n_errors += 1
            continue
        chosen_labels.append(chosen)
        vectors.append(vector)
    battery["n_errors"] = n_errors

    # Order-permutation study: one ask per rotation/reversal, question
    # rebuilt so the wire criteria insertion order matches the rotation.
    order_results: list[tuple[list[str], dict[str, float]]] = []
    orders: dict[str, Any] = {}
    for order in _option_orders(labels):
        rotated = ChoiceQuestion(
            instructions=question.instructions,
            criteria={label: question.criteria[label] for label in order},
        )
        try:
            _chosen, vector = _choice_vector(
                fixture,
                _ask_once(
                    client, fixture.state, fixture.question_id, rotated, timeout
                ),
            )
        except Exception:
            battery["n_errors"] += 1
            continue
        order_results.append((order, vector))
    if order_results:
        orders["n"] = len(order_results)
        triples = [
            (label, order.index(label), vector[label])
            for order, vector in order_results
            for label in order
        ]
        with contextlib.suppress(ValueError):
            orders["position_bias_slope"] = _round6(position_slope(triples))
        base_order, base_vector = order_results[0]
        if base_order == labels:  # the base rotation itself succeeded
            orders["order_shift_max"] = _round6(
                max(
                    abs(vector[label] - base_vector[label])
                    for _order, vector in order_results
                    for label in base_order
                )
            )
            base_argmax = _argmax(base_order, base_vector)
            orders["argmax_flips"] = sum(
                1
                for order, vector in order_results
                if _argmax(order, vector) != base_argmax
            )
    if orders:
        battery["orders"] = orders

    if not chosen_labels:
        # Every sequential ask failed: observation-derived keys stay absent.
        return battery

    counts = {label: 0 for label in labels}
    for chosen in chosen_labels:
        counts[chosen] += 1
    battery["choice_counts"] = counts
    battery["degenerate"] = len(set(chosen_labels)) == 1

    prob_mean = {
        label: sum(vector[label] for vector in vectors) / len(vectors)
        for label in labels
    }
    prob_std = {
        label: math.sqrt(
            sum((vector[label] - prob_mean[label]) ** 2 for vector in vectors)
            / len(vectors)
        )
        for label in labels
    }
    battery["prob_mean"] = {label: _round6(p) for label, p in prob_mean.items()}
    battery["prob_std"] = {label: _round6(p) for label, p in prob_std.items()}
    battery["wobble_max"] = _round6(
        max(
            max(vector[label] for vector in vectors)
            - min(vector[label] for vector in vectors)
            for label in labels
        )
    )

    if len(labels) < 2:
        battery["uniform_chi2"] = None
    else:
        stat, df, p_value = uniform_chi2(counts)
        battery["uniform_chi2"] = {
            "stat": _round6(stat),
            "df": df,
            "p": _round6(p_value),
        }

    try:
        deviation = uniform_deviation(prob_mean)
    except ValueError:
        pass  # stated means do not normalize; the key stays absent
    else:
        battery["uniform_deviation"] = {
            key: value if isinstance(value, int) else _round6(value)
            for key, value in deviation.items()
        }

    bits = [1 if chosen == _modal_count(chosen_labels) else 0 for chosen in chosen_labels]
    battery["runs_z"] = _round6_or_none(runs_test_z(bits))
    battery["max_streak"] = max_streak(bits)

    # Concurrent batch: identical asks on worker threads, compared against
    # the sequential means.
    def _concurrent_ask(_index: int) -> tuple[str, dict[str, float]]:
        return _choice_vector(
            fixture,
            _ask_once(
                client, fixture.state, fixture.question_id, question, timeout
            ),
        )

    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = [
            executor.submit(_concurrent_ask, index) for index in range(concurrent)
        ]
    concurrent_vectors: list[dict[str, float]] = []
    n_concurrent_errors = 0
    for future in futures:
        try:
            _chosen, vector = future.result()
        except Exception:
            n_concurrent_errors += 1  # failed asks count, like sequential ones
            continue
        concurrent_vectors.append(vector)
    battery["n_errors"] += n_concurrent_errors
    if concurrent_vectors:
        battery["concurrent"] = {
            "n": len(concurrent_vectors),
            "wobble_max": _round6(
                max(
                    abs(vector[label] - prob_mean[label])
                    for vector in concurrent_vectors
                    for label in labels
                )
            ),
            "distinct": len(
                {
                    tuple(_round6(vector[label]) for label in labels)
                    for vector in concurrent_vectors
                }
            ),
        }
    return battery


def _noul_battery(
    client: Any,
    fixture: JaggednessFixture,
    repeats: int,
    concurrent: int,
    timeout: float | None,
) -> dict[str, Any]:
    """Reduce a noul fixture to the pinned battery dict (see
    :func:`run_battery` for the schema and absence rules).
    """
    battery: dict[str, Any] = {
        "fixture": fixture.name,
        "kind": "noul",
        "repeats": repeats,
    }
    values: list[float] = []
    n_errors = 0
    for _ in range(repeats):
        try:
            values.append(
                _noul_value(
                    _ask_once(
                        client,
                        fixture.state,
                        fixture.question_id,
                        fixture.question,
                        timeout,
                    )
                )
            )
        except Exception:
            n_errors += 1
    battery["n_errors"] = n_errors
    if not values:
        return battery  # every sequential ask failed; derived keys stay absent

    mean = sum(values) / len(values)
    battery["noul_mean"] = _round6(mean)
    battery["noul_std"] = _round6(
        math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    )
    battery["noul_min"] = _round6(min(values))
    battery["noul_max"] = _round6(max(values))

    def _concurrent_noul(_index: int) -> float:
        return _noul_value(
            _ask_once(
                client,
                fixture.state,
                fixture.question_id,
                fixture.question,
                timeout,
            )
        )

    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = [
            executor.submit(_concurrent_noul, index) for index in range(concurrent)
        ]
    concurrent_values: list[float] = []
    n_concurrent_errors = 0
    for future in futures:
        try:
            concurrent_values.append(future.result())
        except Exception:
            n_concurrent_errors += 1  # failed asks count, like sequential ones
    battery["n_errors"] += n_concurrent_errors
    if concurrent_values:
        battery["concurrent"] = {
            "n": len(concurrent_values),
            "wobble_max": _round6(
                max(abs(value - mean) for value in concurrent_values)
            ),
            "distinct": len({_round6(value) for value in concurrent_values}),
        }
    return battery


def run_battery(
    client: Any,
    fixtures: Iterable[JaggednessFixture] | JaggednessFixture,
    *,
    repeats: int = 50,
    concurrent: int = 32,
    timeout: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Measure jaggedness of one or more fixtures against a duck-typed ask
    client, returning ``{fixture name: battery}``.

    ``client`` needs only ``ask(state, {question_id: question},
    timeout=...) -> SystemOneResponse``; :class:`JevClient` qualifies. A
    single ``JaggednessFixture`` may be passed instead of an iterable.

    Every float in the returned dicts is rounded to 6 decimals. A choice
    battery carries ``fixture``, ``kind``, ``n_outcomes``, ``repeats``,
    ``n_errors``, ``choice_counts`` (full outcome set, zeros included),
    ``degenerate``, ``uniform_chi2`` (``{"stat", "df", "p"}`` or ``None``
    iff ``k < 2``), ``prob_mean``, ``prob_std``, ``wobble_max``,
    ``uniform_deviation``, ``runs_z``, ``max_streak``, ``orders``
    (``{"n", "position_bias_slope", "order_shift_max", "argmax_flips"}``),
    and ``concurrent`` (``{"n", "wobble_max", "distinct"}``). A noul
    battery carries ``fixture``, ``kind``, ``repeats``, ``n_errors``,
    ``noul_mean``, ``noul_std``, ``noul_min``, ``noul_max``, and
    ``concurrent``.

    Mechanics: ``repeats`` sequential identical asks; an order-permutation
    study (choice only — one ask per rotation/reversal of the option
    order, each question rebuilt so the wire criteria insertion order
    matches); then a concurrent batch of ``concurrent`` identical asks on
    worker threads, compared against the sequential means.

    Failure isolation: every failed ask — transport, mapping, or
    unexpected answer shape — increments ``n_errors`` and is excluded; a
    study whose asks all fail leaves its derived keys absent, so the
    battery never raises for ask failures. ``uniform_chi2`` always uses
    the full-outcome counts (zeros included), so a degenerate pick still
    yields ``df = k - 1``; ``uniform_deviation`` is omitted when the
    stated means do not normalize to 1 within 1e-6. The order study is
    self-contained and always runs (choice fixtures); the concurrent
    batch compares against the sequential means, so it is skipped when no
    sequential ask succeeded. Closing the client is the caller's job.
    Raises ``ValueError`` for invalid configuration (non-positive
    ``repeats``/``concurrent``, empty or duplicate-named fixtures).
    """
    if repeats < 1:
        raise ValueError(f"repeats must be at least 1, got {repeats}")
    if concurrent < 1:
        raise ValueError(f"concurrent must be at least 1, got {concurrent}")
    fixture_list = (
        [fixtures] if isinstance(fixtures, JaggednessFixture) else list(fixtures)
    )
    if not fixture_list:
        raise ValueError("fixtures must not be empty")
    names = [fixture.name for fixture in fixture_list]
    if len(set(names)) != len(names):
        raise ValueError(f"fixture names must be unique, got {names}")
    batteries: dict[str, dict[str, Any]] = {}
    for fixture in fixture_list:
        if fixture.kind == "choice":
            batteries[fixture.name] = _choice_battery(
                client, fixture, repeats, concurrent, timeout
            )
        else:
            batteries[fixture.name] = _noul_battery(
                client, fixture, repeats, concurrent, timeout
            )
    return batteries
