"""Check native benchmark imports and an owned small structured fit, offline.

Run with the optional ``benchmark`` extra installed. This is a runtime check,
not a study, model-quality measurement, or replacement for the unit suite.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import platform
import sys
from typing import Any


def check_runtime() -> dict[str, Any]:
    """Exercise the real compiled import and public structured comparator."""
    from daf_jev.benchmark_datasets import (
        BenchmarkDataset,
        BenchmarkExample,
        DatasetManifest,
    )
    from daf_jev.benchmark_models import SklearnDecisionBackend
    from daf_jev.decision_backends import DecisionRequest
    from daf_jev.primitives import choice

    # Load the optional compiled import without requiring additional type stubs.
    importlib.import_module("scipy.sparse.linalg")
    threadpool_limits = importlib.import_module("threadpoolctl").threadpool_limits
    labels = ("low", "high", "absent")
    questions = {"class": choice("Choose the independent feature class.",
                                  {label: label for label in labels})}
    examples = tuple(BenchmarkExample(
        f"train-{index}", f"group-{index}", "train",
        json.dumps({"wine_type": "red", "features": {"feature": float(index - 60)}}),
        questions, {"class": "low" if index < 60 else "high"},
    ) for index in range(120))
    training_hash = hashlib.sha256(json.dumps(
        [example.to_dict() for example in examples], sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    manifest = DatasetManifest("owned-runtime-check", "1", "owned independent test data",
                               "CC0-1.0", training_hash, "categorical", labels)
    predictions = []
    # Bound this diagnostic's native CPU use and restore the caller's limits.
    with threadpool_limits(limits=1):
        backend = SklearnDecisionBackend(BenchmarkDataset(manifest, examples), structured=True)
        try:
            for feature, expected in ((-30.0, "low"), (30.0, "high")):
                result = backend.predict(DecisionRequest(json.dumps({
                    "wine_type": "red", "features": {"feature": feature},
                }), questions))
                prediction = result.predictions["class"]
                probabilities = prediction.probabilities
                if (prediction.value != expected or probabilities is None
                        or tuple(probabilities) != labels
                        or probabilities["absent"] != 0.0
                        or abs(sum(probabilities.values()) - 1.0) > 1e-12
                        or any(not math.isfinite(value) or not 0 <= value <= 1
                               for value in probabilities.values())):
                    raise RuntimeError("structured benchmark runtime check failed")
                predictions.append({"feature": feature, "expected": expected,
                                    "value": prediction.value, "probabilities": probabilities})
        finally:
            backend.close()
    return {
        "format": "dafjev.benchmark-runtime-check/1", "status": "passed",
        "python": platform.python_version(), "platform": sys.platform,
        "architecture": platform.machine(),
        "dependency_versions": {name: importlib.metadata.version(name) for name in (
            "numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl")},
        "training_examples": len(examples), "training_input_sha256": training_hash,
        "vocabulary": list(labels), "predictions": predictions,
        "checks": {"sparse_linalg_import": True, "structured_fit_predict": True,
                   "complete_unseen_class_vocabulary": True},
        "scope": "Owned toy data only; no provider calls or full-suite/study acceptance.",
    }


def main() -> int:
    try:
        record = check_runtime()
    except (ImportError, RuntimeError, ValueError) as exc:
        # Loader errors can contain personal installation paths. Keep those
        # out of this portable diagnostic; native stderr may be retained privately.
        print(json.dumps({"format": "dafjev.benchmark-runtime-check/1", "status": "failed",
                          "error_type": type(exc).__name__, "required_extra": "benchmark"},
                         sort_keys=True))
        return 1
    print(json.dumps(record, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
