"""Paired, fixed-prediction comparisons over a complete frozen cohort.

This module does no I/O. Callers supply verified input/source bindings and all
planned primary decisions, including decisions without an outcome. Group draws
are shared between arms; repeats never become independent sampling units.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from daf_jev.benchmark_metrics import (
    grouped_bootstrap,
    nearest_rank_percentile,
    validate_probabilities,
)
from daf_jev.decision_backends import canonical_json, content_hash

_STATUSES = frozenset({"completed", "failed", "unsupported", "unattempted", "unresolved"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMMON = ("dataset_id", "dataset_index", "prepared_dataset_sha256", "split", "phase", "cohort_sha256")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA256")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    if "target" not in row:
        raise ValueError("planned comparison row requires target")
    return {**{name: _text(row.get(name), name) for name in ("example_id", "question_id", "group_id")},
            "input_sha256": _hash(row.get("input_sha256"), "input_sha256"), "target": row["target"]}


def comparison_cohort_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash the full input/target/group inventory, independently of arrival order.

    ``input_sha256`` must fingerprint the complete frozen state and ordered
    questions. This helper checks fingerprint shape, not an external artifact's
    custody. Duplicate example/question identities always reject.
    """
    identities = [_identity(row) for row in rows]
    identities.sort(key=lambda row: (row["example_id"], row["question_id"]))
    keys = [(row["example_id"], row["question_id"]) for row in identities]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate comparison decision identity")
    return content_hash(identities)


