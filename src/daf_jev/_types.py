"""Wire dataclasses for the TypeSafe Jev (System One) API.

Pure data module: no I/O. Shapes follow docs/ARCHITECTURE.md ("Wire facts")
as verified against the local docs snapshot (docs/reference/, id
b79c9cd6008489f1).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from functools import cached_property
from typing import ClassVar

JSONContent = str | list | dict

__all__ = [
    "Answer",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "JSONContent",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "ScoreAnswer",
    "ScoreQuestion",
    "SystemOneResponse",
    "Usage",
    "answer_from_wire",
    "parse_response",
    "validate_probability_row",
    "validate_response",
]

PROBABILITY_ROW_TOLERANCE = 1e-6
NATIVE_PROBABILITY_ROUNDING_DIGITS = 2


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class NoulQuestion:
    """Boolean ("noul") question: 0 = no, 1 = yes."""

    type: ClassVar[str] = "noul"
    instructions: JSONContent
    criteria: dict | None = None

    def to_wire(self) -> dict:
        wire: dict = {"type": self.type, "instructions": self.instructions}
        if self.criteria is not None:
            # Wire shape is criteria: {"true": str?, "false": str?} — None
            # values are optional descriptions and are omitted.
            filtered = {k: v for k, v in self.criteria.items() if v is not None}
            if filtered:
                wire["criteria"] = filtered
        return wire


@dataclasses.dataclass(frozen=True)
class ChoiceQuestion:
    """Single-choice question over named options."""

    type: ClassVar[str] = "choice"
    instructions: JSONContent
    criteria: Mapping[str, str | None]

    def to_wire(self) -> dict:
        criteria = self.criteria
        if not isinstance(criteria, Mapping):
            raise ValueError(
                "choice question criteria must be a mapping of option -> "
                f"description, got {type(criteria).__name__}"
            )
        options = dict(criteria)
        if not options:
            raise ValueError("choice question requires non-empty criteria (options)")
        bad = [
            option
            for option, description in options.items()
            if description is not None and not isinstance(description, str)
        ]
        if bad:
            raise ValueError(
                "choice question criteria values must all be strings or None; "
                f"non-string at option(s) {bad}"
            )
        return {
            "type": self.type,
            "instructions": self.instructions,
            "criteria": options,
        }


@dataclasses.dataclass(frozen=True)
class ScoreQuestion:
    """Ordinal score question over ordered levels."""

    type: ClassVar[str] = "score"
    instructions: JSONContent
    criteria: Sequence[str]

    def to_wire(self) -> dict:
        levels = list(self.criteria)
        if len(levels) < 2:
            raise ValueError(
                f"score question requires >= 2 criteria levels, got {len(levels)}"
            )
        bad = [i for i, level in enumerate(levels) if not isinstance(level, str)]
        if bad:
            raise ValueError(
                f"score question criteria must all be strings; non-string at "
                f"indices {bad}"
            )
        return {
            "type": self.type,
            "instructions": self.instructions,
            "criteria": levels,
        }


Question = NoulQuestion | ChoiceQuestion | ScoreQuestion


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class NoulAnswer:
    type: ClassVar[str] = "noul"
    noul: float


@dataclasses.dataclass(frozen=True)
class ChoiceAnswer:
    type: ClassVar[str] = "choice"
    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclasses.dataclass(frozen=True)
class ScoreAnswer:
    type: ClassVar[str] = "score"
    score: float  # probability-weighted; may be fractional
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer

_ANSWER_TYPES: dict[str, type[Answer]] = {
    NoulAnswer.type: NoulAnswer,
    ChoiceAnswer.type: ChoiceAnswer,
    ScoreAnswer.type: ScoreAnswer,
}


def _require(payload: dict, cls: type[Answer], answer_type: str) -> dict:
    """Return the payload keys needed by ``cls`` or raise ValueError."""
    missing = [
        f.name for f in dataclasses.fields(cls) if f.name not in payload
    ]
    if missing:
        raise ValueError(
            f"{answer_type} answer is missing required keys: {missing}"
        )
    return payload


def _as_float(value: object, field: str) -> float:
    """Return ``value`` as a float under the strict wire contract: only real
    numbers pass (bools and numeric strings are rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number, got {value!r}")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite, got {value!r}")
    return number


def _as_unit_interval(value: object, field: str) -> float:
    number = _as_float(value, field)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be in [0, 1], got {value!r}")
    return number


