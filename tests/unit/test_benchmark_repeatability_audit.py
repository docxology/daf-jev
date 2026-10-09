"""Analytic stability and empirical binning-loss evidence, independent of accuracy."""

import json
from dataclasses import replace

import pytest

from daf_jev.benchmark_datasets import BenchmarkDataset, make_synthetic_dataset
from daf_jev.benchmark_metrics import audit_dataset, repeatability


def _row(repeat, *, example_id="example", prediction="a", probabilities=None, status="completed", **kw):
    return {"example_id": example_id, "question_id": "decision", "repeat": repeat,
            "phase": "quality" if repeat == 0 else "warm_repeat", "status": status,
            "prediction": prediction, "probabilities": probabilities, "error": None,
            "probability_source": "native" if probabilities is not None else None, **kw}


def test_primary_plus_five_repeats_have_analytic_agreement_and_separate_modal_share():
    rows = [_row(i, prediction="a" if i < 4 else "b", probabilities={"a": .8, "b": .2} if i < 4 else {"a": .2, "b": .8})
            for i in range(6)]
    result = repeatability(rows, labels=["a", "b"])
    assert result["n_repeated_planned_observations"] == result["n_repeated_completed_observations"] == 6
    assert result["n_planned_warm_repeats"] == result["n_completed_warm_repeats"] == 5
    assert result["mean_pairwise_label_agreement"] == pytest.approx(7 / 15)
    assert result["mean_modal_share"] == pytest.approx(4 / 6)
    assert result["mean_distribution_pairwise_half_l1"] == pytest.approx(8 * .6 / 15)
    assert "accuracy" not in result
    assert result == repeatability([{**row, "target": "wrong"} for row in rows], labels=["a", "b"])
    json.dumps(result, allow_nan=False)


def test_failed_missing_invalid_and_primary_only_measurements_remain_unavailable():
    rows = [_row(0, probabilities={"a": .8, "b": .2}), _row(1),
            _row(2, prediction=None, status="failed", error="timeout"),
            _row(3, prediction=None, status="unattempted"), _row(4, probabilities={"a": .4, "b": .4}),
            _row(0, example_id="primary-only")]
    result = repeatability(rows, labels=["a", "b"])
    assert result["n_primary_only_groups"] == 1
    assert result["n_repeated_planned_observations"] == 5 and result["n_repeated_completed_observations"] == 3
    assert result["repeated_status_counts"] == {"completed": 3, "failed": 1, "unattempted": 1}
    group = result["groups"][0]
    assert group["missing_distributions"] == group["invalid_distributions"] == group["distribution_observations"] == 1
    assert group["distribution_mean_pairwise_half_l1"] is None
    primary_only = repeatability([_row(0)], labels=["a", "b"])
    assert primary_only["n_repeated_groups"] == 0 and primary_only["mean_modal_share"] is None
    failed = repeatability([_row(0, status="failed", prediction=None), _row(1, status="failed", prediction=None)])
    assert failed["mean_pairwise_label_agreement"] is None
    assert failed["n_repeated_completed_observations"] == 0


def test_native_rounded_variation_uses_original_distribution_and_fractional_ordinal_without_beliefs_has_no_label():
    rows = [_row(0, prediction="a", probabilities={"a": .33, "b": .33, "c": .33}, probability_rounding_digits=2),
            _row(1, prediction="a", probabilities={"a": .34, "b": .33, "c": .33}, probability_rounding_digits=2)]
    assert repeatability(rows, labels=["a", "b", "c"])["mean_distribution_pairwise_half_l1"] == pytest.approx(.005)
    ordinal = repeatability([_row(0, prediction=1.4), _row(1, prediction=1.4)], labels=["0", "1", "2"], label_kind="ordinal")
    assert ordinal["mean_pairwise_label_agreement"] is None
    assert ordinal["mean_distribution_pairwise_half_l1"] is None
    binary = repeatability([_row(0, prediction=.5), _row(1, prediction=.8)], labels=["false", "true"], label_kind="binary")
    assert binary["mean_pairwise_label_agreement"] == 1


def test_repeatability_rejects_missing_identity_or_primary_and_never_includes_probes():
    for rows in ([{**_row(0), "example_id": None}], [_row(1)], [{**_row(0), "phase": "capability_probe"}],
                 [{**_row(0), "status": "unknown"}], [_row(0), _row(0)]):
        with pytest.raises(ValueError):
            repeatability(rows)


def _wine():
    original = make_synthetic_dataset("ordinal", n=4)
    manifest = replace(original.manifest, name="wine", labels=("0", "1", "2", "3", "4"), metadata={
        "grade_bins": [[0, 2], [3, 4], [5, 6], [7, 8], [9, 10]], "source_revision": "fixture", "split_seed": 0})
    examples = tuple(replace(example, targets={"decision": 2}, metadata={"original_grade": 5 + i % 2,
                         "wine_type": "red" if i < 2 else "white"}) for i, example in enumerate(original.examples))
    return BenchmarkDataset(manifest, examples)


def test_wine_grade_binning_information_loss_is_conditional_entropy_not_prediction_error():
    dataset = _wine()
    result = audit_dataset(dataset, selected_example_ids=[dataset.examples[0].id, dataset.examples[3].id])
    full = result["full"]["wine_binning"]
    assert full["n"] == 4 and full["original_grade_histogram"]["5"] == 2
    assert full["bins"]["2"]["original_grade_histogram"] == {"5": 2, "6": 2}
    assert full["conditional_grade_entropy_bits"] == full["original_grade_entropy_bits"] == 1
    assert full["bin_entropy_bits"] == 0
    assert full["bins"]["0"]["grade_entropy_bits"] is None
    assert full["by_type"]["red"]["conditional_grade_entropy_bits"] == 1
    selected = result["selected"]["wine_binning"]
    assert selected["n"] == 2 and selected["conditional_grade_entropy_bits"] == 1
    assert selected["by_type"]["red"]["conditional_grade_entropy_bits"] == 0
    assert result["source_revision"] == "fixture" and result["license"] == "MIT"
    assert "prediction error" in full["information_loss_semantics"]
    json.dumps(result, allow_nan=False)
    with pytest.raises(ValueError, match="unknown"):
        audit_dataset(dataset, selected_example_ids=["missing"])


def test_audit_counts_duplicates_cross_split_and_conflicting_targets_without_dropping_rows():
    dataset = make_synthetic_dataset("categorical", n=2)
    a, b = dataset.examples
    examples = (a, replace(b, group_id=a.group_id))
    manifest = replace(dataset.manifest, name="clinc150", metadata={"cohort": "official_canonical",
        "cross_split_leakage_declared": True, "cross_split_duplicate_group_ids": [a.group_id],
        "source_counts": {"train": 1, "test": 1}, "source_revision": "official-fixture"})
    audit = audit_dataset(BenchmarkDataset(manifest, examples))
    assert audit["full"]["examples"] == 2
    assert audit["full"]["duplicate_groups"] == audit["full"]["duplicate_excess_rows"] == 1
    assert audit["full"]["duplicate_rows"] == 2
    assert audit["full"]["cross_split_groups"] == audit["full"]["conflicting_target_groups"] == 1
    assert audit["source_counts"] == {"train": 1, "test": 1}
