"""Validation custody, conservative group counts and offline policy replay."""

from dataclasses import replace

import pytest

from daf_jev.benchmark_policies import (
    calibrate_gate,
    entropy_reask,
    replay_policy,
    wilson_upper,
)


def _row(i, *, split="validation", confidence=.9, target="a", prediction="a", **kw):
    return {"example_id": str(i), "question_id": "decision", "group_id": str(i),
            "split": split, "target": target, "prediction": prediction,
            "confidence": confidence, "probabilities": {"a": .9, "b": .1},
            "error": None, "latency_s": .1, "cost_usd": .01, **kw}


def test_wilson_admission_requires_independent_validation_evidence():
    assert wilson_upper(0, 10) > .05
    gate = calibrate_gate([_row(i) for i in range(80)])
    assert gate.status == "admitted" and gate.threshold == .9
    assert gate.wilson_upper <= .05 and gate.n_groups == 80
    repeated = calibrate_gate([_row(1) for _ in range(1000)])
    assert repeated.status == "insufficient_evidence"
    for split in ("train", "test"):
        with pytest.raises(ValueError, match="validation-only"):
            calibrate_gate([_row(1, split=split)])


def test_fit_selects_confident_low_error_groups_and_soft_targets_rejected():
    rows = [_row(i) for i in range(80)] + [_row(90, confidence=.4, prediction="b")]
    gate = calibrate_gate(rows)
    assert gate.threshold == .9 and gate.n_errors == 0
    with pytest.raises(ValueError, match="hard labels"):
        calibrate_gate([_row(1, target={"a": .9, "b": .1})])


def test_gate_hold_abstains_and_cascade_charges_only_invoked_rows():
    rows = [_row(1), _row(2, confidence=.2, prediction="b")]
    strong = [_row(1, cost_usd=1), _row(2, confidence=.99, cost_usd=.03, latency_s=.5)]
    replay = replay_policy(rows, policy="cascade", threshold=.8, strong_rows=strong)
    assert replay[0]["strong_invoked"] is False and replay[0]["cost_usd"] == .01
    assert replay[1]["strong_invoked"] is True and replay[1]["cost_usd"] == "0.04"
    assert replay[1]["latency_s"] == .6 and replay[1]["prediction"] == "a"
    hold = calibrate_gate([_row(1)])
    assert replay_policy(rows, policy="gate", gate=hold)[0]["abstained"] is True
    missing = replay_policy(rows, policy="cascade", threshold=.99)
    assert all(r["error"] == "missing_strong_receipt" and r["cost_usd"] is None for r in missing)
    with pytest.raises(ValueError, match="align"):
        replay_policy([rows[1]], policy="cascade", threshold=.8,
                      strong_rows=[_row(2, target="different")])


def test_entropy_policy_is_explicit_bounded_oracle_simulation():
    rows = {"a": {"no": .9, "yes": .1}, "b": {"no": .5, "yes": .5},
            "c": {"no": .3, "yes": .7}, "d": {"no": .4, "yes": .6}}
    oracle = {var: "yes" for var in rows}
    result = entropy_reask(rows, oracle)
    assert result["simulation"] is True
    assert [r["variable"] for r in result["reveals"]] == ["b", "d", "c"]
    assert result["posteriors"]["a"] == rows["a"]
    assert result["posteriors"]["b"] == {"no": 0., "yes": 1.}
    assert entropy_reask(rows, oracle, max_reveals=0)["reveals"] == []
    with pytest.raises(ValueError, match="three"):
        entropy_reask(rows, oracle, max_reveals=4)


def test_policy_failure_modes_and_exact_decimal_replay():
    rows = [_row(1, confidence=.2, cost_usd="0.10")]
    strong = [_row(1, cost_usd="0.20")]
    assert replay_policy(rows, policy="cascade", threshold=.8, strong_rows=strong)[0]["cost_usd"] == "0.30"
    with pytest.raises(ValueError, match="duplicate"):
        replay_policy(rows, policy="cascade", threshold=.8, strong_rows=strong + strong)
    with pytest.raises(ValueError, match="explicit"):
        replay_policy(rows, policy="gate")
    with pytest.raises(ValueError):
        replay_policy(rows, policy="unknown")
    with pytest.raises(ValueError):
        replay_policy(rows, policy="gate", threshold=float("nan"))
    with pytest.raises(ValueError):
        calibrate_gate([_row(1, confidence=float("nan"))])
    with pytest.raises(ValueError):
        wilson_upper(2, 1)
    with pytest.raises(ValueError):
        wilson_upper(0, 1, z=float("nan"))
    with pytest.raises(ValueError):
        entropy_reask({"a": {"x": 1.}}, {}, max_reveals=1)
    with pytest.raises(ValueError):
        entropy_reask({"a": {"x": 1.}}, {"a": "x"}, asked=["missing"])


