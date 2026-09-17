"""Unit tests for daf_jev.compose: pure decision patterns over answers."""

from __future__ import annotations

import pytest

from daf_jev import ChoiceAnswer, NoulAnswer, ScoreAnswer, composite_score, confidence_gate
from daf_jev import route
from daf_jev.compose import pick, tiered_gate


def _score_answer(
    probabilities: dict[str, float],
    confidence: float = 0.9,
    score: float | None = None,
) -> ScoreAnswer:
    if score is None:
        # Server-guaranteed consistency: score equals the expected level index.
        score = sum(int(k) * p for k, p in probabilities.items())
    return ScoreAnswer(
        score=score,
        legend={str(i): f"level {i}" for i in range(len(probabilities))},
        probabilities=probabilities,
        confidence=confidence,
    )


def _choice_answer(choice: str, confidence: float) -> ChoiceAnswer:
    return ChoiceAnswer(
        choice=choice,
        probabilities={choice: confidence, "other": 1.0 - confidence},
        confidence=confidence,
    )


# --------------------------------------------------------- composite_score ---
def test_composite_score_default_equals_answer_score() -> None:
    answer = _score_answer({"0": 0.25, "1": 0.75})
    assert composite_score(answer) == pytest.approx(0.75)
    assert composite_score(answer) == pytest.approx(answer.score)


def test_composite_score_default_three_levels() -> None:
    answer = _score_answer({"0": 0.2, "1": 0.3, "2": 0.5})
    assert composite_score(answer) == pytest.approx(0.2 * 0 + 0.3 * 1 + 0.5 * 2)


def test_composite_score_reweights_the_distribution() -> None:
    # q_i = p_i * w_i / sum(p_j * w_j): p=[0.25, 0.75], w=[1, 3]
    # -> mass [0.25, 2.25] -> q=[0.1, 0.9] -> 0.9
    answer = _score_answer({"0": 0.25, "1": 0.75})
    assert composite_score(answer, weights=[1, 3]) == pytest.approx(0.9)


def test_composite_score_is_scale_invariant() -> None:
    answer = _score_answer({"0": 0.25, "1": 0.75})
    assert composite_score(answer, weights=[1, 3]) == pytest.approx(
        composite_score(answer, weights=[2, 6])
    )


