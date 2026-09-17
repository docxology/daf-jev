"""Unit tests for daf_jev._types: wire shapes, strict parsing, cached views."""

from __future__ import annotations

import dataclasses

import pytest

from daf_jev._types import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    answer_from_wire,
    parse_response,
)


def _expect_value_error(make_question) -> None:
    """A ValueError must surface whether validation happens at build or wire time."""
    with pytest.raises(ValueError):
        question = make_question()
        question.to_wire()


# ---------------------------------------------------------------- to_wire ---


def test_noul_to_wire_omits_none_criteria() -> None:
    q = NoulQuestion(instructions="Is this about billing?")
    assert q.type == "noul"
    assert q.to_wire() == {"type": "noul", "instructions": "Is this about billing?"}


def test_noul_to_wire_with_criteria() -> None:
    q = NoulQuestion(
        instructions="Is this about billing?",
        criteria={"true": "a charge is present", "false": "no charge"},
    )
    assert q.to_wire() == {
        "type": "noul",
        "instructions": "Is this about billing?",
        "criteria": {"true": "a charge is present", "false": "no charge"},
    }


def test_choice_to_wire() -> None:
    q = ChoiceQuestion(
        instructions="What is the tone?", criteria={"calm": None, "angry": "hostile"}
    )
    assert q.type == "choice"
    assert q.to_wire() == {
        "type": "choice",
        "instructions": "What is the tone?",
        "criteria": {"calm": None, "angry": "hostile"},
    }


def test_score_to_wire() -> None:
    q = ScoreQuestion(instructions="Rate severity", criteria=["low", "high", "critical"])
    assert q.type == "score"
    assert q.to_wire() == {
        "type": "score",
        "instructions": "Rate severity",
        "criteria": ["low", "high", "critical"],
    }