def validate_probability_row(
    probabilities: Mapping[str, float],
    *,
    rounding_digits: int | None = None,
    context: str = "probabilities",
) -> None:
    """Validate a complete probability row without changing its values.

    The strict mass budget is 1e-6. An explicitly declared decimal precision
    adds half a rounding quantum per entry only when every entry matches that
    precision. Native System One rows use two decimal places; callers with
    generated or full-precision probabilities should leave ``rounding_digits``
    unset. This allowance does not apply to CPTs or posterior sidecars.
    """
    if rounding_digits is not None and (
        isinstance(rounding_digits, bool)
        or not isinstance(rounding_digits, int)
        or not 0 <= rounding_digits <= 15
    ):
        raise ValueError("rounding_digits must be None or an integer in [0, 15]")
    if not isinstance(probabilities, Mapping) or not probabilities:
        raise ValueError(f"{context} must be a non-empty mapping")
    values = [
        _as_unit_interval(value, f"{context}[{option!r}]")
        for option, value in probabilities.items()
    ]
    tolerance = PROBABILITY_ROW_TOLERANCE
    if rounding_digits is not None and all(
        abs(value - round(value, rounding_digits)) <= 1e-12 for value in values
    ):
        tolerance += len(values) * 0.5 * 10.0 ** -rounding_digits
    mass = math.fsum(values)
    if mass <= 0.0 or abs(mass - 1.0) > tolerance:
        raise ValueError(
            f"{context} sum {mass!r} differs from 1 by {abs(mass - 1.0)!r}; "
            f"allowed deviation is {tolerance!r}"
        )


