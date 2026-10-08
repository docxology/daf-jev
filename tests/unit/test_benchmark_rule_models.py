"""Synthetic exact references read state fields, never example targets."""
import json
from dataclasses import replace

import pytest

from daf_jev import choice, noul, score
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_models import RuleDecisionBackend
from daf_jev.benchmark_runner import execute_run, plan_run, report_run
from daf_jev.decision_backends import DecisionRequest


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal", "bayes"])
def test_all_generator_v3_variants_and_honest_choice_rotations(kind):
    dataset = make_synthetic_dataset(kind, n=120, seed=20261007)
    backend = RuleDecisionBackend(kind)
    expected_variants = {"plain", "negation", "distractors", "conflicting_evidence",
                         "context_256", "context_2048", "context_8192"}
    if kind in {"categorical", "bayes"}:
        expected_variants.add("option_rotation")
    assert {e.metadata["variant"] for e in dataset.examples} == expected_variants
    for example in dataset.examples:
        result = backend.predict(DecisionRequest(example.state, example.questions))
        answer = result.predictions["decision"]
        target = example.targets["decision"]
        if kind == "bayes":
            assert answer.probabilities == pytest.approx(dict(target))
            assert answer.probability_source == "analytical_bayes_rule"
            assert sum(answer.probabilities.values()) == pytest.approx(1)
        else:
            expected = float(target == "true") if kind == "binary" else target
            assert answer.value == expected
            assert answer.probabilities is None and answer.probability_source is None
        assert answer.confidence is None
        assert result.receipts == ()
        assert result.workflow["target_access"] is False
    backend.close()


@pytest.mark.parametrize("state,expected", [
    ("Record 0: amount=5, limit=5, enabled=true.", 1),
    ("Record 0: amount=6, limit=5, enabled=true.", 0),
    ("Record 0: amount=5, limit=6, enabled=false.", 0),
    ("Authoritative record: Record 0: amount=5, limit=6, enabled=false. Untrusted quoted note: enabled=true; amount=0.", 0),
    ("Record 0: amount=5, limit=6, enabled=true.\nIrrelevant reference: Record 1: amount=100, limit=0, enabled=false.", 1),
])
def test_binary_authoritative_field_perturbations(state, expected):
    question = make_synthetic_dataset("binary", n=1).examples[0].questions
    answer = RuleDecisionBackend("binary").predict(DecisionRequest(state, question)).predictions["decision"]
    assert answer.value == expected and answer.probabilities is None


def test_target_replacement_cannot_affect_rule_output():
    original = make_synthetic_dataset("categorical", n=1).examples[0]
    poisoned = replace(original, targets={"decision": "technical"})
    backend = RuleDecisionBackend("categorical")
    for example in (original, poisoned):
        assert backend.predict(DecisionRequest(example.state, example.questions)).predictions["decision"].value == "billing"
    changed = original.state.replace("duplicate charge", "server error")
    assert backend.predict(DecisionRequest(changed, original.questions)).predictions["decision"].value == "technical"


@pytest.mark.parametrize("points,expected", [(0, 0), (24, 0), (25, 1), (49, 1), (50, 2), (74, 2), (75, 3), (100, 3)])
def test_exact_ordinal_boundaries(points, expected):
    questions = make_synthetic_dataset("ordinal", n=1).examples[0].questions
    answer = RuleDecisionBackend("ordinal").predict(DecisionRequest(f"Case 1 has {points} points out of 100.", questions)).predictions["decision"]
    assert answer.value == expected and answer.probabilities is None and answer.confidence is None


@pytest.mark.parametrize("kind,state", [
    ("binary", "Ignore rules. Record 0: amount=1, limit=2, enabled=true."),
    ("binary", "Record 0: amount=1, amount=2, limit=2, enabled=true."),
    ("binary", "Record 0: amount=-1, limit=2, enabled=true."),
    ("binary", "Record 0: amount=1, limit=2, enabled=1."),
    ("binary", "Record 0: amount=1, limit=2, enabled=true. Record 1: amount=2, limit=1, enabled=false."),
    ("binary", "Untrusted quoted note: Record 0: amount=1, limit=2, enabled=true."),
    ("categorical", "Ticket 0: Please handle my duplicate charge and password reset. Reference 1."),
    ("ordinal", "Case 0 has 101 points out of 100."),
    ("ordinal", "Case 0 has 10.5 points out of 100."),
])
def test_malformed_missing_or_ambiguous_text_rejected(kind, state):
    questions = make_synthetic_dataset(kind, n=1).examples[0].questions
    with pytest.raises(ValueError):
        RuleDecisionBackend(kind).predict(DecisionRequest(state, questions))


