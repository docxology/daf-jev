"""Unit tests for daf_jev.questions.question_from_mapping (pure builder, no I/O)."""

from __future__ import annotations

import pytest

from daf_jev.questions import question_from_mapping


def test_choice_rejects_duplicate_option_after_str_coercion() -> None:
    # {1: ..., "1": ...} holds two distinct mapping keys that stringify to the
    # same option name; without collision tracking the second silently
    # overwrites the first.
    with pytest.raises(ValueError) as excinfo:
        question_from_mapping(
            {
                "type": "choice",
                "instructions": "Pick one",
                "criteria": {1: "int option", "1": "string option"},
            },
            context="questions file billing.yaml",
        )
    assert "questions file billing.yaml: duplicate option '1'" in str(excinfo.value)


def test_choice_rejects_empty_option_name() -> None:
    for name in ("", "   "):
        with pytest.raises(ValueError) as excinfo:
            question_from_mapping(
                {
                    "type": "choice",
                    "instructions": "Pick one",
                    "criteria": {name: "blank option", "calm": None},
                }
            )
        assert "choice option name must be non-empty" in str(excinfo.value)


def test_noul_criteria_keys_limited_to_true_and_false() -> None:
    with pytest.raises(ValueError) as excinfo:
        question_from_mapping(
            {
                "type": "noul",
                "instructions": "Is this billing?",
                "criteria": {"true": None, "yes": "not a noul key"},
            }
        )
    assert "'yes'" in str(excinfo.value)

    # Partial criteria stay legal: each key is optional, values are str|null.
    built = question_from_mapping(
        {
            "type": "noul",
            "instructions": "Is this billing?",
            "criteria": {"false": "not billing"},
        }
    )
    assert built.criteria == {"false": "not billing"}