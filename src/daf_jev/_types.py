"""Wire dataclasses for the TypeSafe Jev (System One) API.

Pure data module: no I/O. Shapes follow docs/ARCHITECTURE.md ("Wire facts")
as verified against the local docs snapshot (docs/reference/, id
b79c9cd6008489f1).
"""

from __future__ import annotations

import dataclasses
from functools import cached_property
from typing import ClassVar, Mapping, Optional, Sequence, Union

JSONContent = Union[str, list, dict]

__all__ = [
    "JSONContent",
    "Question",
    "NoulQuestion",
    "ChoiceQuestion",
    "ScoreQuestion",
    "Answer",
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Usage",
    "SystemOneResponse",
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
    criteria: Optional[dict] = None

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
    criteria: Mapping[str, Optional[str]]

    def to_wire(self) -> dict:
        if not self.criteria:
            raise ValueError("choice question requires non-empty criteria (options)")
        return {
            "type": self.type,
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
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


Question = Union[NoulQuestion, ChoiceQuestion, ScoreQuestion]


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


Answer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]

_ANSWER_TYPES: dict[str, type] = {
    cls.type: cls for cls in (NoulAnswer, ChoiceAnswer, ScoreAnswer)
}


def _require(payload: dict, cls: type) -> dict:
    """Return the payload keys needed by ``cls`` or raise ValueError."""
    missing = [
        f.name for f in dataclasses.fields(cls) if f.name not in payload
    ]
    if missing:
        raise ValueError(f"{cls.type} answer is missing required keys: {missing}")
    return payload


def _as_float(payload: dict, key: str) -> float:
    value = payload[key]
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number, got {value!r}") from exc


def answer_from_wire(payload: dict) -> Answer:
    """Parse a strict wire answer dict into its dataclass.

    Raises ValueError for an unknown answer type or missing keys.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"answer must be a dict, got {type(payload).__name__}")
    answer_type = payload.get("type")
    cls = _ANSWER_TYPES.get(answer_type)
    if cls is None:
        raise ValueError(f"unknown answer type: {answer_type!r}")
    _require(payload, cls)
    if cls is NoulAnswer:
        return NoulAnswer(noul=_as_float(payload, "noul"))
    if cls is ChoiceAnswer:
        return ChoiceAnswer(
            choice=str(payload["choice"]),
            probabilities={
                str(k): _as_float(payload["probabilities"], str(k))
                for k in payload["probabilities"]
            },
            confidence=_as_float(payload, "confidence"),
        )
    return ScoreAnswer(
        score=_as_float(payload, "score"),
        legend={str(k): str(v) for k, v in payload["legend"].items()},
        probabilities={
            str(k): _as_float(payload["probabilities"], str(k))
            for k in payload["probabilities"]
        },
        confidence=_as_float(payload, "confidence"),
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
    request_id: Optional[str] = None

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


def parse_response(payload: dict, request_id: Optional[str] = None) -> SystemOneResponse:
    """Parse a strict System One response payload.

    Raises ValueError when the top-level keys are missing, an answer has an
    unknown type, or an answer is missing required keys.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"response payload must be a dict, got {type(payload).__name__}"
        )
    for key in ("model", "answers", "usage"):
        if key not in payload:
            raise ValueError(f"response is missing required key: {key!r}")
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
        model=str(payload["model"]),
        answers=answers,
        usage=Usage(
            input_tokens=int(usage_raw.get("input_tokens", 0)),
            output_tokens=int(usage_raw.get("output_tokens", 0)),
        ),
        request_id=request_id,
    )