def test_reported_aggregate_overages_survive_every_offline_policy():
    from daf_jev.benchmark_metrics import score_predictions

    rows = [_row(1, confidence=.2, cost_usd="18000000000.000000000000000003")]
    direct = replay_policy(rows, policy="direct")
    assert score_predictions(direct)["total_cost_usd"] == rows[0]["cost_usd"]
    gated = replay_policy(rows, policy="gate", threshold=.8)
    assert score_predictions(gated)["total_cost_usd"] == rows[0]["cost_usd"]
    cascade = replay_policy(rows, policy="cascade", threshold=.8,
                            strong_rows=[_row(1, cost_usd="0.000000000000000002")])
    assert score_predictions(cascade)["total_cost_usd"] == "18000000000.000000000000000005"


@pytest.mark.parametrize("bad", [-.1, True, float("nan"), float("inf"), "1E1000000", "0.0000000000000000001"])
def test_replay_validates_each_consumed_known_cost_before_unknown_propagation(bad):
    weak = [_row(1, confidence=.9, cost_usd=bad)]
    with pytest.raises(ValueError):
        replay_policy(weak, policy="direct")
    with pytest.raises(ValueError):
        replay_policy(weak, policy="gate", threshold=.8)
    with pytest.raises(ValueError):
        replay_policy([_row(1, confidence=.2, cost_usd=bad)], policy="cascade", threshold=.8,
                      strong_rows=[_row(1, cost_usd=None)])
    with pytest.raises(ValueError):
        replay_policy([_row(1, confidence=.2, cost_usd=None)], policy="cascade", threshold=.8,
                      strong_rows=[_row(1, cost_usd=bad)])
    # An uninvoked strong arm incurs no charge and is not consumed.
    accepted = replay_policy([_row(1, confidence=.9, cost_usd="0.01")], policy="cascade", threshold=.8,
                            strong_rows=[_row(1, cost_usd=bad)])
    assert accepted[0]["strong_invoked"] is False and accepted[0]["cost_usd"] == "0.01"


def test_cascade_retains_strong_belief_provenance_and_stage_identities():
    weak = _row(1, confidence=.2, backend_id="weak", probability_source="native",
                confidence_semantics="provider_defined", probability_rounding_digits=2)
    strong = _row(1, confidence=.9, backend_id="strong", probability_source="classifier",
                  confidence_semantics="top_probability", probability_rounding_digits=None)
    result = replay_policy([weak], policy="cascade", threshold=.8, strong_rows=[strong])[0]
    assert result["backend_id"] == result["strong_backend_id"] == "strong"
    assert result["weak_backend_id"] == "weak"
    assert result["probability_source"] == "classifier"
    assert result["confidence_semantics"] == "top_probability"
    assert result["probability_rounding_digits"] is None


def test_binary_hard_numeric_gate_labels_match_boolean_distribution_vocabulary():
    rows = [_row(i, target=1, prediction=.9, probabilities={"false": .1, "true": .9}) for i in range(80)]
    gate = calibrate_gate(rows)
    assert gate.status == "admitted" and gate.n_errors == 0
    tied = [_row(i, target=1, prediction=.5, probabilities={"false": .5, "true": .5}) for i in range(80)]
    assert calibrate_gate(tied).n_errors == 0


@pytest.mark.parametrize("change", [{"status": "unknown"}, {"threshold": True}, {"threshold": float("nan")},
    {"max_risk": float("nan")}, {"confidence_level": .9}, {"n_groups": True}, {"n_groups": 0},
    {"validation_groups": 79}, {"n_errors": 81}, {"wilson_upper": .001}, {"wilson_upper": None}])
def test_frozen_gate_rejects_inconsistent_or_fabricated_admission_statistics(change):
    gate = calibrate_gate([_row(i) for i in range(80)])
    with pytest.raises(ValueError):
        replace(gate, **change)


def test_unadmitted_gate_cannot_claim_accepted_groups():
    hold = calibrate_gate([_row(1)])
    with pytest.raises(ValueError, match="unadmitted"):
        replace(hold, n_groups=1)
