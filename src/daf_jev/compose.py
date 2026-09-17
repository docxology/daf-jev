"""Composable decision patterns over TypeSafe answers.

Pure, deterministic logic implementing the documented patterns
(speculative fan-out, confidence-gated routing, composite scoring, intent
routing): confidence is the second decision axis, composite weights are owned
by code. No I/O.
"""

import math

from collections.abc import Callable, Mapping, Sequence
from typing import Optional, TypeVar

from daf_jev._types import ChoiceAnswer, ScoreAnswer

__all__ = ["composite_score", "confidence_gate", "route", "pick"]

T = TypeVar("T")


def composite_score(
    answer: ScoreAnswer,
    weights: Optional[Sequence[float]] = None,
) -> float:
    """Expected value of a Score answer over its level indices.

    Default (uniform weighting): ``sum(p_i * i)`` over the sorted level
    indices — the probability-weighted position on the scale, in
    ``[min index, max index]``; equals ``answer.score``.

    With ``weights`` (one per level, positional order matching the sorted
    level indices): the probability distribution is re-weighted —
    ``q_i = p_i * w_i / sum(p_j * w_j)`` — and the result is
    ``sum(q_i * i)``. Only the weight ratios matter (scale-invariant:
    ``[2, 6]`` and ``[1, 3]`` give the same value), and the result always
    lies within ``[min index, max index]``. ``ValueError`` if the weights
    length does not match the level count, any weight is not finite, the
    weights do not sum to a positive value, or ``sum(p_j * w_j) == 0``
    (the weights assign no mass to probable levels).
    """
    probs = answer.probabilities
    if not probs:
        raise ValueError("ScoreAnswer carries no probabilities; cannot compute composite score")

    indices = sorted(int(k) for k in probs)
    if weights is None:
        return sum(int(k) * p for k, p in probs.items())

    if len(weights) != len(indices):
        raise ValueError(
            f"weights length {len(weights)} does not match level count {len(indices)}"
        )
    if not all(math.isfinite(w) for w in weights):
        raise ValueError("weights must all be finite")
    if sum(weights) <= 0:
        raise ValueError("weights must sum to a positive value")

    weighted = [(idx, probs[str(idx)] * w) for idx, w in zip(indices, weights)]
    mass = sum(m for _, m in weighted)
    if mass == 0:
        raise ValueError("weights assign no mass to probable levels")
    return sum(idx * m for idx, m in weighted) / mass


def confidence_gate(
    answer: object,
    *,
    threshold: float,
    below: str = "review",
) -> str:
    """Return the answer's primary value when confident enough, else ``below``.

    ``answer`` must carry a ``confidence`` field (Choice or Score answers do;
    Noul answers do not and raise ``TypeError``). The primary value is the
    selected ``choice`` for a Choice answer, and for a Score answer the legend
    description of the level nearest ``score`` (falling back to the score
    itself when the legend lacks that level).
    """
    confidence = getattr(answer, "confidence", None)
    if confidence is None:
        raise TypeError(
            f"{type(answer).__name__} carries no confidence "
            "(noul answers do not); confidence_gate requires a Choice or Score answer"
        )

    choice = getattr(answer, "choice", None)
    if choice is not None:
        primary: str = choice
    else:
        score = getattr(answer, "score", None)
        if score is None:
            primary = str(answer)
        else:
            probs = getattr(answer, "probabilities", None) or {}
            level = round(score)
            if probs:
                keys = [int(k) for k in probs]
                level = min(max(level, min(keys)), max(keys))
            desc = (getattr(answer, "legend", None) or {}).get(str(level))
            primary = desc if desc is not None else str(score)

    return primary if confidence >= threshold else below


def route(
    answer: ChoiceAnswer,
    handlers: Mapping[str, Callable[[], T]],
    *,
    min_confidence: float = 0.0,
    fallback: Optional[Callable[[], T]] = None,
) -> T:
    """Dispatch to the handler for ``answer.choice``, gated on confidence.

    Confidence below ``min_confidence`` routes to ``fallback`` — the model is
    saying it is not sure, so no handler fires. A choice with no registered
    handler also falls back. When ``fallback`` is ``None``, either condition
    raises (``ValueError`` for low confidence, ``KeyError`` for an unmapped
    choice) rather than silently acting. Handlers are zero-argument callables,
    invoked lazily only when selected.
    """
    choice = getattr(answer, "choice", None)
    if choice is None:
        raise TypeError(
            f"{type(answer).__name__} has no 'choice'; route() requires a ChoiceAnswer"
        )

    if getattr(answer, "confidence", 0.0) < min_confidence:
        if fallback is None:
            raise ValueError(
                f"answer confidence {getattr(answer, 'confidence', 0.0)} is below "
                f"min_confidence {min_confidence} and no fallback was provided"
            )
        return fallback()

    handler = handlers.get(choice)
    if handler is None:
        if fallback is None:
            raise KeyError(f"no handler registered for choice {choice!r} and no fallback provided")
        return fallback()
    return handler()


def pick(
    actions: Mapping[str, Callable],
    choices: Mapping[str, object],
) -> dict[str, object]:
    """Dispatch every answer in ``choices`` through :func:`route`.

    Convenience wrapper for the fan-out pattern: one call returns answers for
    several questions; ``pick`` maps each answer id to the result of the action
    matching its choice. Answers without a ``choice`` field (noul, score) have
    no discrete action to select and are skipped. Unmapped choices raise
    ``KeyError`` — pass answers through :func:`route` with a ``fallback``
    instead when a default action is wanted.
    """
    return {
        qid: route(answer, actions)
        for qid, answer in choices.items()
        if getattr(answer, "choice", None) is not None
    }
