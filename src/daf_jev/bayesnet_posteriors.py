"""Ingest of GNN-emitted Bayes-net posterior sidecars, plus calibration
pairing.

Cross-repo contract: the GNN side emits a posterior sidecar JSON document
via ``rxinfer_bridge --out``; this module reads it fail-closed. Two
sibling format variants share one loader:

- ``dafjev.bayesnet-posteriors/1`` (:data:`FORMAT_POSTERIORS`, this
  repo's public contract): top-level keys exactly ``{format, evidence,
  posteriors}``; rows are raw ``Float64`` probabilities with the flat
  per-row budget ``|sum(row) - 1| <= 1e-6`` (:data:`ROW_SUM_TOLERANCE`);
  ``evidence`` maps each observed variable to its observed state, and
  every evidence row must be one-hot: the observed state carries
  ``p >= 1 - 1e-6`` (:data:`ONE_HOT_TOLERANCE`; a missing state counts as
  ``0.0``) and every other state in that row carries ``p <= 1e-6``.
- ``gnn.marginals/1`` (:data:`FORMAT_MARGINALS`, GNN-internal):
  top-level keys exactly ``{format, marginals, source_model}``; rows are
  6-digit-rounded, so the per-row budget widens with row length:
  ``|sum(row) - 1| <= 1e-6 + len(row) * 5e-7``. This is the budget
  asymmetry vs variant A — 5e-7 (:data:`ROUNDED_STATE_BUDGET`) is the
  worst-case per-state rounding error of 6-digit output.

The sidecar is the calibration TARGET for Jev assignments
(:func:`pair_for_calibration`): ``confidence`` is the exact posterior
support for Jev's chosen state, ``correct`` is whether that state matches
the sidecar's modal state (first-max tie-break in insertion order on both
sides), and the soft multiclass Brier score compares the full assignment
against the sidecar row. Distribution assignments reduce to their argmax
for the ``(confidence, correct)`` pair; the full distribution feeds only
the Brier term.

No re-ask mode is implemented in this lane: re-asking against the sidecar
is future decider-example-layer work.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from daf_jev.graphical import GRAPH_SPEC_FORMAT

__all__ = [
    "ASSIGNMENT_ROW_SUM_TOLERANCE",
    "FORMAT_MARGINALS",
    "FORMAT_POSTERIORS",
    "ONE_HOT_TOLERANCE",
    "ROUNDED_STATE_BUDGET",
    "ROW_SUM_TOLERANCE",
    "CalibrationPairing",
    "PosteriorsSidecar",
    "load_posteriors",
    "pair_for_calibration",
    "row_sum_deviations",
]

FORMAT_POSTERIORS = "dafjev.bayesnet-posteriors/1"
FORMAT_MARGINALS = "gnn.marginals/1"
ROW_SUM_TOLERANCE = 1e-6            # variant A per-row budget (raw Float64)
ROUNDED_STATE_BUDGET = 5e-7         # variant B per-state budget (6-digit rounding)
ONE_HOT_TOLERANCE = 1e-6
ASSIGNMENT_ROW_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PosteriorsSidecar:
    """A parsed posterior sidecar document.

    ``format`` is :data:`FORMAT_POSTERIORS` (variant A: ``evidence`` set,
    ``source_model`` ``None``) or :data:`FORMAT_MARGINALS` (variant B:
    ``evidence`` ``None``, ``source_model`` a model label or ``None``).
    ``posteriors`` maps variable key -> state -> probability, preserving
    the document's insertion order ("posteriors" rows for variant A,
    "marginals" rows for variant B).
    """

    format: str                                    # FORMAT_POSTERIORS | FORMAT_MARGINALS
    posteriors: Mapping[str, Mapping[str, float]]  # var -> state -> p (A "posteriors" rows; B "marginals" rows)
    evidence: Mapping[str, str] | None             # variant A only; None for B
    source_model: str | None                       # variant B only; None for A


@dataclass(frozen=True)
class CalibrationPairing:
    """Calibration statistics of Jev assignments paired against a sidecar.

    ``brier_scores`` maps each paired variable to the soft multiclass
    Brier score of its assignment against the sidecar row, in assignment
    insertion order. ``pairs`` carries ``(confidence, correct)`` tuples in
    the same order and length, matching the :mod:`daf_jev.calibration`
    pair convention.
    """

    brier_scores: Mapping[str, float]      # var -> soft multiclass Brier vs sidecar row (insertion order)
    pairs: tuple[tuple[float, bool], ...]  # (confidence, correct); same order/length as brier_scores


def _row_sum_deviation(row: Mapping[str, float]) -> float:
    """Absolute distance of a probability row from 1.0 (plain float sum)."""
    return abs(sum(row.values()) - 1.0)


def _first_argmax(row: Mapping[str, float]) -> str:
    """First state in insertion order carrying the row's maximum value."""
    best_state: str | None = None
    best_probability = -math.inf
    for state, probability in row.items():
        if probability > best_probability:
            best_state = state
            best_probability = probability
    if best_state is None:
        raise ValueError("cannot determine the modal state of an empty probability row")
    return best_state


