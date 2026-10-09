"""Paired comparisons use actual retained records and analytic cluster cases."""
import copy
import json

import pytest

from daf_jev.benchmark_comparisons import compare_predictions, comparison_cohort_hash
from daf_jev.benchmark_metrics import score_predictions
from daf_jev.benchmark_store import RunStore
from daf_jev.decision_backends import content_hash


def _row(i, target="a", prediction="a", **kwargs):
    return {"example_id": str(i), "question_id": "decision", "group_id": str(i),
            "input_sha256": content_hash({"state": str(i), "ordered_questions": [["decision", ["a", "b"]]]}),
            "target": target, "prediction": prediction, "status": "completed", "applicable": True,
            "phase": "quality", "repeat": 0, "split": "test", **kwargs}


def _binding(rows, backend="left", **kwargs):
    return {"backend_id": backend, "dataset_id": "fixture", "dataset_index": 0,
            "prepared_dataset_sha256": content_hash("prepared ordered input"),
            "inference_source_sha256": content_hash(backend), "split": "test", "phase": "quality",
            "cohort_sha256": comparison_cohort_hash(rows), "hard_prediction_rule": "reported_label", **kwargs}


def _compare(left, right, **kwargs):
    return compare_predictions(left, right, left_binding=_binding(left), right_binding=_binding(right, "right"),
                               labels=["a", "b"], label_kind="categorical", bootstrap_samples=80, **kwargs)


def test_real_journal_records_pair_identical_group_draws_and_keep_partial_denominators(tmp_path):
    frozen = [_row(i) for i in range(4)]
    stores = [RunStore.create(tmp_path.resolve(), {"fixture": True, "planned": frozen}) for _ in range(2)]
    for arm, store in enumerate(stores):
        for i in range(4):
            if arm == 1 and i == 3:
                store.append({"event": "cell_started", "cell_id": str(i)})
                continue
            store.append({"event": "cell_started", "cell_id": str(i)})
            store.append({"event": "cell_finished", "cell_id": str(i), "row": _row(i, prediction="b" if arm == 0 and i == 0 else "a")})
    rows = []
    for store in stores:
        retained = RunStore(store.directory, read_only=True)
        outcomes = {event["cell_id"]: event["row"] for event in retained.events() if event["event"] == "cell_finished"}
        rows.append([outcomes.get(str(i), _row(i, prediction=None, status="unresolved")) for i in range(4)])
    result = _compare(*rows)
    assert result["planned_decisions"] == 4
    assert result["planned_status_counts"]["right"] == {"completed": 3, "unresolved": 1}
    assert result["joint_valid_coverage"] == .75
    assert result["metrics"]["accuracy"]["difference"] == pytest.approx(1 / 3)
    assert result["metrics"]["accuracy"]["paired_decisions"] == 3
    assert result == _compare(rows[0][::-1], rows[1][::-1])
    json.dumps(result, allow_nan=False)


def test_matched_permutations_remain_one_independent_group_and_identical_arms_zero():
    rows = [_row(i, group_id="matched", probabilities={"a": .8, "b": .2}) for i in range(3)]
    result = _compare(rows, rows)
    for name in ("accuracy", "brier"):
        metric = result["metrics"][name]
        assert metric["difference"] == 0 and metric["paired_decisions"] == 3
        assert metric["status"] == "insufficient_groups"
        assert metric["interval"]["low"] is None and metric["independent_groups"] == 1
    assert result["probability_meaning_summary"]["left"]["unknown_distributions"] == 3


def test_paired_brier_matches_report_units_and_missing_beliefs_have_no_fake_loss():
    left = [_row(0, probabilities={"a": .8, "b": .2}), _row(1, target="b", probabilities={"a": .6, "b": .4})]
    right = [_row(0, probabilities={"a": .9, "b": .1}), _row(1, target="b", prediction="b", probabilities={"a": .1, "b": .9})]
    metric = _compare(left, right)["metrics"]["brier"]
    assert metric["left"] == score_predictions(left, labels=["a", "b"])["brier"]
    assert metric["right"] == score_predictions(right, labels=["a", "b"])["brier"]
    assert metric["difference"] == pytest.approx(-.38)
    right[1]["probabilities"] = None
    assert _compare(left, right)["metrics"]["brier"]["paired_decisions"] == 1
    for row in right:
        row["probabilities"] = None
    assert _compare(left, right)["metrics"]["brier"]["difference"] is None


