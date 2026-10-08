"""Analytic metric, missing-measurement and clustered-uncertainty checks."""

import json
from decimal import ROUND_FLOOR, Inexact, localcontext

import pytest

from daf_jev.benchmark_metrics import (
    grouped_bootstrap,
    nearest_rank_percentile,
    score_predictions,
    validate_probabilities,
)


def _row(i, target, prediction, probabilities=None, **kw):
    return {"example_id": str(i), "group_id": str(i), "target": target,
            "prediction": prediction, "probabilities": probabilities,
            "confidence": .8, "latency_s": .2, "error": None, "cost_usd": .01, **kw}


def test_classification_confusion_proper_scores_and_cost():
    rows = [_row(1, "a", "a", {"a": .8, "b": .2}), _row(2, "b", "a", {"a": .6, "b": .4})]
    result = score_predictions(rows, labels=["a", "b"], wall_s=.25)
    assert result["accuracy"] == .5
    assert result["macro_f1"] == pytest.approx(1 / 3)
    assert result["brier"] == pytest.approx(.4)
    assert result["confusion"] == {"a": {"a": 1, "b": 0}, "b": {"a": 1, "b": 0}}
    assert result["total_cost_usd"] == "0.02"
    assert result["cost_per_correct_decision_usd"] == "0.02"
    assert result["throughput_per_s"] == 8
    assert result["uncertainty"]["accuracy"]["groups"] == 2
    decimal_receipt = score_predictions([_row(1, "a", "a", cost_usd="0.0125")])
    assert decimal_receipt["total_cost_usd"] == "0.0125"
    json.dumps(result, allow_nan=False)


def test_failure_abstention_missing_cost_and_infinite_loss_are_distinct():
    rows = [_row(1, "a", "b", {"a": 0., "b": 1.}, cost_usd=None),
            _row(2, "a", None, error="timeout"), _row(3, "a", None, abstained=True)]
    result = score_predictions(rows, labels=["a", "b"])
    assert result["log_loss"] is None
    assert result["log_loss_status"] == "infinite"
    assert result["n_infinite_log_loss"] == 1
    assert result["n_errors"] == 1 and result["n_abstained"] == 1
    assert result["coverage"] == pytest.approx(1 / 3)
    assert result["known_cost_usd"] == "0.02" and result["total_cost_usd"] is None
    json.dumps(result, allow_nan=False)


def test_currency_sums_and_ratios_retain_decimal_evidence_and_unknowns():
    rows = [_row(1, "a", "a", cost_usd="0.100000000000000001"),
            _row(2, "a", "b", cost_usd="0.200000000000000002")]
    result = score_predictions(rows)
    assert result["known_cost_usd"] == result["total_cost_usd"] == "0.300000000000000003"
    assert result["cost_per_decision_usd"] == "0.1500000000000000015"
    assert result["cost_per_correct_decision_usd"] == "0.300000000000000003"
    assert "local compute expense is separate" in result["cost_scope"]
    assert json.loads(json.dumps(result, allow_nan=False))["total_cost_usd"] == "0.300000000000000003"
    partial = score_predictions([*rows, _row(3, "a", "a", cost_usd=None)])
    assert partial["known_cost_usd"] == "0.300000000000000003"
    assert partial["total_cost_usd"] is partial["cost_per_decision_usd"] is None


def test_currency_ratios_ignore_hostile_callers_decimal_context():
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_FLOOR
        context.traps[Inexact] = True
        context.Emax = 5
        small = score_predictions([_row(1, "a", "a", cost_usd="0.01"),
                                   _row(2, "a", "a", cost_usd="0.01"),
                                   _row(3, "a", "a", cost_usd="0.02")])
        large = score_predictions([_row(1, "a", "a", cost_usd="100000000")])
    assert small["total_cost_usd"] == "0.04"
    assert small["cost_per_decision_usd"] == "0.013333333333333333333333333333333333333333333333333"
    assert large["total_cost_usd"] == "100000000"


def test_derived_request_totals_do_not_reapply_individual_charge_ceiling():
    result = score_predictions([_row(1, "a", "a", cost_usd="18000000000.000000000000000003")])
    assert result["total_cost_usd"] == "18000000000.000000000000000003"
    assert result["cost_per_correct_decision_usd"] == result["total_cost_usd"]
    with pytest.raises(ValueError, match="cost_usd"):
        score_predictions([_row(1, "a", "a", cost_usd="1E30")])


def test_soft_targets_have_no_invented_hard_accuracy():
    result = score_predictions([_row(1, {"a": .25, "b": .75}, "b", {"a": .25, "b": .75})])
    assert result["accuracy"] is None and result["macro_f1"] is None
    assert result["brier"] == 0
    assert result["log_loss"] > 0  # distribution entropy, not fabricated zero


def test_ordinal_fractional_prediction_and_binary_scalar():
    ordinal = score_predictions([_row(1, 2, 2.5), _row(2, 1, 0)], labels=["0", "1", "2", "3"], label_kind="ordinal")
    assert ordinal["ordinal_mae"] == .75
    assert ordinal["ordinal_rmse"] == pytest.approx((.625) ** .5)
    native = score_predictions([_row(1, 2, 2.3, {"0": 0., "1": 0., "2": .7, "3": .3})],
                               labels=["0", "1", "2", "3"], label_kind="ordinal")
    assert native["accuracy"] == 1 and native["ordinal_mae"] == pytest.approx(.3)
    binary = score_predictions([_row(1, "true", .8, {"false": .2, "true": .8})], label_kind="binary")
    assert binary["accuracy"] == 1
    assert binary["binary_brier"] == pytest.approx(.04)