def load_posteriors(
    path: str | Path,
    graphspec: str | Path | None = None,
) -> PosteriorsSidecar:
    """Read a posterior sidecar document, validating it fail-closed.

    Accepts both sibling variants: ``{format, evidence, posteriors}``
    (:data:`FORMAT_POSTERIORS`, with the one-hot evidence rule) and
    ``{format, marginals, source_model}`` (:data:`FORMAT_MARGINALS`, with
    the length-widened row-sum budget). Key and row order are preserved
    as plain dicts. When ``graphspec`` is given, every sidecar variable
    and state is cross-checked against that GraphSpec document
    (sidecar -> spec direction only; extra spec detail is ignored).

    Args:
        path: Sidecar JSON document (``dafjev.bayesnet-posteriors/1`` or
            ``gnn.marginals/1``).
        graphspec: Optional ``dafjev.bayesnet/1`` GraphSpec document to
            cross-check variables and states against.

    Returns:
        The parsed :class:`PosteriorsSidecar`, insertion order preserved
        everywhere.

    Raises:
        ValueError: On invalid JSON, a missing or unknown ``format``,
            unexpected/missing top-level keys, non-mapping rows,
            bool/non-numeric/NaN/infinite/negative probabilities, a
            row-sum budget breach (flat for variant A, length-widened for
            variant B), a one-hot evidence violation, or — when
            ``graphspec`` is given — a GraphSpec document that is not
            valid ``dafjev.bayesnet/1`` or does not define a sidecar
            variable or state. Errors name the offending
            var/state/key/path.
        FileNotFoundError: When ``path`` (or ``graphspec``) does not
            exist; natural errors propagate.
    """
    sidecar_path = Path(path)
    try:
        document = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"posteriors sidecar {sidecar_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ValueError(
            f"posteriors sidecar {sidecar_path} top level must be a JSON "
            f"object, got {type(document).__name__}"
        )
    if "format" not in document:
        raise ValueError(
            f"posteriors sidecar {sidecar_path} is missing the required 'format' key"
        )
    fmt = document["format"]
    if not isinstance(fmt, str):
        raise ValueError(
            f"posteriors sidecar {sidecar_path}: 'format' must be a string, "
            f"got {type(fmt).__name__}"
        )
    if fmt not in (FORMAT_POSTERIORS, FORMAT_MARGINALS):
        raise ValueError(
            f"posteriors sidecar {sidecar_path}: unsupported format {fmt!r} "
            f"(accepted: {FORMAT_POSTERIORS!r}, {FORMAT_MARGINALS!r})"
        )

    is_posteriors = fmt == FORMAT_POSTERIORS
    rows_key = "posteriors" if is_posteriors else "marginals"
    expected_keys = (
        {"format", "evidence", "posteriors"}
        if is_posteriors
        else {"format", "marginals", "source_model"}
    )
    unexpected = sorted(set(document) - expected_keys)
    if unexpected:
        raise ValueError(
            f"posteriors sidecar {sidecar_path}: unexpected top-level key(s) "
            f"{unexpected!r} for format {fmt!r}; expected exactly "
            f"{sorted(expected_keys)!r}"
        )
    missing = sorted(expected_keys - set(document))
    if missing:
        raise ValueError(
            f"posteriors sidecar {sidecar_path}: missing top-level key(s) "
            f"{missing!r} for format {fmt!r}"
        )

    rows_document = document[rows_key]
    if not isinstance(rows_document, Mapping):
        raise ValueError(
            f"posteriors sidecar {sidecar_path}: {rows_key!r} must be a JSON "
            f"object mapping variable keys to state -> probability rows, got "
            f"{type(rows_document).__name__}"
        )
    posteriors: dict[str, dict[str, float]] = {}
    for var, row_document in rows_document.items():
        if not isinstance(row_document, Mapping):
            raise ValueError(
                f"posteriors sidecar {sidecar_path}: {rows_key} row for "
                f"variable {var!r} must be a JSON object mapping state names "
                f"to probabilities, got {type(row_document).__name__}"
            )
        row: dict[str, float] = {}
        for state, value in row_document.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: {rows_key} probability "
                    f"for variable {var!r} state {state!r} must be an int or "
                    f"float, got {type(value).__name__}"
                )
            try:
                probability = float(value)
            except OverflowError as exc:
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: {rows_key} probability "
                    f"for variable {var!r} state {state!r} is out of float "
                    f"range, got {value!r}"
                ) from exc
            if not math.isfinite(probability):
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: {rows_key} probability "
                    f"for variable {var!r} state {state!r} must be finite, got "
                    f"{value!r}"
                )
            if probability < 0.0:
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: {rows_key} probability "
                    f"for variable {var!r} state {state!r} must be >= 0, got "
                    f"{value!r}"
                )
            row[state] = probability
        budget = (
            ROW_SUM_TOLERANCE
            if is_posteriors
            else ROW_SUM_TOLERANCE + len(row) * ROUNDED_STATE_BUDGET
        )
        deviation = _row_sum_deviation(row)
        if deviation > budget:
            raise ValueError(
                f"posteriors sidecar {sidecar_path}: {rows_key} row for "
                f"variable {var!r} sums to {sum(row.values())!r}, deviating "
                f"{deviation!r} from 1.0 beyond the {fmt!r} row-sum budget "
                f"{budget!r}"
            )
        posteriors[var] = row

    evidence: dict[str, str] | None = None
    source_model: str | None = None
    if is_posteriors:
        evidence_document = document["evidence"]
        if not isinstance(evidence_document, Mapping):
            raise ValueError(
                f"posteriors sidecar {sidecar_path}: 'evidence' must be a JSON "
                f"object mapping variable keys to observed state names, got "
                f"{type(evidence_document).__name__}"
            )
        evidence = {}
        for var, observed in evidence_document.items():
            if not isinstance(observed, str):
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: evidence value for "
                    f"variable {var!r} must be a string state name, got "
                    f"{type(observed).__name__}"
                )
            evidence[var] = observed
        for var, observed in evidence.items():
            evidence_row = posteriors.get(var)
            if evidence_row is None:
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: evidence variable "
                    f"{var!r} has no {rows_key} row"
                )
            observed_probability = evidence_row.get(observed, 0.0)
            if observed_probability < 1.0 - ONE_HOT_TOLERANCE:
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: evidence one-hot "
                    f"violated for variable {var!r}: observed state "
                    f"{observed!r} carries {observed_probability!r}, needs "
                    f">= {1.0 - ONE_HOT_TOLERANCE!r}"
                )
            for state, probability in evidence_row.items():
                if state != observed and probability > ONE_HOT_TOLERANCE:
                    raise ValueError(
                        f"posteriors sidecar {sidecar_path}: evidence one-hot "
                        f"violated for variable {var!r}: state {state!r} "
                        f"carries {probability!r} > tolerance "
                        f"{ONE_HOT_TOLERANCE!r} while {observed!r} is observed"
                    )
    else:
        source_model = document["source_model"]
        if source_model is not None and not isinstance(source_model, str):
            raise ValueError(
                f"posteriors sidecar {sidecar_path}: 'source_model' must be a "
                f"string or null, got {type(source_model).__name__}"
            )

    if graphspec is not None:
        spec_path = Path(graphspec)
        try:
            spec_document = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"graphspec {spec_path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(spec_document, dict):
            raise ValueError(
                f"graphspec {spec_path}: top level must be a JSON object, got "
                f"{type(spec_document).__name__}"
            )
        spec_format = spec_document.get("format")
        if spec_format != GRAPH_SPEC_FORMAT:
            raise ValueError(
                f"graphspec {spec_path}: format must be {GRAPH_SPEC_FORMAT!r}, "
                f"got {spec_format!r}"
            )
        variables_document = spec_document.get("variables")
        if not isinstance(variables_document, list):
            raise ValueError(
                f"graphspec {spec_path}: 'variables' must be a list, got "
                f"{type(variables_document).__name__}"
            )
        spec_states: dict[str, list[str]] = {}
        for index, element in enumerate(variables_document):
            if not isinstance(element, dict):
                raise ValueError(
                    f"graphspec {spec_path}: variables[{index}] must be a JSON "
                    f"object carrying 'key' and 'states', got "
                    f"{type(element).__name__}"
                )
            key = element.get("key")
            if not isinstance(key, str):
                raise ValueError(
                    f"graphspec {spec_path}: variables[{index}] must carry a "
                    f"string 'key', got {key!r}"
                )
            states = element.get("states")
            if not isinstance(states, list) or not all(
                isinstance(state, str) for state in states
            ):
                raise ValueError(
                    f"graphspec {spec_path}: variables[{key!r}] must carry a "
                    f"'states' list of strings, got {states!r}"
                )
            spec_states[key] = list(states)
        if evidence is not None:
            for var, observed in evidence.items():
                spec_var_states = spec_states.get(var)
                if spec_var_states is None:
                    raise ValueError(
                        f"posteriors sidecar {sidecar_path}: evidence variable "
                        f"{var!r} is not defined in graphspec {spec_path}"
                    )
                if observed not in spec_var_states:
                    raise ValueError(
                        f"posteriors sidecar {sidecar_path}: evidence state "
                        f"{observed!r} of variable {var!r} is not among "
                        f"graphspec states {spec_var_states!r} in {spec_path}"
                    )
        for var, row in posteriors.items():
            spec_var_states = spec_states.get(var)
            if spec_var_states is None:
                raise ValueError(
                    f"posteriors sidecar {sidecar_path}: posterior variable "
                    f"{var!r} is not defined in graphspec {spec_path}"
                )
            for state in row:
                if state not in spec_var_states:
                    raise ValueError(
                        f"posteriors sidecar {sidecar_path}: posterior state "
                        f"{state!r} of variable {var!r} is not among graphspec "
                        f"states {spec_var_states!r} in {spec_path}"
                    )

    return PosteriorsSidecar(
        format=fmt,
        posteriors=posteriors,
        evidence=evidence,
        source_model=source_model,
    )