def test_composite_score_weight_length_mismatch() -> None:
    answer = _score_answer({"0": 0.5, "1": 0.5})
    with pytest.raises(ValueError):
        composite_score(answer, weights=[1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        composite_score(answer, weights=[1.0])


def test_composite_score_rejects_zero_total_weight() -> None:
    answer = _score_answer({"0": 0.5, "1": 0.5})
    with pytest.raises(ValueError):
        composite_score(answer, weights=[0.0, 0.0])


def test_composite_score_rejects_weights_with_no_probable_mass() -> None:
    # All probability sits on level 0, whose weight is 0: no mass to normalize.
    answer = _score_answer({"0": 1.0, "1": 0.0})
    with pytest.raises(ValueError):
        composite_score(answer, weights=[0, 5])


def test_composite_score_rejects_non_finite_weights() -> None:
    answer = _score_answer({"0": 0.5, "1": 0.5})
    with pytest.raises(ValueError):
        composite_score(answer, weights=[1.0, float("nan")])
    with pytest.raises(ValueError):
        composite_score(answer, weights=[1.0, float("inf")])


def test_composite_score_allows_negative_weights_staying_in_range() -> None:
    # p=[0.2, 0.6, 0.2], w=[1, 1, -1]: mass [0.2, 0.6, -0.2], total 0.6
    # -> q=[1/3, 1, -1/3] -> 1/3, inside [min index, max index].
    answer = _score_answer({"0": 0.2, "1": 0.6, "2": 0.2})
    result = composite_score(answer, weights=[1, 1, -1])
    assert result == pytest.approx(1 / 3)
    assert 0 <= result <= 2


def test_composite_score_requires_probabilities() -> None:
    answer = ScoreAnswer(score=1.0, legend={}, probabilities={}, confidence=0.9)
    with pytest.raises(ValueError):
        composite_score(answer)
    with pytest.raises(ValueError):
        composite_score(answer, weights=[1.0, 2.0, 3.0])


# ------------------------------------------------------- confidence_gate -----


def test_confidence_gate_above_threshold_returns_primary_value() -> None:
    answer = _choice_answer("escalate", 0.95)
    assert confidence_gate(answer, threshold=0.8) == "escalate"


def test_confidence_gate_below_threshold_returns_fallback() -> None:
    answer = _choice_answer("auto_reply", 0.4)
    assert confidence_gate(answer, threshold=0.8) == "review"
    assert confidence_gate(answer, threshold=0.8, below="human") == "human"


def test_confidence_gate_duck_typed_answer_falls_back_to_str() -> None:
    # An answer with confidence but neither choice nor score: its str() is used.
    class Partial:
        confidence = 0.9

        def __str__(self) -> str:
            return "partial-answer"

    assert confidence_gate(Partial(), threshold=0.5) == "partial-answer"


def test_confidence_gate_rejects_noul_answers() -> None:
    with pytest.raises(TypeError):
        confidence_gate(NoulAnswer(0.9), threshold=0.5)


def test_confidence_gate_score_answer_uses_nearest_legend_level() -> None:
    answer = _score_answer({"0": 0.1, "1": 0.6, "2": 0.3}, score=1.4)
    assert confidence_gate(answer, threshold=0.8) == "level 1"


def test_confidence_gate_score_clamps_level_to_probability_range() -> None:
    # round(2.6) = 3 exceeds the probable levels; clamp to the max index.
    answer = _score_answer({"0": 0.1, "1": 0.6, "2": 0.3}, score=2.6)
    assert confidence_gate(answer, threshold=0.8) == "level 2"


def test_confidence_gate_score_falls_back_to_score_without_legend_entry() -> None:
    answer = ScoreAnswer(
        score=1.4,
        legend={"0": "low"},  # no description for the clamped level 1
        probabilities={"0": 1.0, "1": 0.0},
        confidence=0.9,
    )
    assert confidence_gate(answer, threshold=0.8) == "1.4"


def test_confidence_gate_score_without_probabilities_or_legend() -> None:
    answer = ScoreAnswer(score=1.4, legend={}, probabilities={}, confidence=1.0)
    assert confidence_gate(answer, threshold=0.8) == "1.4"


def test_confidence_gate_score_below_threshold_returns_fallback() -> None:
    answer = _score_answer({"0": 0.5, "1": 0.5}, score=1.0, confidence=0.3)
    assert confidence_gate(answer, threshold=0.8) == "review"


# ---------------------------------------------------------------- route -----


def test_route_dispatches_to_matching_handler() -> None:
    answer = _choice_answer("angry", 0.9)
    handlers = {"calm": lambda: "calm-path", "angry": lambda: "angry-path"}
    assert route(answer, handlers) == "angry-path"


def test_route_rejects_answers_without_choice() -> None:
    with pytest.raises(TypeError):
        route(_score_answer({"0": 1.0}), {"calm": lambda: "calm-path"})


def test_route_low_confidence_without_fallback_raises() -> None:
    answer = _choice_answer("calm", 0.1)
    with pytest.raises(ValueError):
        route(answer, {"calm": lambda: "calm-path"}, min_confidence=0.5)


def test_route_unmapped_choice_without_fallback_raises() -> None:
    answer = _choice_answer("sarcastic", 0.99)
    with pytest.raises(KeyError):
        route(answer, {"calm": lambda: "calm-path"})


def test_route_fallback_on_low_confidence() -> None:
    answer = _choice_answer("calm", 0.2)
    handlers = {"calm": lambda: "calm-path", "angry": lambda: "angry-path"}
    assert route(
        answer, handlers, min_confidence=0.5, fallback=lambda: "fallback-path"
    ) == "fallback-path"


def test_route_fallback_on_missing_handler() -> None:
    answer = _choice_answer("sarcastic", 0.99)
    handlers = {"calm": lambda: "calm-path"}
    assert route(answer, handlers, fallback=lambda: "fallback-path") == "fallback-path"


def test_pick_returns_dict_of_dispatched_results() -> None:
    actions = {"calm": lambda: "auto-reply", "angry": lambda: "escalate"}
    answers = {
        "tone": _choice_answer("angry", 0.9),
        "politeness": _choice_answer("calm", 0.9),
    }
    assert pick(actions, answers) == {
        "tone": "escalate",
        "politeness": "auto-reply",
    }


def test_pick_skips_answers_without_choice() -> None:
    actions = {"calm": lambda: "auto-reply"}
    answers = {
        "tone": _choice_answer("calm", 0.9),
        "billing": NoulAnswer(0.87),
        "severity": _score_answer({"0": 1.0}),
    }
    assert pick(actions, answers) == {"tone": "auto-reply"}


# ----------------------------------------------------------- tiered_gate -----


def test_tiered_gate_automates_at_or_above_high_threshold() -> None:
    assert tiered_gate(_choice_answer("calm", 0.9)) == "automate"
    # Exactly at the high threshold routes to the high label (>= semantics).
    assert tiered_gate(_choice_answer("calm", 0.85)) == "automate"


def test_tiered_gate_reviews_between_thresholds() -> None:
    assert tiered_gate(_choice_answer("escalate", 0.7)) == "review"
    # Exactly at the low threshold is still the middle tier (>= semantics).
    assert tiered_gate(_choice_answer("escalate", 0.6)) == "review"


def test_tiered_gate_escalates_below_low_threshold() -> None:
    assert tiered_gate(_choice_answer("human", 0.3)) == "escalate"


def test_tiered_gate_custom_thresholds_and_labels() -> None:
    answer = _choice_answer("calm", 0.75)
    kwargs = {
        "high": 0.9,
        "low": 0.5,
        "high_label": "send",
        "middle_label": "check",
        "low_label": "human",
    }
    assert tiered_gate(_choice_answer("calm", 0.95), **kwargs) == "send"
    assert tiered_gate(answer, **kwargs) == "check"
    assert tiered_gate(_choice_answer("calm", 0.2), **kwargs) == "human"


def test_tiered_gate_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError):
        tiered_gate(_choice_answer("calm", 0.7), high=0.6, low=0.9)


def test_tiered_gate_rejects_empty_labels() -> None:
    with pytest.raises(ValueError):
        tiered_gate(_choice_answer("calm", 0.7), high_label="")
    with pytest.raises(ValueError):
        tiered_gate(_choice_answer("calm", 0.7), low_label="")


def test_tiered_gate_rejects_answers_without_confidence() -> None:
    with pytest.raises(TypeError):
        tiered_gate(NoulAnswer(0.9))


def test_tiered_gate_accepts_score_answers() -> None:
    answer = _score_answer({"0": 0.5, "1": 0.5}, confidence=0.7)
    assert tiered_gate(answer) == "review"