@pytest.mark.parametrize("probs", [{"a": -.1, "b": 1.1}, {"a": float("nan"), "b": 1.}, {"a": .2, "b": .2}, {"a": True, "b": 0.}])
def test_invalid_probability_rows_fail_without_normalization(probs):
    with pytest.raises(ValueError):
        validate_probabilities(probs)


def test_declared_native_rounding_keeps_original_numbers():
    probs = {"a": .33, "b": .33, "c": .33}
    with pytest.raises(ValueError):
        validate_probabilities(probs)
    assert validate_probabilities(probs, rounding_digits=2) == probs
    result = score_predictions([_row(1, "a", "a", probs, probability_rounding_digits=2)], labels=list(probs))
    assert result["probability_row_sum_deviations"] == pytest.approx([-.01])
    with pytest.raises(ValueError):
        validate_probabilities({"a": .3, "b": .3, "c": .3}, rounding_digits=2)
    with pytest.raises(ValueError):
        validate_probabilities({"a": .3333, "b": .3333, "c": .3234}, rounding_digits=2)
    assert validate_probabilities({"a": .5, "b": .5}, rounding_digits=15) == {"a": .5, "b": .5}


def test_nearest_rank_and_grouped_repeat_uncertainty():
    assert nearest_rank_percentile([1., 2.], 95) == 2
    assert nearest_rank_percentile([1., 2.], 0) == 1
    interval = grouped_bootstrap([("group-a", 1.)] * 1000)
    assert interval["status"] == "insufficient_groups"
    data = [("a", 0.), ("a", 1.), ("b", 1.), ("b", 1.)]
    assert grouped_bootstrap(data, seed=2) == grouped_bootstrap(data, seed=2)
    assert grouped_bootstrap(data)["groups"] == 2
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 95)


def test_complete_vocabulary_is_required_and_empty_metrics_are_unavailable():
    with pytest.raises(ValueError, match="vocabulary"):
        score_predictions([_row(1, "a", "a", {"a": 1.})], labels=["a", "b"])
    result = score_predictions([])
    assert result["accuracy"] is None and result["throughput_per_s"] is None
    assert result["coverage"] is None and result["n_attempted"] == 0


@pytest.mark.parametrize("field,value", [("latency_s", -1), ("confidence", 1.1), ("confidence", float("nan")),
                                         ("cost_usd", "NaN"), ("cost_usd", "-0.1"), ("cost_usd", "not money")])
def test_invalid_measurements_fail_explicitly(field, value):
    with pytest.raises(ValueError):
        score_predictions([_row(1, "a", "a", **{field: value})])


def test_binary_scalar_and_probability_provenance_validation():
    with pytest.raises(ValueError):
        score_predictions([_row(1, "true", float("nan"))], label_kind="binary")
    with pytest.raises(ValueError):
        validate_probabilities({"a": 1.}, rounding_digits=True)
    with pytest.raises(ValueError):
        nearest_rank_percentile([1.], 101)
    with pytest.raises(ValueError):
        grouped_bootstrap([("a", 1.)], samples=0)


def test_out_of_scope_detection_confusion_and_failure_denominators_preserve_official_label():
    rows = [_row(1, "oos", "oos"), _row(2, "account", "oos"),
            _row(3, "oos", "account"), _row(4, "account", "account"),
            _row(5, "oos", None, error="timeout")]
    planned = [*rows, _row(6, "oos", None, status="unattempted")]
    result = score_predictions(rows, labels=["account", "oos"], planned_rows=planned)["out_of_scope_detection"]
    assert {key: result[key] for key in ("tp", "fp", "fn", "tn")} == dict.fromkeys(("tp", "fp", "fn", "tn"), 1)
    assert result["precision"] == result["recall"] == result["specificity"] == result["f1"] == .5
    assert result["positive_labels"] == ["oos"]
    assert result["n_planned_hard"] == 6 and result["n_valid_hard"] == 4
    assert result["n_planned_oos"] == 4 and result["n_valid_oos"] == 2 and result["n_failed_oos"] == 1
    assert result["planned_oos_status_counts"] == {"completed": 2, "failed": 1, "unattempted": 1}


def test_oos_detection_absent_denominators_and_exact_matching_names():
    result = score_predictions([_row(1, "account", "account")], labels=["account", "out_of_scope"])["out_of_scope_detection"]
    assert result["precision"] is result["recall"] is result["f1"] is None
    assert result["specificity"] == 1 and result["n_planned_oos"] == 0
    assert score_predictions([_row(1, "account", "account")], labels=["account", "OOS"])["out_of_scope_detection"] is None
    soft = score_predictions([_row(1, {"oos": .5, "account": .5}, "oos")], labels=["oos", "account"])["out_of_scope_detection"]
    assert soft["n_valid_hard"] == 0 and soft["n_planned_soft"] == 1 and soft["recall"] is None