def row_sum_deviations(sidecar: PosteriorsSidecar) -> dict[str, float]:
    """Per-variable absolute row-sum deviation ``|sum(row) - 1|``.

    Insertion order follows ``sidecar.posteriors``.
    """
    return {var: _row_sum_deviation(row) for var, row in sidecar.posteriors.items()}


def pair_for_calibration(
    sidecar: PosteriorsSidecar,
    assignments: Mapping[str, str | Mapping[str, float]],
) -> CalibrationPairing:
    """Pair Jev assignments against the sidecar as the calibration target.

    Each assignment names a sidecar variable with either a chosen state
    (``str``) or a state -> probability distribution (``Mapping``).
    Sidecar variables without an assignment are skipped — partial pairing
    is by design. For every assigned variable, in assignment insertion
    order: the soft multiclass Brier score of the assignment against the
    sidecar row (summed over the union of both key sets), plus a
    ``(confidence, correct)`` pair where ``confidence`` is the exact
    posterior support for the chosen state and ``correct`` whether the
    chosen state matches the sidecar's modal state. Ties break to the
    first maximum in insertion order on both sides; distribution
    assignments reduce to their argmax for the pair, while the full
    distribution feeds only the Brier term.

    Args:
        sidecar: Calibration target (see :class:`PosteriorsSidecar`).
        assignments: Variable key -> chosen state or distribution.

    Returns:
        The :class:`CalibrationPairing` over all assigned variables, in
        assignment insertion order.

    Raises:
        ValueError: Naming the offending variable/state when an
            assignment value is neither a string nor a mapping, the
            assigned variable is absent from ``sidecar.posteriors``, a
            chosen or distribution state is not among the sidecar row's
            states (the row defines the vocabulary), a distribution
            probability is not a non-negative finite number, or a
            distribution does not sum to 1 within
            :data:`ASSIGNMENT_ROW_SUM_TOLERANCE`.
    """
    brier_scores: dict[str, float] = {}
    pairs: list[tuple[float, bool]] = []
    for var, assignment in assignments.items():
        if not isinstance(assignment, str) and not isinstance(assignment, Mapping):
            raise ValueError(
                f"assignment of variable {var!r} must be a state name (str) or "
                f"a state -> probability mapping, got {type(assignment).__name__}"
            )
        row = sidecar.posteriors.get(var)
        if row is None:
            raise ValueError(
                f"assignment variable {var!r} is not present in the posteriors "
                f"sidecar (sidecar variables: {list(sidecar.posteriors)})"
            )
        if not row:
            raise ValueError(
                f"posteriors sidecar row for variable {var!r} is empty; "
                "cannot pair against it"
            )
        if isinstance(assignment, str):
            chosen = assignment
            if chosen not in row:
                raise ValueError(
                    f"assignment state {chosen!r} of variable {var!r} is not "
                    f"among sidecar states {list(row)}"
                )
            prediction: dict[str, float] = {chosen: 1.0}
        else:
            for state, value in assignment.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"assignment probability of variable {var!r} state "
                        f"{state!r} must be an int or float, got "
                        f"{type(value).__name__}"
                    )
                try:
                    probability = float(value)
                except OverflowError as exc:
                    raise ValueError(
                        f"assignment probability of variable {var!r} state "
                        f"{state!r} is out of float range, got {value!r}"
                    ) from exc
                if not math.isfinite(probability):
                    raise ValueError(
                        f"assignment probability of variable {var!r} state "
                        f"{state!r} must be finite, got {value!r}"
                    )
                if probability < 0.0:
                    raise ValueError(
                        f"assignment probability of variable {var!r} state "
                        f"{state!r} must be >= 0, got {value!r}"
                    )
            for state in assignment:
                if state not in row:
                    raise ValueError(
                        f"assignment state {state!r} of variable {var!r} is "
                        f"not among sidecar states {list(row)} (the row "
                        f"defines the vocabulary)"
                    )
            assignment_sum = sum(assignment.values())
            if abs(assignment_sum - 1.0) > ASSIGNMENT_ROW_SUM_TOLERANCE:
                raise ValueError(
                    f"assignment of variable {var!r} sums to {assignment_sum!r}, "
                    f"deviating more than {ASSIGNMENT_ROW_SUM_TOLERANCE!r} from 1.0"
                )
            chosen = _first_argmax(assignment)
            prediction = dict(assignment)
        brier = 0.0
        counted: set[str] = set()
        for state, value in prediction.items():
            counted.add(state)
            brier += (value - row.get(state, 0.0)) ** 2
        for state, value in row.items():
            if state not in counted:
                brier += (0.0 - value) ** 2
        brier_scores[var] = brier
        pairs.append((row[chosen], chosen == _first_argmax(row)))
    return CalibrationPairing(brier_scores=brier_scores, pairs=tuple(pairs))