def _binding(value: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(canonical_json(dict(value)))
    for name in ("backend_id", "dataset_id", "split"):
        _text(result.get(name), name)
    for name in ("prepared_dataset_sha256", "inference_source_sha256", "cohort_sha256"):
        _hash(result.get(name), name)
    index = result.get("dataset_index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError("dataset_index must be a nonnegative integer")
    if result.get("phase") != "quality":
        raise ValueError("paired comparisons require primary quality phase")
    if result.get("hard_prediction_rule") not in {"reported_label", "scalar_exact", "probability_argmax"}:
        raise ValueError("declare hard_prediction_rule")
    return result


def _rows(values: Sequence[Mapping[str, Any]], binding: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    # Outcome distribution order is part of existing argmax tie behaviour.
    # Canonical hashes still bind semantic identity, but a working copy must
    # not sort consumed probability keys and silently change the prediction.
    rows = [json.loads(json.dumps(dict(row), ensure_ascii=False, allow_nan=False)) for row in values]
    if comparison_cohort_hash(rows) != binding["cohort_sha256"]:
        raise ValueError("comparison rows do not match the full frozen cohort")
    result = {}
    for row in rows:
        if row.get("status") not in _STATUSES:
            raise ValueError("comparison rows require explicit planned status")
        if not isinstance(row.get("applicable"), bool):
            raise ValueError("comparison applicability must be frozen boolean")
        if not row["applicable"] and row["status"] not in {"unsupported", "unattempted"}:
            raise ValueError("inapplicable comparison row has an attempted outcome")
        if row.get("phase") != "quality" or type(row.get("repeat")) is not int or row["repeat"] != 0:
            raise ValueError("comparison rows require primary quality repeat zero")
        if row.get("split") != binding["split"]:
            raise ValueError("comparison row split does not match binding")
        if row.get("abstained") is not None and not isinstance(row["abstained"], bool):
            raise ValueError("abstained must be boolean")
        if row["status"] == "completed":
            if row.get("error") is not None:
                raise ValueError("completed comparison row has an error")
            if row.get("prediction") is None and not row.get("abstained"):
                raise ValueError("completed comparison row lacks prediction or declared abstention")
        meaning = row.get("probability_semantics")
        if meaning is not None:
            _text(meaning, "probability_semantics")
        identity = _identity(row)
        result[(identity["example_id"], identity["question_id"])] = row
    return result


def _label(value: Any, *, binary: bool) -> str:
    if binary and isinstance(value, (bool, int, float)):
        number = float(value) if isinstance(value, bool) else _number(value, "binary value")
        if not 0 <= number <= 1:
            raise ValueError("binary value must be in [0,1]")
        return "true" if number >= .5 else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = _number(value, "label")
        return str(int(number)) if number.is_integer() else str(number)
    return _text(value, "label")


def _scores(row: Mapping[str, Any], *, labels: Sequence[str], label_kind: str,
            rule: str) -> tuple[dict[str, float | None], tuple[str, str] | None]:
    binary = label_kind == "binary"
    target = row["target"]
    if binary and isinstance(target, (int, float)) and not isinstance(target, bool) and target not in (0, 1):
        raise ValueError("binary targets must be hard labels; soft targets require a probability mapping")
    target_probs = validate_probabilities(target, labels=labels) if isinstance(target, Mapping) else None
    target_label = None if target_probs is not None else _label(target, binary=binary)
    if target_label is not None and target_label not in labels:
        raise ValueError("comparison target outside complete vocabulary")
    scores: dict[str, float | None] = {"accuracy": None, "brier": None, "ordinal_mae": None}
    if row["status"] != "completed" or row.get("abstained"):
        return scores, None
    prediction = row["prediction"]
    probs = row.get("probabilities")
    if probs is not None:
        probs = validate_probabilities(probs, labels=labels, rounding_digits=row.get("probability_rounding_digits"))
    if label_kind == "ordinal":
        number = _number(prediction, "ordinal prediction")
        bounds = [float(label) for label in labels]
        if not min(bounds) <= number <= max(bounds):
            raise ValueError("ordinal prediction outside declared bin coordinates")
        if target_probs is None:
            scores["ordinal_mae"] = abs(number - _number(target, "ordinal target"))
    if rule == "probability_argmax":
        predicted_label = max(probs, key=lambda label: probs[label]) if probs is not None else None
    else:
        predicted_label = _label(prediction, binary=binary)
        if predicted_label not in labels and label_kind != "ordinal":
            raise ValueError("comparison prediction outside complete vocabulary")
    if target_label is not None and predicted_label is not None:
        scores["accuracy"] = float(predicted_label == target_label)
    if probs is not None:
        target_probs = target_probs or {label: float(label == target_label) for label in labels}
        scores["brier"] = sum((probs[label] - target_probs[label]) ** 2 for label in labels)
    hard = (target_label, predicted_label) if target_label is not None and predicted_label is not None else None
    return scores, hard


def _macro_f1(pairs: list[tuple[str, str, str, str]], *, labels: Sequence[str], samples: int,
              seed: int, rules_match: bool) -> dict[str, Any]:
    """Recompute full-vocabulary macro-F1 for each shared group draw."""
    if not rules_match or not pairs:
        return _delta([], samples=samples, seed=seed, unit="macro_f1_fraction",
                      unavailable="incompatible_prediction_rules" if not rules_match else None)
    indices = {label: i for i, label in enumerate(labels)}
    groups: dict[str, Counter[tuple[int, int, int]]] = {}
    for group, target, left_label, right_label in pairs:
        groups.setdefault(group, Counter())[(indices[target], indices.get(left_label, -1), indices.get(right_label, -1))] += 1
    totals = [list(values.items()) for values in groups.values()]

    def estimate(multiplicities: list[int]) -> tuple[float, float]:
        target_count = [0] * len(labels)
        predicted = [[0] * len(labels) for _ in range(2)]
        correct = [[0] * len(labels) for _ in range(2)]
        for multiplicity, group in zip(multiplicities, totals, strict=True):
            if not multiplicity:
                continue
            for (target, a, b), count in group:
                weight = count * multiplicity
                target_count[target] += weight
                for arm, prediction in enumerate((a, b)):
                    if prediction >= 0:
                        predicted[arm][prediction] += weight
                        if prediction == target:
                            correct[arm][target] += weight
        estimates = []
        for arm in range(2):
            estimates.append(sum(2 * correct[arm][i] / (target_count[i] + predicted[arm][i])
                if target_count[i] + predicted[arm][i] else 0.0 for i in range(len(labels))) / len(labels))
        return estimates[0], estimates[1]

    left, right = estimate([1] * len(totals))
    interval: dict[str, Any] = {"status": "insufficient_groups", "low": None, "high": None,
                                "groups": len(totals), "samples": samples}
    if len(totals) >= 2:
        rng = random.Random(seed)
        differences = []
        for _ in range(samples):
            multiplicities = [0] * len(totals)
            for _ in totals:
                multiplicities[rng.randrange(len(totals))] += 1
            a, b = estimate(multiplicities)
            differences.append(b - a)
        interval = {"status": "ok", "low": nearest_rank_percentile(differences, 2.5),
                    "high": nearest_rank_percentile(differences, 97.5), "groups": len(totals),
                    "samples": samples, "method": "paired_grouped_percentile_95_macro_f1_recomputed"}
    return {"status": interval["status"] if interval["status"] != "ok" else "ok",
            "left": left, "right": right, "difference": right - left, "unit": "macro_f1_fraction",
            "paired_decisions": len(pairs), "independent_groups": len(totals), "interval": interval}


def _delta(pairs: list[tuple[str, float, float]], *, samples: int, seed: int,
           unit: str, unavailable: str | None = None) -> dict[str, Any]:
    if unavailable is not None or not pairs:
        return {"status": unavailable or "no_joint_measurements", "left": None, "right": None,
                "difference": None, "unit": unit, "paired_decisions": 0,
                "independent_groups": 0, "interval": None}
    left = sum(a for _, a, _ in pairs) / len(pairs)
    right = sum(b for _, _, b in pairs) / len(pairs)
    interval = grouped_bootstrap([(group, b - a) for group, a, b in pairs], samples=samples, seed=seed)
    return {"status": "ok" if interval["status"] == "ok" else "insufficient_groups", "left": left, "right": right,
            "difference": sum(b - a for _, a, b in pairs) / len(pairs), "unit": unit,
            "paired_decisions": len(pairs), "independent_groups": len({g for g, _, _ in pairs}), "interval": interval}


def compare_predictions(left_rows: Sequence[Mapping[str, Any]], right_rows: Sequence[Mapping[str, Any]], *,
                        left_binding: Mapping[str, Any], right_binding: Mapping[str, Any],
                        labels: Sequence[str], label_kind: str, bootstrap_samples: int = 2000,
                        seed: int = 0) -> dict[str, Any]:
    """Compare primary decisions with paired group draws and truthful coverage.

    Differences are right minus left. Only joint eligible measurements are
    scored; their conditional denominator is reported alongside every planned
    status. The intervals describe fixed predictions, not refits, optional
    stopping or selected-threshold risk guarantees. Missing beliefs stay absent.
    Caller-supplied bindings must come from independently verified artifacts.
    """
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if label_kind not in {"binary", "categorical", "ordinal", "soft"}:
        raise ValueError("unknown comparison label_kind")
    vocabulary = list(labels)
    if len(vocabulary) < 2 or any(not isinstance(label, str) or not label for label in vocabulary) or len(set(vocabulary)) != len(vocabulary):
        raise ValueError("comparison requires a complete unique vocabulary")
    if label_kind == "binary" and set(vocabulary) != {"false", "true"}:
        raise ValueError("binary comparison vocabulary must be false/true")
    if label_kind == "ordinal":
        try:
            numeric_labels = [float(label) for label in vocabulary]
        except ValueError as exc:
            raise ValueError("ordinal labels must be finite bin coordinates") from exc
        if any(not math.isfinite(label) for label in numeric_labels) or len(set(numeric_labels)) != len(numeric_labels):
            raise ValueError("ordinal labels must be finite unique bin coordinates")
    left_meta, right_meta = _binding(left_binding), _binding(right_binding)
    if any(left_meta[name] != right_meta[name] for name in _COMMON):
        raise ValueError("comparison cohort/input/split identity mismatch")
    left, right = _rows(left_rows, left_meta), _rows(right_rows, right_meta)
    pairs: dict[str, list[tuple[str, float, float]]] = {metric: [] for metric in ("accuracy", "brier", "ordinal_mae")}
    joint_applicable = joint_valid = 0
    hard_pairs = []
    meanings: dict[str, dict[str, Any]] = {}
    for name, values in (("left", left), ("right", right)):
        distributions = [row for row in values.values() if row["status"] == "completed" and row.get("probabilities") is not None]
        meanings[name] = {"declared": sorted({row["probability_semantics"] for row in distributions if row.get("probability_semantics") is not None}),
                          "unknown_distributions": sum(row.get("probability_semantics") is None for row in distributions)}
    for key in sorted(left):
        a, b = left[key], right[key]
        # Inventory hashes bind targets and input/group identity; check exact
        # materialized records too, rather than assuming coincident IDs suffice.
        if canonical_json(_identity(a)) != canonical_json(_identity(b)):
            raise ValueError("paired input/target/group identity mismatch")
        av, ah = _scores(a, labels=vocabulary, label_kind=label_kind, rule=left_meta["hard_prediction_rule"])
        bv, bh = _scores(b, labels=vocabulary, label_kind=label_kind, rule=right_meta["hard_prediction_rule"])
        if not (a["applicable"] and b["applicable"]):
            continue
        joint_applicable += 1
        if all(row["status"] == "completed" and not row.get("abstained") for row in (a, b)):
            joint_valid += 1
        if ah is not None and bh is not None:
            hard_pairs.append((a["group_id"], ah[0], ah[1], bh[1]))
        for metric in pairs:
            a_value, b_value = av[metric], bv[metric]
            if a_value is not None and b_value is not None:
                pairs[metric].append((_text(a["group_id"], "group_id"), a_value, b_value))
    rules_match = left_meta["hard_prediction_rule"] == right_meta["hard_prediction_rule"]
    units = {"accuracy": "fraction_correct", "brier": "sum_squared_probability_error", "ordinal_mae": "declared_bin_coordinates"}
    metrics = {metric: _delta(values, samples=bootstrap_samples, seed=seed, unit=units[metric],
               unavailable="incompatible_prediction_rules" if metric == "accuracy" and not rules_match else None)
               for metric, values in pairs.items()}
    if metrics["accuracy"]["difference"] is not None:
        metrics["accuracy"]["difference_pp"] = 100 * metrics["accuracy"]["difference"]
    metrics["macro_f1"] = _macro_f1(hard_pairs, labels=vocabulary, samples=bootstrap_samples,
                                   seed=seed, rules_match=rules_match)
    result = {"format": "dafjev.paired-comparison/1", "left_binding": left_meta, "right_binding": right_meta,
              "labels": vocabulary, "label_kind": label_kind, "planned_decisions": len(left),
              "planned_independent_groups": len({row["group_id"] for row in left.values()}),
              "planned_status_counts": {name: dict(Counter(row["status"] for row in rows.values())) for name, rows in (("left", left), ("right", right))},
              "joint_applicable_decisions": joint_applicable, "joint_valid_decisions": joint_valid,
              "joint_valid_coverage": joint_valid / joint_applicable if joint_applicable else None,
              "metrics": metrics, "probability_meaning_summary": meanings,
              "bootstrap_samples": bootstrap_samples, "seed": seed,
              "interpretation": "right minus left on joint measurements; paired row-weighted group percentile intervals over fixed predictions",
              "limits": ["all planned statuses retained; successful-pair metrics are conditional on measured pairs",
                         "caller supplies verified input/source bindings; this pure reducer does not attest external custody",
                         "unknown probability meaning remains descriptive; missing distributions are not invented",
                         "noncompleted partial predictions/distributions ignored for scoring; statuses retained",
                         "no refit uncertainty, sequential validity, selected-gate guarantee, cost or latency inference"]}
    canonical_json(result)
    return result
