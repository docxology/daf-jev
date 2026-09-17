"""Live integration tests against the real TypeSafe API.

Skipped entirely unless JEV_API_KEY is present in the process environment.
The key is read from os.environ ONLY — the project `.env` is never read here.
"""

from __future__ import annotations

import os

import pytest

from daf_jev import ChoiceQuestion, JevClient, NoulQuestion, ScoreQuestion

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("JEV_API_KEY"), reason="JEV_API_KEY not set"
    ),
]


def _questions() -> dict:
    return {
        "is_billing": NoulQuestion(
            instructions="Is this customer message about a billing problem?"
        ),
        "tone": ChoiceQuestion(
            instructions="What is the customer's tone?",
            criteria={"calm": None, "frustrated": "annoyed but civil", "angry": "hostile"},
        ),
        "severity": ScoreQuestion(
            instructions="How severe is the issue?",
            criteria=["minor inconvenience", "noticeable problem", "blocking emergency"],
        ),
    }


def test_live_mixed_ask_shapes() -> None:
    client = JevClient(api_key=os.environ["JEV_API_KEY"])
    try:
        resp = client.ask(
            "I was charged twice this month and nobody has responded to my emails.",
            _questions(),
        )
    finally:
        client.close()

    assert isinstance(resp.model, str) and resp.model
    assert resp.usage.input_tokens >= 0 and resp.usage.output_tokens >= 0

    noul = resp.nouls["is_billing"]
    assert 0.0 <= noul.noul <= 1.0

    choice = resp.choices["tone"]
    assert choice.choice in {"calm", "frustrated", "angry"}
    assert abs(sum(choice.probabilities.values()) - 1.0) < 1e-6
    assert 0.0 <= choice.confidence <= 1.0

    score = resp.scores["severity"]
    assert 0.0 <= score.score <= 2.0
    assert abs(sum(score.probabilities.values()) - 1.0) < 1e-6
    assert 0.0 <= score.confidence <= 1.0


def test_live_models_non_empty() -> None:
    client = JevClient(api_key=os.environ["JEV_API_KEY"])
    try:
        cards = client.models()
    finally:
        client.close()

    assert len(cards) > 0
    assert all(isinstance(card.name, str) and card.name for card in cards)