def test_macro_f1_recomputes_confusion_on_every_shared_draw_with_absent_classes():
    left = [_row(0), _row(1, target="b", prediction="a")]
    right = [_row(0), _row(1, target="b", prediction="b")]
    result = _compare(left, right)
    metric = result["metrics"]["macro_f1"]
    assert metric["left"] == pytest.approx(1 / 3)
    assert metric["right"] == 1
    assert metric["difference"] == pytest.approx(2 / 3)
    assert metric["interval"]["low"] == 0
    assert metric["interval"]["high"] == pytest.approx(2 / 3)
    assert "recomputed" in metric["interval"]["method"]
    # A retained absent class remains in the macro denominator on every draw.
    extended = compare_predictions(left, right, left_binding=_binding(left),
        right_binding=_binding(right, "right"), labels=["a", "b", "absent"],
        label_kind="categorical", bootstrap_samples=80)
    assert extended["metrics"]["macro_f1"]["right"] == pytest.approx(2 / 3)


def test_noncompleted_partial_values_are_ignored_without_losing_outcomes():
    rows = [_row(0, status="failed", prediction={"invalid": "partial"}, probabilities={"a": 100})]
    result = _compare(rows, rows)
    assert result["planned_status_counts"]["left"] == {"failed": 1}
    assert result["metrics"]["accuracy"]["difference"] is None


def test_binary_fractional_targets_require_an_explicit_soft_distribution():
    rows = [_row(0, target=.2, prediction=.3)]
    with pytest.raises(ValueError, match="soft targets require"):
        compare_predictions(rows, rows, left_binding=_binding(rows), right_binding=_binding(rows, "right"),
                            labels=["false", "true"], label_kind="binary")
    rows = [_row(0, target={"false": .8, "true": .2}, prediction=.3,
                 probabilities={"false": .7, "true": .3})]
    result = compare_predictions(rows, rows, left_binding=_binding(rows), right_binding=_binding(rows, "right"),
                                labels=["false", "true"], label_kind="binary")
    assert result["metrics"]["accuracy"]["difference"] is None
    assert result["metrics"]["brier"]["left"] == pytest.approx(.02)


def test_ordinal_raw_mae_comparable_but_argmax_and_scalar_accuracy_are_distinct():
    left = [_row(i, target=1, prediction=1.5, probabilities={"0": .1, "1": .6, "2": .3}) for i in range(2)]
    right = [_row(i, target=1, prediction=1.) for i in range(2)]
    result = compare_predictions(left, right,
        left_binding=_binding(left, hard_prediction_rule="probability_argmax"),
        right_binding=_binding(right, "right", hard_prediction_rule="scalar_exact"),
        labels=["0", "1", "2"], label_kind="ordinal", bootstrap_samples=10)
    assert result["metrics"]["accuracy"]["status"] == "incompatible_prediction_rules"
    assert result["metrics"]["ordinal_mae"]["difference"] == -.5
    assert result["metrics"]["ordinal_mae"]["unit"] == "declared_bin_coordinates"
    assert result["metrics"]["brier"]["status"] == "no_joint_measurements"


def test_soft_targets_have_brier_but_no_invented_hard_accuracy():
    left = [_row(i, target={"a": .25, "b": .75}, prediction="b", probabilities={"a": .25, "b": .75}) for i in range(2)]
    right = [_row(i, target={"a": .25, "b": .75}, prediction="b", probabilities={"a": .5, "b": .5}) for i in range(2)]
    result = _compare(left, right)
    assert result["metrics"]["accuracy"]["difference"] is None
    assert result["metrics"]["brier"]["difference"] == .125


