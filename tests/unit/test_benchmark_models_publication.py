"""Actual fitted baselines and offline publication custody, no provider calls."""
import hashlib
import json
from dataclasses import replace

import pytest

from daf_jev.benchmark_datasets import BenchmarkDataset, make_synthetic_dataset
from daf_jev.benchmark_models import SklearnDecisionBackend, fit_prior
from daf_jev.benchmark_publication import markdown_report, write_publication
from daf_jev.decision_backends import DecisionRequest, content_hash
from daf_jev.evidence import selected_benchmark


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal"])
def test_real_training_prior_and_text_classifier(kind):
    pytest.importorskip("sklearn")
    dataset = make_synthetic_dataset(kind, n=120, seed=20261007)
    example = next(e for e in dataset.examples if e.split == "test")
    for backend in (fit_prior(dataset), SklearnDecisionBackend(dataset)):
        result = backend.predict(DecisionRequest(example.state, example.questions))
        assert set(result.predictions) == set(example.questions)
        for prediction in result.predictions.values():
            assert sum(prediction.probabilities.values()) == pytest.approx(1)
            assert prediction.probability_source in ("classifier", "training_prior")
        backend.close()


def test_structured_features_flatten_and_vocabulary_is_complete():
    pytest.importorskip("sklearn")
    dataset = make_synthetic_dataset("ordinal", n=120, seed=17)
    examples = tuple(replace(e, state=json.dumps({"wine_type": "red", "features": {"feature": float(i % 20)}})) for i, e in enumerate(dataset.examples))
    transformed = [example.to_dict() for example in examples]
    metadata = {**dataset.manifest.to_dict()["metadata"],
                "examples_sha256": content_hash(transformed),
                "order_sensitive_examples_sha256": hashlib.sha256(json.dumps(
                    transformed, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()}
    dataset = BenchmarkDataset(replace(dataset.manifest, metadata=metadata), examples)
    backend = SklearnDecisionBackend(dataset, structured=True)
    example = examples[0]
    result = backend.predict(DecisionRequest(example.state, example.questions))
    assert len(next(iter(result.predictions.values())).probabilities) == 4
    assert backend.training["split"] == "train"
    with pytest.raises(ValueError, match="question absent"):
        backend.predict(DecisionRequest("{}", {"other": next(iter(example.questions.values()))}))
    for state in ("[]", '{"features": {"x": "bad"}, "wine_type": "red"}'):
        with pytest.raises(ValueError):
            backend._features(state)


def test_soft_training_is_explicitly_unsupported():
    dataset = make_synthetic_dataset("bayes", n=30)
    with pytest.raises(ValueError, match="discrete"):
        fit_prior(dataset)
    pytest.importorskip("sklearn")
    with pytest.raises(ValueError, match="discrete"):
        SklearnDecisionBackend(dataset)


def _report():
    return {"format": "dafjev.benchmark-report/1", "manifest_hash": "a" * 64, "journal_hash": "b" * 64,
        "status": "partial", "planned_cells": 2, "denominators": {"completed": 1, "unattempted": 1},
        "accounting": {"reported_cost_usd": "0", "reserved_usd": "0"}, "cohorts": [
            {"backend": "prior", "dataset": "synthetic", "split": "test", "phase": "quality",
             "metrics": {"n": 1, "accuracy": .5, "macro_f1": None, "n_missing_cost": 1,
                         "uncertainty": {"accuracy": {"low": .2, "high": .8}}}}],
        "policies": [{"dataset": "synthetic", "weak": "prior", "strong": None, "policy": "gate", "gate": {"status": "insufficient_evidence"}, "metrics": {}}],
        "limits": ["Partial evidence"], "cells": [{"id": "x", "status": "unattempted", "reason": "missing key"}]}


def test_standalone_reports_are_exclusive_and_deterministic(tmp_path):
    report = _report()
    text = markdown_report(report)
    assert "a" * 64 in text and "unavailable" in text and "missing key" in text
    assert "{{" not in text and "??" not in text
    path = tmp_path / "report.md"
    write_publication(report, path)
    assert path.read_text() == text
    with pytest.raises(FileExistsError):
        write_publication(report, path)
    with pytest.raises(ValueError):
        write_publication(report, tmp_path / "report.txt")
    with pytest.raises(ValueError):
        markdown_report({})
    pytest.importorskip("matplotlib")
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    write_publication(report, first)
    write_publication(report, second)
    assert first.read_bytes().startswith(b"%PDF-")
    assert first.read_bytes() == second.read_bytes()


def test_explicit_shared_evidence_ignores_newer_and_rejects_mutation(tmp_path):
    root = tmp_path
    (root / "manuscript").mkdir()
    selection = root / "manuscript/evidence.json"
    with pytest.raises(FileNotFoundError):
        selected_benchmark(root, "batching")
    selection.write_text('{}')
    with pytest.raises(ValueError, match="format"):
        selected_benchmark(root, "batching")
    path = root / "old.json"
    path.write_text('{"model": "historical"}')
    spec = {"format": "dafjev.publication-evidence/1", "historical_benchmarks": {"batching": {
        "path": "old.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}
    selection.write_text(json.dumps(spec))
    (root / "new.json").write_text('{"model": "newer"}')
    assert selected_benchmark(root, "batching") == path
    with pytest.raises(FileNotFoundError):
        selected_benchmark(root, "patterns")
    path.write_text('{}')
    with pytest.raises(ValueError, match="changed"):
        selected_benchmark(root, "batching")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        selected_benchmark(root, "batching")
    path.symlink_to(root / "new.json")
    with pytest.raises(ValueError, match="nonsymlink"):
        selected_benchmark(root, "batching")
