"""Frozen cohort identity and missing-arm denominators using owned RunStores."""

import hashlib
import json
from collections import Counter

import pytest

from daf_jev._types import ChoiceQuestion
from daf_jev.benchmark_datasets import (
    BenchmarkDataset,
    BenchmarkExample,
    DatasetManifest,
    make_synthetic_dataset,
    save_dataset,
)
from daf_jev.benchmark_runner import (
    _gate_identity,
    catalog_profiles,
    plan_run,
    report_run,
)
from daf_jev.benchmark_store import RunStore


def _plan(tmp_path, datasets, *, ids=None, backends=None):
    inputs = []
    for index, dataset in enumerate(datasets):
        path = tmp_path / f"data-{index}.json"
        save_dataset(dataset, path)
        inputs.append({"id": ids[index] if ids else f"cohort-{index}", "path": path.name})
    config = {"format": "dafjev.benchmark-run/1", "seed": 1, "budget_usd": "0",
        "sampling": "all", "timing_samples": 1, "timing_repetitions": 1,
        "capability_probes": False, "datasets": inputs,
        "backends": backends or [{"id": "fixture", "kind": "uniform"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return plan_run(path, tmp_path / "runs")


def _outcomes(store, datasets):
    """Author labeled fixture events, without fitting or impersonating model I/O."""
    for cell in store.manifest["cells"]:
        example = next(e for e in datasets[cell["dataset"]].examples if e.id == cell["example_id"])
        predictions = {}
        for qid, target in example.targets.items():
            value = target if cell["dataset"] == 0 else next(label for label in datasets[cell["dataset"]].manifest.labels if label != target)
            predictions[qid] = {"type": "choice", "value": value, "confidence": .99, "probabilities": None}
        store.append({"event": "cell_started", "cell_id": cell["id"]})
        store.append({"event": "cell_finished", "cell_id": cell["id"], "status": "completed",
                      "predictions": predictions, "elapsed_s": .01})


def test_same_family_frozen_ids_bind_distinct_gates_policies_and_reductions(tmp_path):
    datasets = [make_synthetic_dataset("categorical", seed=1, n=10),
                make_synthetic_dataset("categorical", seed=2, n=20)]
    store = _plan(tmp_path, datasets, ids=["fold-zero", "fold-one"])
    _outcomes(store, datasets)
    before = {name: (store.directory / name).read_bytes() for name in ("manifest.json", "head.json", "events.jsonl")}
    report = report_run(store.directory)
    gates = sorted(report["gate_evidence"]["gates"], key=lambda row: row["dataset_index"])
    assert len(gates) == len(report["policies"]) == 2
    for index, gate in enumerate(gates):
        assert gate["dataset_id"] == ["fold-zero", "fold-one"][index]
        assert gate["dataset"] == "synthetic-categorical"
        assert gate["prepared_dataset_sha256"] == store.manifest["datasets"][index]["sha256"]
        assert gate["validation_identity"] == _gate_identity(store.manifest, "fixture", index)
        assert gate["calibration"]["validation_groups"] == [2, 4][index]
    tests = sorted((c for c in report["cohorts"] if c["phase"] == "quality" and c["split"] == "test"),
                   key=lambda row: row["dataset_index"])
    assert [c["metrics"]["accuracy"] for c in tests] == [1, 0]
    assert [c["metrics"]["planned_cells"] for c in tests] == [2, 4]
    assert {name: (store.directory / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("ids", [["same", "same"], ["valid", ""], ["valid", True]])
def test_new_plan_rejects_duplicate_or_invalid_dataset_ids_before_store(tmp_path, ids):
    with pytest.raises(ValueError, match=r"dataset id|dataset IDs"):
        _plan(tmp_path, [make_synthetic_dataset("binary", n=10), make_synthetic_dataset("binary", seed=2, n=10)], ids=ids)
    assert not (tmp_path / "runs").exists()


def test_legacy_duplicate_frozen_aliases_still_reduce_by_dataset_index(tmp_path):
    datasets = [make_synthetic_dataset("categorical", seed=1, n=10),
                make_synthetic_dataset("categorical", seed=2, n=20)]
    fresh = _plan(tmp_path, datasets)
    manifest = json.loads((fresh.directory / "manifest.json").read_text())
    for item in manifest["datasets"]:
        item["id"] = "legacy-alias"
    legacy = RunStore.create(tmp_path / "legacy", manifest)
    (legacy.directory / "inputs").mkdir()
    for item in manifest["datasets"]:
        (legacy.directory / item["file"]).write_bytes((fresh.directory / item["file"]).read_bytes())
    _outcomes(legacy, datasets)
    report = report_run(legacy.directory)
    gates = report["gate_evidence"]["gates"]
    assert len(gates) == 2
    assert {g["dataset_id"] for g in gates} == {"legacy-alias"}
    assert {g["dataset_index"] for g in gates} == {0, 1}
    assert len({g["validation_identity"] for g in gates}) == 2


@pytest.mark.parametrize("status", ["unsupported", "unattempted", "unresolved"])
def test_entirely_missing_arms_preserve_planned_axes_and_no_fake_measurements(tmp_path, status):
    dataset = make_synthetic_dataset("categorical", seed=1, n=10)
    profiles = [{"id": name, "kind": "uniform"} for name in ("first", "second")]
    store = _plan(tmp_path, [dataset], backends=profiles)
    for cell in store.manifest["cells"]:
        if status == "unsupported":
            store.append({"event": "cell_finished", "cell_id": cell["id"], "status": status, "reason": "fixture"})
        elif status == "unresolved":
            store.append({"event": "cell_started", "cell_id": cell["id"]})
    before = (store.directory / "events.jsonl").read_bytes()
    report = report_run(store.directory)
    assert report["denominators"] == {status: 10}
    assert len(report["cohorts"]) == 6
    assert {c["backend"] for c in report["cohorts"]} == {"first", "second"}
    assert sum(c["metrics"]["planned_cells"] for c in report["cohorts"]) == 10
    for cohort in report["cohorts"]:
        metrics = cohort["metrics"]
        assert metrics["planned_status_counts"] == {status: metrics["planned_decisions"]}
        assert metrics["planned_cell_status_counts"] == {status: metrics["planned_cells"]}
        assert metrics["n_attempted"] == metrics["n_success"] == 0
        assert metrics["planned_coverage"] == 0
        assert all(metrics[field] is None for field in ("accuracy", "brier", "coverage", "throughput_per_s", "throughput_wall_s"))
        assert cohort["throughput_scope"] == "unavailable"
        assert cohort["rows"] == []
    assert all(p["metrics"]["planned_cells"] == 2 for p in report["policies"])
    assert (store.directory / "events.jsonl").read_bytes() == before
    assert not any(event.get("event") == "attempt_started" for event in store.events())


def test_empty_soft_target_arms_do_not_create_hard_label_policy_gates(tmp_path):
    store = _plan(tmp_path, [make_synthetic_dataset("bayes", n=10)])
    report = report_run(store.directory)
    assert report["cohorts"] and report["gate_evidence"]["gates"] == report["policies"] == []
    assert all(c["metrics"]["accuracy"] is None for c in report["cohorts"])


@pytest.mark.parametrize("completed", [False, True])
def test_mixed_soft_validation_targets_never_fit_a_hard_gate(tmp_path, completed):
    question = ChoiceQuestion("Select class", {"in": "Known", "oos": "Unknown"})
    examples = (BenchmarkExample("validation", "validation", "validation", "fixture", {"decision": question},
                                {"decision": {"in": .5, "oos": .5}}),
                BenchmarkExample("test", "test", "test", "fixture", {"decision": question}, {"decision": "in"}))
    dataset = BenchmarkDataset(DatasetManifest("mixed-target-fixture", "1", "owned fixture", "MIT", "0" * 64,
                                               "categorical", ("in", "oos")), examples)
    store = _plan(tmp_path, [dataset])
    if completed:
        for cell in store.manifest["cells"]:
            store.append({"event": "cell_finished", "cell_id": cell["id"], "status": "completed", "predictions": {
                "decision": {"type": "choice", "value": "in", "confidence": .99, "probabilities": {"in": .5, "oos": .5}}}})
    report = report_run(store.directory)
    assert report["cohorts"] and report["gate_evidence"]["gates"] == report["policies"] == []


def test_question_and_cell_counts_and_oos_statuses_are_distinct(tmp_path):
    question = ChoiceQuestion("Select the class", {"in": "Known intent", "oos": "Out of scope"})
    examples = tuple(BenchmarkExample(f"example-{i}", f"group-{i}", split, "fixture",
        {"first": question, "second": question}, {"first": "oos", "second": "in"})
        for i, split in enumerate(("validation", "test", "test")))
    dataset = BenchmarkDataset(DatasetManifest("fixture-oos", "1", "owned fixture", "MIT", "0" * 64,
        "categorical", ("in", "oos")), examples)
    store = _plan(tmp_path, [dataset])
    first_test = next(c for c in store.manifest["cells"] if c["phase"] == "quality" and c["example_id"] == "example-1")
    store.append({"event": "cell_finished", "cell_id": first_test["id"], "status": "unsupported", "reason": "fixture"})
    cohort = next(c for c in report_run(store.directory)["cohorts"] if c["phase"] == "quality" and c["split"] == "test")
    assert cohort["metrics"]["planned_cells"] == 2
    assert cohort["metrics"]["planned_decisions"] == 4
    assert cohort["metrics"]["planned_status_counts"] == {"unsupported": 2, "unattempted": 2}
    oos = cohort["metrics"]["out_of_scope_detection"]
    assert oos["n_planned_hard"] == 4 and oos["n_planned_oos"] == 2
    assert oos["planned_oos_status_counts"] == {"unsupported": 1, "unattempted": 1}
    assert oos["n_valid_hard"] == 0 and oos["recall"] is None
    assert Counter(c["status"] for c in report_run(store.directory)["cells"]) == {"unsupported": 1, "unattempted": 3}


@pytest.mark.parametrize("raw", [
    '{"payload":{"data":[]},"payload":{"data":[]}}',
    '{"payload":{"data":[{"id":"first","id":"second"}]}}',
    '{"payload":{"data":[]},"untrusted":NaN}',
])
def test_catalog_intake_rejects_ambiguous_json_without_changing_input(tmp_path, raw):
    path = tmp_path / "catalog.json"
    path.write_text(raw)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=r"duplicate|non-finite"):
        catalog_profiles(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("boundary", ["catalog", "gate"])
def test_plan_rejects_ambiguous_frozen_catalog_or_gate_before_creating_run(tmp_path, boundary):
    _plan(tmp_path, [make_synthetic_dataset("categorical", n=10)])
    path = tmp_path / "config.json"
    config = json.loads(path.read_text())
    ambiguous = tmp_path / "ambiguous.json"
    if boundary == "catalog":
        ambiguous.write_text('{"payload":{"data":[]},"payload":{"data":[]}}')
        config["backends_from_catalog"] = ambiguous.name
    else:
        ambiguous.write_text('{"format":"dafjev.policy-gates/1","source_manifest_hash":"fixture",'
                             '"gates":[{"calibration":{"threshold":0.99,"threshold":0.01}}]}')
        config["backends"].append({"id": "cascade", "kind": "cascade", "gate_file": ambiguous.name,
                                   "weak": "fixture", "strong": "missing"})
    path.write_text(json.dumps(config))
    input_before = ambiguous.read_bytes()
    with pytest.raises(ValueError, match="duplicate"):
        plan_run(path, tmp_path / "rejected-runs")
    assert not (tmp_path / "rejected-runs").exists()
    assert ambiguous.read_bytes() == input_before
