"""Wire dataclasses for the TypeSafe Jev (System One) API.

Pure data module: no I/O. Shapes follow docs/ARCHITECTURE.md ("Wire facts")
as verified against the local docs snapshot (docs/reference/, id
b79c9cd6008489f1).
"""

from __future__ import annotations

import dataclasses
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
]


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
        return float(value)
    except OverflowError as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc


def _require_str(payload: dict, field: str) -> str:
    """Return ``payload[field]`` requiring an actual ``str``."""
    value = payload[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {value!r}")
    return value


def _as_probabilities(probabilities: object) -> dict[str, float]:
    """Parse a strict ``{option: number}`` mapping or raise ValueError."""
    if not isinstance(probabilities, dict):
        raise ValueError(
            "probabilities must be a dict of option -> number, "
            f"got {type(probabilities).__name__}"
        )
    return {
        str(option): _as_float(value, f"probabilities[{option!r}]")
        for option, value in probabilities.items()
    }


def _as_legend(legend: object) -> dict[str, str]:
    """Parse a strict ``{level: description}`` mapping or raise ValueError."""
    if not isinstance(legend, dict):
        raise ValueError(
            "legend must be a dict of level -> description, "
            f"got {type(legend).__name__}"
        )
    return {str(level): str(description) for level, description in legend.items()}


def _as_int(usage: dict, key: str) -> int:
    """Return ``usage[key]`` as an int (default 0); any parse failure is
    normalized to a field-naming ValueError."""
    value = usage.get(key, 0)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{key} must be an integer, got {value!r}") from exc


def answer_from_wire(payload: dict) -> Answer:
    """Parse a strict wire answer dict into its dataclass.

    Raises ValueError for an unknown answer type, a missing key, or a
    malformed value (wrong type for a string, mapping, or numeric field).
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
        return NoulAnswer(noul=_as_float(payload["noul"], "noul"))
    if cls is ChoiceAnswer:
        return ChoiceAnswer(
            choice=_require_str(payload, "choice"),
            probabilities=_as_probabilities(payload["probabilities"]),
            confidence=_as_float(payload["confidence"], "confidence"),
        )
    return ScoreAnswer(
        score=_as_float(payload["score"], "score"),
        legend=_as_legend(payload["legend"]),
        probabilities=_as_probabilities(payload["probabilities"]),
        confidence=_as_float(payload["confidence"], "confidence"),
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


def parse_response(payload: dict, request_id: str | None = None) -> SystemOneResponse:
    """Parse a strict System One response payload.

    Raises ValueError when the top-level keys are missing or malformed, an
    answer has an unknown type, or an answer or usage value has the wrong
    type.
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
        str(qid): answer_from_wire(answer) for qid, answer in answers_raw.items()
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