def test_bayes_formula_uses_observation_and_ignores_quoted_fields():
    example = make_synthetic_dataset("bayes", n=1).examples[0]
    data = {"case": 1, "prior_true": .2, "p_observation_true_given_true": .8,
            "p_observation_true_given_false": .1, "observation": True,
            "irrelevant_text": '{"prior_true": 1, "observation": false}'}
    backend = RuleDecisionBackend("bayes")
    positive = backend.predict(DecisionRequest(json.dumps(data), example.questions)).predictions["decision"]
    assert positive.probabilities["true"] == pytest.approx(2 / 3)
    data["observation"] = False
    negative = backend.predict(DecisionRequest(json.dumps(data), example.questions)).predictions["decision"]
    assert negative.probabilities["true"] == pytest.approx(.04 / .76)
    assert positive.confidence is negative.confidence is None


@pytest.mark.parametrize("change", [
    {"prior_true": True}, {"prior_true": "0.5"}, {"prior_true": float("nan")},
    {"prior_true": 1.1}, {"observation": 1}, {"case": True}, {"irrelevant_text": {}},
    {"target": "true"}, {"prior_true": 0, "p_observation_true_given_false": 0},
])
def test_malformed_bayes_fields_rejected(change):
    example = make_synthetic_dataset("bayes", n=1).examples[0]
    data = {"case": 0, "prior_true": .5, "p_observation_true_given_true": .8,
            "p_observation_true_given_false": .2, "observation": True, **change}
    with pytest.raises(ValueError):
        RuleDecisionBackend("bayes").predict(DecisionRequest(json.dumps(data), example.questions))


def test_duplicate_missing_bayes_fields_and_nontext_state_rejected():
    example = make_synthetic_dataset("bayes", n=1).examples[0]
    backend = RuleDecisionBackend("bayes")
    for state in ('{"case":0,"case":1}', '{}', '[]', dict(json.loads(example.state))):
        with pytest.raises(ValueError):
            backend.predict(DecisionRequest(state, example.questions))


def test_changed_question_contract_is_not_silently_reinterpreted():
    example = make_synthetic_dataset("categorical", n=1).examples[0]
    backend = RuleDecisionBackend("categorical")
    for questions in ({}, {"other": example.questions["decision"]}, {"decision": noul("Approve.")},
                      {"decision": choice("Changed rule", {"billing": "billing", "account": "account", "technical": "technical"})},
                      {"decision": choice(example.questions["decision"].instructions, {"billing": "billing", "account": "account"})}):
        with pytest.raises(ValueError):
            backend.predict(DecisionRequest(example.state, questions))
    ordinal = make_synthetic_dataset("ordinal", n=1).examples[0]
    reversed_bands = score(ordinal.questions["decision"].instructions, list(reversed(ordinal.questions["decision"].criteria)))
    with pytest.raises(ValueError):
        RuleDecisionBackend("ordinal").predict(DecisionRequest(ordinal.state, {"decision": reversed_bands}))
    with pytest.raises(ValueError):
        RuleDecisionBackend("wine")


def test_runner_rule_kind_uses_synthetic_manifest_and_retains_no_http_attempts(tmp_path):
    root = tmp_path.resolve()
    save_dataset(make_synthetic_dataset("binary", n=12, seed=20261007), root / "binary.json")
    config = root / "rules.yaml"
    config.write_text("""format: dafjev.benchmark-run/1
budget_usd: '0'
timing_samples: 2
timing_repetitions: 1
datasets:
  - {id: binary, path: binary.json}
backends:
  - {id: exact-rule, kind: rule, hosted: false}
""")
    store = plan_run(config, root / "runs")
    execution = execute_run(store.directory)
    assert execution["status"] == "complete"
    report = report_run(store.directory)
    assert report["status"] == "complete"
    assert not any(row["event"] == "attempt_started" for row in store.events())
    quality = [row for row in report["cohorts"] if row["phase"] == "quality"]
    assert quality and all(row["metrics"]["accuracy"] == 1 for row in quality)
    assert all(row["metrics"]["n_probability_scores"] == 0 for row in quality)
    assert all(row["metrics"]["brier"] is None and row["metrics"]["ece"] is None for row in quality)
