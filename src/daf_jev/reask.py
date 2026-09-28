"""Max-entropy re-ask policy over posterior sidecars (M1 part b).

Pipeline step 5 as a decision-policy input: the sidecar's posterior rows
say where the model is still uncertain, and the next variable to ask
about is the one whose row carries the highest Shannon entropy in bits.
This module is pure compute — no I/O, no client, no matplotlib, no
network. The Jev-ask wiring lives in the example layer
(``examples/reask_policy.py``); the CLI (``daf-jev posteriors-reask``)
and the MCP tool (``jev_reask_plan``) surface the plan directly.

Fail-closed contract: only ``dafjev.bayesnet-posteriors/1`` sidecars are
accepted. ``gnn.marginals/1`` documents carry no ``evidence`` mapping to
replay, so a re-ask plan would have no recorded context — they are
rejected with a message naming both format strings.

Entropy rows follow the :mod:`daf_jev.bayesnet_posteriors` row-sum
conventions (the flat :data:`~daf_jev.bayesnet_posteriors.ROW_SUM_TOLERANCE`
budget): negative or non-finite probabilities raise ``ValueError``, and
drifting rows are NEVER renormalized — the deviation is raised with the
numbers in the message.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from daf_jev.bayesnet_posteriors import (
    FORMAT_MARGINALS,
    FORMAT_POSTERIORS,
    ROW_SUM_TOLERANCE,
    PosteriorsSidecar,
)

__all__ = [
    "ReAskPlan",
    "entropy_bits",
    "next_question",
    "reask_plan",
]


@dataclass(frozen=True)
class ReAskPlan:
    """The ordered re-ask queue derived from a posteriors sidecar.

    ``next_question`` is the max-entropy not-yet-asked variable (ties
    broken by the sidecar's posteriors insertion order; ``None`` when no
    candidate remains). ``entropy`` is that variable's entropy in bits.
    ``queue`` holds ``(variable, entropy_bits)`` pairs over every
    candidate, descending by entropy with insertion-order ties.
    ``evidence`` is the sidecar's evidence mapping verbatim — the replay
    context; the plan never constructs Jev calls (the example layer does).
    """

    next_question: str | None
    entropy: float | None
    queue: tuple[tuple[str, float], ...]
    evidence: Mapping[str, str]


def entropy_bits(row: Mapping[str, float]) -> float:
    """Shannon entropy of one probability row, in BITS (base-2 log).

    Empty rows return ``0.0``. Probabilities must be finite and
    non-negative; the row must sum to 1 within the
    :data:`daf_jev.bayesnet_posteriors.ROW_SUM_TOLERANCE` flat budget —
    a drifting row raises with its deviation in the message and is never
    renormalized. Zero-probability states contribute 0 bits (the
    ``0 * log2(0) = 0`` convention).

    Raises:
        ValueError: On a negative or non-finite probability, or a row-sum
            deviation beyond
            :data:`~daf_jev.bayesnet_posteriors.ROW_SUM_TOLERANCE`.
    """
    if not row:
        return 0.0
    total = 0.0
    entropy = 0.0
    for state, probability in row.items():
        if not math.isfinite(probability):
            raise ValueError(
                f"probability for state {state!r} must be finite, got "
                f"{probability!r}"
            )
        if probability < 0.0:
            raise ValueError(
                f"probability for state {state!r} must be >= 0, got "
                f"{probability!r}"
            )
        total += probability
        if probability > 0.0:
            entropy -= probability * math.log2(probability)
    deviation = abs(total - 1.0)
    if deviation > ROW_SUM_TOLERANCE:
        raise ValueError(
            f"probability row sums to {total!r}, deviating {deviation!r} "
            f"from 1.0 beyond the row-sum budget {ROW_SUM_TOLERANCE!r}"
        )
    return entropy


def reask_plan(
    sidecar: PosteriorsSidecar,
    *,
    asked: Iterable[str] = frozenset(),
) -> ReAskPlan:
    """Build the full max-entropy re-ask plan from a variant-A sidecar.

    Args:
        sidecar: A validated ``dafjev.bayesnet-posteriors/1`` sidecar.
            Variant B (``gnn.marginals/1``) is rejected: it carries no
            ``evidence`` to replay.
        asked: Variables already asked; excluded from the queue (unknown
            names are simply never candidates).

    Returns:
        The :class:`ReAskPlan`: next variable (max entropy, insertion-order
        ties), its entropy in bits, the full descending queue, and the
        sidecar's evidence mapping verbatim.

    Raises:
        ValueError: When the sidecar is not a variant-A document.
    """
    if sidecar.format != FORMAT_POSTERIORS:
        raise ValueError(
            f"re-ask requires {FORMAT_POSTERIORS!r} sidecars with an "
            f"evidence mapping to replay; got {sidecar.format!r} "
            f"({FORMAT_MARGINALS!r} documents carry no evidence)"
        )
    asked_set = frozenset(asked)
    candidates = tuple(
        (var, entropy_bits(row))
        for var, row in sidecar.posteriors.items()
        if var not in asked_set
    )
    # Descending entropy; Python's stable sort keeps insertion order for
    # equal keys even under reverse=True, which pins the tie-break.
    ordered = tuple(
        sorted(candidates, key=lambda entry: entry[1], reverse=True)
    )
    first = ordered[0] if ordered else None
    return ReAskPlan(
        next_question=first[0] if first is not None else None,
        entropy=first[1] if first is not None else None,
        queue=ordered,
        evidence=sidecar.evidence or {},
    )


def next_question(
    sidecar: PosteriorsSidecar,
    *,
    asked: Iterable[str] = frozenset(),
) -> str | None:
    """The next variable to ask about: max entropy, insertion-order ties.

    ``None`` when no candidate remains (every variable with a posterior
    row has been asked, or the sidecar has no rows). Delegates to
    :func:`reask_plan` so the tie-break contract lives in one place.
    """
    return reask_plan(sidecar, asked=asked).next_question
