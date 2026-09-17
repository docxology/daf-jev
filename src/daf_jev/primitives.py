"""Ergonomic builders for TypeSafe question primitives.

Free functions :func:`noul`, :func:`choice`, :func:`score` build the frozen
wire dataclasses from :mod:`daf_jev._types`, validating eagerly so mistakes
surface at construction time rather than at request time.
:class:`QuestionSet` is a ``Mapping[str, Question]`` container that composes
questions for a single ``ask`` call. No I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Optional

from daf_jev._types import ChoiceQuestion, NoulQuestion, Question, ScoreQuestion

__all__ = ["noul", "choice", "score", "QuestionSet"]


def noul(
    instructions: object,
    *,
    true_desc: Optional[str] = None,
    false_desc: Optional[str] = None,
) -> NoulQuestion:
    """Build a yes/no question.

    ``true_desc`` / ``false_desc`` optionally clarify what yes and no mean;
    they become the Noul ``criteria`` map. When both are omitted, ``criteria``
    is left off the wire entirely.
    """
    criteria = None
    if true_desc is not None or false_desc is not None:
        criteria = {"true": true_desc, "false": false_desc}
    return NoulQuestion(instructions=instructions, criteria=criteria)


def choice(
    instructions: object,
    options: Mapping[str, Optional[str]],
) -> ChoiceQuestion:
    """Build a multiple-choice question.

    ``options`` maps option name to an optional description (``None`` sends a
    null description). At least one option is required.
    """
    criteria = dict(options)
    if not criteria:
        raise ValueError("choice() requires at least one option")
    return ChoiceQuestion(instructions=instructions, criteria=criteria)


def score(instructions: object, levels: Sequence[str]) -> ScoreQuestion:
    """Build an ordered-scale question.

    ``levels`` are the level descriptions, ordered from the low end of the
    scale to the high end. At least two levels are required.
    """
    criteria = list(levels)
    if len(criteria) < 2:
        raise ValueError("score() requires at least 2 levels")
    return ScoreQuestion(instructions=instructions, criteria=criteria)


class QuestionSet(Mapping[str, Question]):
    """An ordered, mutable ``Mapping[str, Question]`` of questions under ids.

    Feeds :meth:`JevClient.ask` directly. Builder methods mirror the free
    functions with the question id as the first argument and return ``self``,
    so sets can be composed fluently::

        QuestionSet().noul("refund", "Does the customer request a refund?") \\
                     .score("severity", ["Cosmetic", "Broken", "Blocking"])
    """

    def __init__(self, questions: Optional[Mapping[str, Question]] = None) -> None:
        self._questions: dict[str, Question] = dict(questions) if questions else {}

    # -- Mapping protocol ---------------------------------------------------

    def __getitem__(self, key: str) -> Question:
        return self._questions[key]

    def __iter__(self):
        return iter(self._questions)

    def __len__(self) -> int:
        return len(self._questions)

    def __repr__(self) -> str:
        return f"QuestionSet({self._questions!r})"

    # -- Mutation -----------------------------------------------------------

    def add(self, id: str, q: Question) -> "QuestionSet":
        """Add (or replace) ``q`` under ``id``; returns ``self``."""
        self._questions[id] = q
        return self

    def merge(self, other: Mapping[str, Question]) -> "QuestionSet":
        """Merge every question from ``other`` into this set; returns ``self``.

        Ids already present are overwritten by ``other``'s entries.
        """
        items = other._questions if isinstance(other, QuestionSet) else other
        self._questions.update(items)
        return self

    # -- Wire shape ---------------------------------------------------------

    def to_wire(self) -> dict[str, dict]:
        """Return ``{id: question.to_wire()}``, ready for the request body."""
        return {qid: q.to_wire() for qid, q in self._questions.items()}

    # -- Builders (mirror the free functions) --------------------------------

    def noul(
        self,
        id: str,
        instructions: object,
        *,
        true_desc: Optional[str] = None,
        false_desc: Optional[str] = None,
    ) -> "QuestionSet":
        return self.add(id, noul(instructions, true_desc=true_desc, false_desc=false_desc))

    def choice(
        self,
        id: str,
        instructions: object,
        options: Mapping[str, Optional[str]],
    ) -> "QuestionSet":
        return self.add(id, choice(instructions, options))

    def score(self, id: str, instructions: object, levels: Sequence[str]) -> "QuestionSet":
        return self.add(id, score(instructions, levels))
