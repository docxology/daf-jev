"""Unit tests for daf_jev.primitives: builders, validation, QuestionSet."""

from __future__ import annotations

import pytest

from daf_jev import ChoiceQuestion, NoulQuestion, QuestionSet, ScoreQuestion
from daf_jev import choice, noul, score


# ------------------------------------------------------------- builders -----


def test_noul_builder() -> None:
    q = noul("Is this about billing?")
    assert isinstance(q, NoulQuestion)
    assert q.to_wire() == {"type": "noul", "instructions": "Is this about billing?"}


def test_noul_builder_with_descriptions() -> None:
    q = noul("Charged twice?", true_desc="a charge exists", false_desc="no charge")
    wire = q.to_wire()
    assert wire["criteria"]["true"] == "a charge exists"
    assert wire["criteria"]["false"] == "no charge"


def test_choice_builder() -> None:
    q = choice("What is the tone?", {"calm": None, "angry": "hostile"})
    assert isinstance(q, ChoiceQuestion)
    assert q.to_wire()["criteria"] == {"calm": None, "angry": "hostile"}


def test_score_builder() -> None:
    q = score("Rate severity", ["low", "high", "critical"])
    assert isinstance(q, ScoreQuestion)
    assert q.to_wire()["criteria"] == ["low", "high", "critical"]


def test_builders_reject_invalid_criteria() -> None:
    with pytest.raises(ValueError):
        choice("pick", {})
    with pytest.raises(ValueError):
        score("rate", ["only-one-level"])


# ------------------------------------------------------------ QuestionSet ---


def test_question_set_add_and_getitem() -> None:
    qs = QuestionSet()
    qs.add("billing", noul("Is this about billing?"))
    assert isinstance(qs["billing"], NoulQuestion)


def test_question_set_mapping_protocol() -> None:
    qs = QuestionSet()
    qs.add("a", noul("q a"))
    qs.add("b", choice("q b", {"x": None}))
    assert len(qs) == 2
    assert set(iter(qs)) == {"a", "b"}
    assert "a" in qs and "b" in qs and "c" not in qs
    assert dict(qs)["a"].to_wire() == {"type": "noul", "instructions": "q a"}


def test_question_set_merge_combines() -> None:
    first = QuestionSet()
    first.add("a", noul("q a"))
    second = QuestionSet()
    second.add("b", score("q b", ["low", "high"]))
    # merge may mutate-and-return-self, return a new set, or return None after
    # mutating; all satisfy the contract, so fall back to the receiver.
    combined = first.merge(second) or first
    assert set(combined) == {"a", "b"}
    assert combined["b"].type == "score"


def test_question_set_to_wire() -> None:
    qs = QuestionSet()
    qs.add("billing", noul("Is this about billing?"))
    qs.add("severity", score("Rate", ["low", "high"]))
    assert qs.to_wire() == {
        "billing": {"type": "noul", "instructions": "Is this about billing?"},
        "severity": {
            "type": "score",
            "instructions": "Rate",
            "criteria": ["low", "high"],
        },
    }


def test_question_set_repr_shows_questions() -> None:
    qs = QuestionSet()
    qs.add("billing", noul("Is this about billing?"))
    text = repr(qs)
    assert text.startswith("QuestionSet(")
    assert "billing" in text


def test_question_set_builder_methods_chain_and_return_self() -> None:
    qs = QuestionSet()
    result = (
        qs.noul("billing", "Refund requested?", true_desc="yes", false_desc="no")
        .choice("tone", "What tone?", {"calm": None, "angry": "hostile"})
        .score("severity", "Rate it", ["low", "high"])
    )
    assert result is qs
    assert isinstance(qs["billing"], NoulQuestion)
    assert isinstance(qs["tone"], ChoiceQuestion)
    assert isinstance(qs["severity"], ScoreQuestion)
    assert qs["billing"].to_wire()["criteria"] == {"true": "yes", "false": "no"}
    assert qs.to_wire()["severity"]["criteria"] == ["low", "high"]