def test_questions_are_frozen() -> None:
    q = NoulQuestion(instructions="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        q.instructions = "y"  # type: ignore[misc]


def test_score_requires_at_least_two_levels() -> None:
    _expect_value_error(lambda: ScoreQuestion(instructions="rate", criteria=["only"]))
    _expect_value_error(lambda: ScoreQuestion(instructions="rate", criteria=[]))


def test_choice_requires_non_empty_criteria() -> None:
    _expect_value_error(lambda: ChoiceQuestion(instructions="pick", criteria={}))


# ------------------------------------------------------- answers / parsing ---


def _answers_payload() -> dict:
    return {
        "model": "jev-latest",
        "usage": {"input_tokens": 120, "output_tokens": 45},
        "answers": {
            "billing": {"type": "noul", "noul": 0.87},
            "tone": {
                "type": "choice",
                "choice": "angry",
                "probabilities": {"calm": 0.2, "angry": 0.8},
                "confidence": 0.76,
            },
            "severity": {
                "type": "score",
                "score": 1.4,
                "legend": {"0": "low", "1": "high", "2": "critical"},
                "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3},
                "confidence": 0.9,
            },
        },
    }


def test_answer_from_wire_each_type() -> None:
    noul = answer_from_wire({"type": "noul", "noul": 0.5})
    assert isinstance(noul, NoulAnswer) and noul.type == "noul" and noul.noul == 0.5

    choice = answer_from_wire(
        {"type": "choice", "choice": "b", "probabilities": {"a": 0.1, "b": 0.9}, "confidence": 0.8}
    )
    assert isinstance(choice, ChoiceAnswer)
    assert choice.choice == "b" and choice.probabilities == {"a": 0.1, "b": 0.9}
    assert choice.confidence == 0.8

    score = answer_from_wire(
        {
            "type": "score",
            "score": 1.5,
            "legend": {"0": "low", "1": "high"},
            "probabilities": {"0": 0.5, "1": 0.5},
            "confidence": 0.7,
        }
    )
    assert isinstance(score, ScoreAnswer)
    assert score.score == 1.5
    assert score.legend == {"0": "low", "1": "high"}
    assert score.probabilities == {"0": 0.5, "1": 0.5}
    assert score.confidence == 0.7


def test_answer_from_wire_rejects_unknown_type_and_missing_keys() -> None:
    with pytest.raises(ValueError):
        answer_from_wire({"type": "vibe", "level": 9000})
    with pytest.raises(ValueError):
        answer_from_wire({"type": "noul"})  # missing "noul"
    with pytest.raises(ValueError):
        answer_from_wire({"type": "choice", "choice": "b"})  # missing probabilities


def test_parse_response_happy_path() -> None:
    resp = parse_response(_answers_payload(), "req-abc")
    assert resp.model == "jev-latest"
    assert resp.request_id == "req-abc"
    assert resp.usage.input_tokens == 120 and resp.usage.output_tokens == 45
    assert set(resp.answers) == {"billing", "tone", "severity"}
    assert resp.answers["billing"].type == "noul"
    assert resp.answers["tone"].type == "choice"
    assert resp.answers["severity"].type == "score"


def test_parse_response_request_id_defaults_to_none() -> None:
    resp = parse_response(_answers_payload(), None)
    assert resp.request_id is None


def test_parse_response_strict_unknown_answer_type() -> None:
    payload = _answers_payload()
    payload["answers"]["weird"] = {"type": "vibe", "level": 1}
    with pytest.raises(ValueError):
        parse_response(payload, None)


def test_parse_response_strict_missing_top_level_keys() -> None:
    payload = _answers_payload()
    del payload["answers"]
    with pytest.raises(ValueError):
        parse_response(payload, None)

    payload = _answers_payload()
    del payload["usage"]
    with pytest.raises(ValueError):
        parse_response(payload, None)


def test_parse_response_strict_missing_answer_key() -> None:
    payload = _answers_payload()
    del payload["answers"]["billing"]["noul"]
    with pytest.raises(ValueError):
        parse_response(payload, None)


def test_cached_type_views() -> None:
    resp = parse_response(_answers_payload(), None)
    assert set(resp.nouls) == {"billing"}
    assert set(resp.choices) == {"tone"}
    assert set(resp.scores) == {"severity"}
    # Views are cached: repeated access returns the same object.
    assert resp.nouls is resp.nouls
    assert resp.choices is resp.choices
    assert resp.scores is resp.scores
    assert resp.nouls["billing"].noul == 0.87
    assert resp.choices["tone"].choice == "angry"
    assert resp.scores["severity"].score == 1.4


def test_noul_to_wire_omits_criteria_when_all_descriptions_none() -> None:
    q = NoulQuestion(instructions="q", criteria={"true": None, "false": None})
    assert q.to_wire() == {"type": "noul", "instructions": "q"}


def test_score_to_wire_rejects_non_string_levels() -> None:
    _expect_value_error(lambda: ScoreQuestion(instructions="rate", criteria=[1, 2]))


def test_answer_from_wire_rejects_non_numeric_fields() -> None:
    with pytest.raises(ValueError):
        answer_from_wire({"type": "noul", "noul": "high"})


def test_answer_from_wire_rejects_non_dict_payload() -> None:
    with pytest.raises(ValueError):
        answer_from_wire(["type", "noul"])


def test_parse_response_rejects_non_dict_payload() -> None:
    with pytest.raises(ValueError):
        parse_response(["model", "answers", "usage"], None)


def test_parse_response_rejects_non_dict_answers_and_usage() -> None:
    payload = _answers_payload()
    payload["answers"] = ["not", "a", "dict"]
    with pytest.raises(ValueError):
        parse_response(payload, None)

    payload = _answers_payload()
    payload["usage"] = "5 tokens"
    with pytest.raises(ValueError):
        parse_response(payload, None)


def test_parse_response_rejects_missing_model_key() -> None:
    payload = _answers_payload()
    del payload["model"]
    with pytest.raises(ValueError):
        parse_response(payload, None)