@pytest.mark.parametrize("labels", [["2", "1", "0"], ["0", "1", "2"]])
def test_ordinal_probability_ties_preserve_consumed_row_order_and_report_rule(labels):
    rows = [_row(i, target=2, prediction=1.5, probabilities={"2": .5, "1": .5, "0": 0.},
        input_sha256=content_hash({"state": str(i), "ordered_questions": [["decision", labels]]})) for i in range(2)]
    binding = _binding(rows, hard_prediction_rule="probability_argmax")
    result = compare_predictions(rows, rows, left_binding=binding, right_binding=binding,
                                labels=labels, label_kind="ordinal", bootstrap_samples=10)
    report = score_predictions(rows, labels=labels, label_kind="ordinal")
    assert result["metrics"]["accuracy"]["left"] == report["accuracy"] == 1
    assert result["metrics"]["macro_f1"]["left"] == report["macro_f1"]
    assert list(rows[0]["probabilities"]) == ["2", "1", "0"]


def test_full_inapplicable_and_empty_cohorts_keep_unavailable_measurements():
    left = [_row(i, prediction=None, applicable=False, status="unsupported") for i in range(2)]
    right = [_row(i, prediction=None, status="unattempted") for i in range(2)]
    result = _compare(left, right)
    assert result["planned_decisions"] == 2 and result["joint_applicable_decisions"] == 0
    assert result["planned_status_counts"]["left"] == {"unsupported": 2}
    assert result["joint_valid_coverage"] is None
    assert _compare([], [])["metrics"]["accuracy"]["difference"] is None


@pytest.mark.parametrize("field,value", [("target", "b"), ("group_id", "other"), ("input_sha256", "1" * 64)])
def test_coincident_ids_do_not_authorize_different_targets_groups_or_inputs(field, value):
    left = [_row(0), _row(1)]
    right = copy.deepcopy(left)
    right[0][field] = value
    with pytest.raises(ValueError, match="identity mismatch"):
        _compare(left, right)


@pytest.mark.parametrize("field,value", [("dataset_id", "another"), ("dataset_index", 1), ("prepared_dataset_sha256", "1" * 64), ("split", "validation")])
def test_exact_cohort_binding_is_required(field, value):
    rows = [_row(0)]
    with pytest.raises(ValueError, match="identity mismatch"):
        compare_predictions(rows, rows, left_binding=_binding(rows), right_binding=_binding(rows, "right", **{field: value}), labels=["a", "b"], label_kind="categorical")


@pytest.mark.parametrize("updates", [{"status": "missing"}, {"applicable": 1}, {"phase": "warm_repeat"}, {"repeat": True}, {"repeat": 1}, {"error": "timeout"}, {"prediction": None}, {"probability_semantics": ""}, {"probabilities": {"a": .3, "b": .2}}, {"prediction": "hidden"}])
def test_malformed_records_fail_without_relabeling_or_normalizing(updates):
    rows = [_row(0, **updates)]
    with pytest.raises(ValueError):
        _compare(rows, rows)


def test_full_inventory_missing_or_duplicate_rows_and_invalid_vocab_reject():
    rows = [_row(0), _row(1)]
    with pytest.raises(ValueError, match="full frozen cohort"):
        compare_predictions(rows[:1], rows, left_binding=_binding(rows), right_binding=_binding(rows, "right"), labels=["a", "b"], label_kind="categorical")
    with pytest.raises(ValueError, match="duplicate"):
        comparison_cohort_hash([rows[0], rows[0]])
    with pytest.raises(ValueError, match="unique vocabulary"):
        compare_predictions(rows, rows, left_binding=_binding(rows), right_binding=_binding(rows, "right"), labels=["a", "a"], label_kind="categorical")


def test_completed_abstentions_and_native_rounding_remain_explicit():
    left = [_row(0, prediction=None, abstained=True), _row(1, probabilities={"a": .49, "b": .5}, probability_rounding_digits=2)]
    right = [_row(0), _row(1, probabilities={"a": .5, "b": .5})]
    result = _compare(left, right)
    assert result["joint_valid_decisions"] == 1
    assert result["metrics"]["brier"]["left"] == pytest.approx(.5101)


@pytest.mark.parametrize("kwargs", [{"bootstrap_samples": True}, {"bootstrap_samples": 0}, {"seed": True}])
def test_invalid_bootstrap_configuration_rejects(kwargs):
    rows = [_row(0)]
    with pytest.raises(ValueError):
        compare_predictions(rows, rows, left_binding=_binding(rows), right_binding=_binding(rows, "right"), labels=["a", "b"], label_kind="categorical", **kwargs)