def _require_str(payload: dict, field: str) -> str:
    """Return ``payload[field]`` requiring an actual ``str``."""
    value = payload[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {value!r}")
    return value


def _as_probabilities(
    probabilities: object, rounding_digits: int | None
) -> dict[str, float]:
    """Parse a strict ``{option: number}`` mapping or raise ValueError."""
    if not isinstance(probabilities, dict):
        raise ValueError(
            "probabilities must be a dict of option -> number, "
            f"got {type(probabilities).__name__}"
        )
    parsed = {
        str(option): _as_float(value, f"probabilities[{option!r}]")
        for option, value in probabilities.items()
    }
    validate_probability_row(parsed, rounding_digits=rounding_digits)
    return parsed


def _as_legend(legend: object) -> dict[str, str]:
    """Parse a strict ``{level: description}`` mapping or raise ValueError.

    Values must already be ``str`` — the wire legend is
    ``{level_index_str: str}``, and coercing e.g. ``str(None)`` to
    ``"None"`` would silently fabricate a description. Keys are still
    stringified level indices.
    """
    if not isinstance(legend, dict):
        raise ValueError(
            "legend must be a dict of level -> description, "
            f"got {type(legend).__name__}"
        )
    parsed: dict[str, str] = {}
    for level, description in legend.items():
        if not isinstance(description, str):
            raise ValueError(
                f"legend values must be strings, got {description!r} "
                f"at level {level!r}"
            )
        parsed[str(level)] = description
    return parsed


def _as_int(usage: dict, key: str) -> int:
    """Return ``usage[key]`` as an int (default 0) under the strict wire
    contract: an ``int`` passes as-is (``bool`` never does — it is an
    ``int`` subclass), a float only when integral (``100.0`` -> ``100``),
    and numeric strings or any other type raise a field-naming
    ``ValueError``."""
    value = usage.get(key, 0)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer number, got {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        raise ValueError(f"{key} must be an integer number, got {value!r}")
    if number < 0:
        raise ValueError(f"{key} must be non-negative, got {value!r}")
    return number


def answer_from_wire(
    payload: dict,
    *,
    probability_rounding_digits: int | None = NATIVE_PROBABILITY_ROUNDING_DIGITS,
) -> Answer:
    """Parse a strict wire answer dict into its dataclass.

    Raises ValueError for an unknown answer type, a missing key, or a
    malformed value (wrong type for a string, mapping, or numeric field).
    Unit-interval fields and probability mass are validated. The native
    rounding allowance defaults to two decimal places; pass
    ``probability_rounding_digits=None`` for the strict 1e-6 mass budget.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"answer must be a dict, got {type(payload).__name__}")
    answer_type = payload.get("type")
    if not isinstance(answer_type, str):
        raise ValueError(f"unknown answer type: {answer_type!r}")
    cls = _ANSWER_TYPES.get(answer_type)
    if cls is None:
        raise ValueError(f"unknown answer type: {answer_type!r}")
    _require(payload, cls, answer_type)
    if cls is NoulAnswer:
        return NoulAnswer(noul=_as_unit_interval(payload["noul"], "noul"))
    if cls is ChoiceAnswer:
        return ChoiceAnswer(
            choice=_require_str(payload, "choice"),
            probabilities=_as_probabilities(payload["probabilities"], probability_rounding_digits),
            confidence=_as_unit_interval(payload["confidence"], "confidence"),
        )
    return ScoreAnswer(
        score=_as_float(payload["score"], "score"),
        legend=_as_legend(payload["legend"]),
        probabilities=_as_probabilities(payload["probabilities"], probability_rounding_digits),
        confidence=_as_unit_interval(payload["confidence"], "confidence"),
    )


# ---------------------------------------------------------------------------
# Top-level response
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclasses.dataclass(frozen=True)
class SystemOneResponse:
    model: str
    answers: dict[str, Answer]
    usage: Usage
    request_id: str | None = None

    @cached_property
    def nouls(self) -> dict[str, NoulAnswer]:
        return {
            qid: answer
            for qid, answer in self.answers.items()
            if isinstance(answer, NoulAnswer)
        }

    @cached_property
    def choices(self) -> dict[str, ChoiceAnswer]:
        return {
            qid: answer
            for qid, answer in self.answers.items()
            if isinstance(answer, ChoiceAnswer)
        }

    @cached_property
    def scores(self) -> dict[str, ScoreAnswer]:
        return {
            qid: answer
            for qid, answer in self.answers.items()
            if isinstance(answer, ScoreAnswer)
        }


def parse_response(
    payload: dict,
    request_id: str | None = None,
    *,
    probability_rounding_digits: int | None = NATIVE_PROBABILITY_ROUNDING_DIGITS,
) -> SystemOneResponse:
    """Parse a strict System One response payload.

    Unknown extra top-level fields (e.g. kev's ``latency_ms``) are
    tolerated and ignored.
    Raises ValueError when the top-level keys are missing or malformed, an
    answer has an unknown type, or an answer or usage value has the wrong
    type. Token counts must be non-negative. Native probability rows are
    retained verbatim under the declared rounding allowance; pass
    ``probability_rounding_digits=None`` for strict full-precision rows.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"response payload must be a dict, got {type(payload).__name__}"
        )
    for key in ("model", "answers", "usage"):
        if key not in payload:
            raise ValueError(f"response is missing required key: {key!r}")
    model = _require_str(payload, "model")
    answers_raw = payload["answers"]
    if not isinstance(answers_raw, dict):
        raise ValueError(
            f"answers must be a dict, got {type(answers_raw).__name__}"
        )
    usage_raw = payload["usage"]
    if not isinstance(usage_raw, dict):
        raise ValueError(f"usage must be a dict, got {type(usage_raw).__name__}")
    answers = {
        str(qid): answer_from_wire(
            answer, probability_rounding_digits=probability_rounding_digits
        )
        for qid, answer in answers_raw.items()
    }
    return SystemOneResponse(
        model=model,
        answers=answers,
        usage=Usage(
            input_tokens=_as_int(usage_raw, "input_tokens"),
            output_tokens=_as_int(usage_raw, "output_tokens"),
        ),
        request_id=request_id,
    )


def validate_response(
    response: SystemOneResponse,
    questions: Mapping[str, Question | dict],
    *,
    probability_rounding_digits: int | None = NATIVE_PROBABILITY_ROUNDING_DIGITS,
) -> None:
    """Bind native answers to the exact request; never repair a response."""
    expected_ids = set(questions)
    received_ids = set(response.answers)
    if expected_ids != received_ids:
        raise ValueError(
            f"answer IDs do not match questions: missing {sorted(expected_ids - received_ids)!r}, "
            f"unexpected {sorted(received_ids - expected_ids)!r}"
        )
    _as_int(dataclasses.asdict(response.usage), "input_tokens")
    _as_int(dataclasses.asdict(response.usage), "output_tokens")
    for qid, question in questions.items():
        wire = question if isinstance(question, dict) else question.to_wire()
        answer = response.answers[qid]
        qtype = wire.get("type")
        if qtype != answer.type:
            raise ValueError(
                f"question {qid!r} requires a {qtype!r} answer, got {answer.type!r}"
            )
        if isinstance(answer, NoulAnswer):
            _as_unit_interval(answer.noul, f"answer {qid!r} noul")
            continue
        _as_unit_interval(answer.confidence, f"answer {qid!r} confidence")
        validate_probability_row(
            answer.probabilities,
            rounding_digits=probability_rounding_digits,
            context=f"answer {qid!r} probabilities",
        )
        if isinstance(answer, ChoiceAnswer):
            expected_options = set(wire["criteria"])
            if set(answer.probabilities) != expected_options:
                raise ValueError(f"answer {qid!r} probabilities must match every choice option")
            if answer.choice not in expected_options:
                raise ValueError(f"answer {qid!r} choice {answer.choice!r} is not a declared option")
        elif isinstance(answer, ScoreAnswer):
            levels = wire["criteria"]
            expected_levels = {str(index) for index in range(len(levels))}
            if set(answer.probabilities) != expected_levels or set(answer.legend) != expected_levels:
                raise ValueError(f"answer {qid!r} probabilities and legend must match every score level")
            if answer.legend != {str(index): text for index, text in enumerate(levels)}:
                raise ValueError(f"answer {qid!r} legend does not match the declared score levels")
            score = _as_float(answer.score, f"answer {qid!r} score")
            if not 0.0 <= score <= len(levels) - 1:
                raise ValueError(f"answer {qid!r} score must be in [0, {len(levels) - 1}]")
