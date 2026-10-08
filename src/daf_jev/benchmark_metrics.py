"""Ground-truth metrics and grouped uncertainty for benchmark observations.

Missing measurements remain ``None``. Infinite proper losses are represented
by an explicit status and count rather than clipped probabilities or JSON
Infinity. Failures and abstentions remain in the attempted denominator.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Any

from daf_jev._types import validate_probability_row
from daf_jev.benchmark_store import currency_context, usd_total

__all__ = ["audit_dataset", "grouped_bootstrap", "nearest_rank_percentile", "repeatability",
           "score_predictions", "validate_probabilities"]


def _number(value: Any, field: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise ValueError(f"{field} outside its allowed range")
    return result


def _cost(value: Any) -> Decimal:
    """Retain bounded decimal currency through aggregation and division."""
    try:
        return usd_total(value)
    except ValueError as exc:
        raise ValueError("cost_usd must be a finite nonnegative bounded decimal") from exc


def _currency_summary(costs: Sequence[Decimal], missing: int, decisions: int,
                      correct: float) -> dict[str, Any]:
    with localcontext(currency_context()):
        total = sum(costs, Decimal(0))
        return {"known_cost_usd": str(total), "total_cost_usd": str(total) if not missing else None,
            "cost_per_decision_usd": str(total / decisions) if not missing and decisions else None,
            "cost_per_correct_decision_usd": str(total / Decimal(str(correct))) if not missing and correct > 0 else None,
            "currency_arithmetic": "decimal; precision 50; ratios round half even",
            "cost_scope": "supplied request billing; local compute expense is separate"}


def nearest_rank_percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank (ceiling rank) percentile; pct=0 returns the minimum."""
    if not values:
        raise ValueError("percentile requires nonempty observations")
    pct = _number(pct, "percentile", minimum=0, maximum=100)
    ordered = sorted(_number(v, "observation") for v in values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def validate_probabilities(values: Mapping[str, Any], *, labels: Sequence[str] | None = None,
                           rounding_digits: int | None = None) -> dict[str, float]:
    """Validate a complete simplex without normalization or label reduction."""
    if not isinstance(values, Mapping) or not values or any(not isinstance(k, str) for k in values):
        raise ValueError("probabilities must be a nonempty string-keyed mapping")
    if labels is not None and set(values) != set(labels):
        raise ValueError("probability labels do not match the complete task vocabulary")
    probs = {k: _number(v, f"probability[{k}]", minimum=0, maximum=1) for k, v in values.items()}
    validate_probability_row(probs, rounding_digits=rounding_digits)
    return probs


def grouped_bootstrap(values: Sequence[tuple[str, float]], *, samples: int = 2000,
                      seed: int = 0) -> dict[str, Any]:
    """Percentile 95% interval resampling independent groups, retaining repeats."""
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("bootstrap samples must be a positive integer")
    groups: dict[str, list[float]] = defaultdict(list)
    for group, value in values:
        groups[group].append(_number(value, "bootstrap observation"))
    if len(groups) < 2:
        return {"status": "insufficient_groups", "low": None, "high": None,
                "groups": len(groups), "samples": samples}
    totals = [(sum(v), len(v)) for v in groups.values()]
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        draws = [totals[rng.randrange(len(totals))] for _ in totals]
        estimates.append(sum(t for t, _ in draws) / sum(n for _, n in draws))
    return {"status": "ok", "low": nearest_rank_percentile(estimates, 2.5),
            "high": nearest_rank_percentile(estimates, 97.5),
            "groups": len(groups), "samples": samples, "method": "grouped_percentile_95"}


def _label(value: Any, *, binary: bool) -> str:
    if binary and isinstance(value, (bool, int, float)):
        number = float(value) if isinstance(value, bool) else _number(value, "binary prediction", minimum=0, maximum=1)
        return "true" if number >= .5 else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = _number(value, "prediction/target")
        return str(int(number)) if number.is_integer() else str(number)
    if not isinstance(value, str):
        raise ValueError("hard targets and predictions must be labels or numeric scores")
    return value


def repeatability(rows: Sequence[Mapping[str, Any]], *, labels: Sequence[str] | None = None,
                  label_kind: str | None = None) -> dict[str, Any]:
    """Prediction stability over planned primary and warm observations.

    Targets are never used: modal agreement is self-consistency, not accuracy.
    A primary-only group or fewer than two valid observations is unavailable.
    Distribution distances use only explicitly supplied valid rows, without
    inventing missing beliefs or renormalizing native rounded probabilities.
    """
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    allowed_statuses = {"completed", "failed", "unsupported", "unattempted", "unresolved"}
    for row in rows:
        if row.get("example_id") is None or row.get("question_id") is None:
            raise ValueError("repeatability requires example_id and question_id")
        if row.get("phase") not in {"quality", "warm_repeat"} or row.get("status") not in allowed_statuses:
            raise ValueError("repeatability requires planned quality/warm_repeat phase and explicit status")
        grouped[(str(row["example_id"]), str(row["question_id"]))].append(row)
    binary = label_kind == "binary" or (labels is not None and set(labels) == {"false", "true"})
    groups: list[dict[str, Any]] = []
    repeated_rows = []
    for (example_id, question_id), observations in sorted(grouped.items()):
        primary = [row for row in observations if row["phase"] == "quality"]
        if len(primary) != 1:
            raise ValueError("repeatability groups require exactly one planned primary quality observation")
        if not any(row["phase"] == "warm_repeat" for row in observations):
            continue
        repeated_rows.extend(observations)
        completed = [row for row in observations if row["status"] == "completed" and row.get("error") is None
                     and row.get("prediction") is not None and not row.get("abstained")]
        hard_labels: list[str] = []
        distributions: list[dict[str, float]] = []
        invalid_distributions = 0
        missing_distributions = 0
        for row in completed:
            probs = None
            if row.get("probabilities") is None:
                missing_distributions += 1
            else:
                try:
                    probs = validate_probabilities(row["probabilities"], labels=labels,
                                                   rounding_digits=row.get("probability_rounding_digits"))
                except ValueError:
                    invalid_distributions += 1
                else:
                    if distributions and set(probs) != set(distributions[0]):
                        invalid_distributions += 1
                        probs = None
                    else:
                        distributions.append(probs)
            prediction = row["prediction"]
            label: str | None
            if label_kind == "ordinal" and probs is not None:
                label = max(labels or list(probs), key=lambda outcome: probs[outcome])
            elif label_kind == "ordinal" and isinstance(prediction, (int, float)) and not isinstance(prediction, bool):
                number = _number(prediction, "ordinal repeated prediction")
                label = str(int(number)) if number.is_integer() else None
            else:
                label = _label(prediction, binary=binary)
            if label is not None and (labels is None or label in labels):
                hard_labels.append(label)
        counts = Counter(hard_labels)
        n_labels = len(hard_labels)
        agreement = (sum(n * (n - 1) for n in counts.values()) / (n_labels * (n_labels - 1))) if n_labels >= 2 else None
        distances = [.5 * sum(abs(a[key] - b[key]) for key in a)
                     for i, a in enumerate(distributions) for b in distributions[i + 1:]]
        groups.append({"example_id": example_id, "question_id": question_id,
            "planned_observations": len(observations), "planned_warm_repeats": len(observations) - 1,
            "completed_observations": len(completed), "status_counts": dict(Counter(row["status"] for row in observations)),
            "primary_completed": primary[0] in completed, "label_observations": n_labels,
            "label_counts": dict(counts), "pairwise_label_agreement": agreement,
            "modal_share": max(counts.values()) / n_labels if n_labels >= 2 else None,
            "distribution_observations": len(distributions), "missing_distributions": missing_distributions,
            "invalid_distributions": invalid_distributions,
            "distribution_mean_pairwise_half_l1": sum(distances) / len(distances) if distances else None,
            "distribution_max_pairwise_half_l1": max(distances) if distances else None,
            "probability_semantics": sorted({row["probability_semantics"] for row in completed if row.get("probabilities") is not None and row.get("probability_semantics") is not None}),
            "unknown_probability_semantics": sum(row.get("probabilities") is not None and row.get("probability_semantics") is None for row in completed),
            "probability_sources": sorted({str(row["probability_source"]) if row.get("probability_source") is not None else "unavailable"
                                           for row in completed if row.get("probabilities") is not None})})
    agreements = [group["pairwise_label_agreement"] for group in groups if group["pairwise_label_agreement"] is not None]
    modal = [group["modal_share"] for group in groups if group["modal_share"] is not None]
    variation = [group["distribution_mean_pairwise_half_l1"] for group in groups if group["distribution_mean_pairwise_half_l1"] is not None]
    completed_rows = [row for row in repeated_rows if row["status"] == "completed" and row.get("error") is None
                      and row.get("prediction") is not None and not row.get("abstained")]
    return {"semantics": "prediction self-consistency; independent targets and accuracy are not used",
        "distribution_distance": "pairwise half L1 over supplied valid distributions; no normalization or imputation",
        "n_planned_groups": len(grouped), "n_repeated_groups": len(groups),
        "n_primary_only_groups": len(grouped) - len(groups), "n_planned_observations": len(rows),
        "n_repeated_planned_observations": len(repeated_rows), "n_repeated_completed_observations": len(completed_rows),
        "n_planned_warm_repeats": sum(row["phase"] == "warm_repeat" for row in repeated_rows),
        "n_completed_warm_repeats": sum(row["phase"] == "warm_repeat" for row in completed_rows),
        "repeated_status_counts": dict(Counter(row["status"] for row in repeated_rows)),
        "n_estimable_label_groups": len(agreements), "n_estimable_distribution_groups": len(variation),
        "mean_pairwise_label_agreement": sum(agreements) / len(agreements) if agreements else None,
        "mean_modal_share": sum(modal) / len(modal) if modal else None,
        "mean_distribution_pairwise_half_l1": sum(variation) / len(variation) if variation else None,
        "groups": groups}


def audit_dataset(dataset: Any, *, selected_example_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Offline full/preselected provenance, duplicate and wine-binning audit."""
    manifest = dataset.manifest.to_dict()
    examples = list(dataset.examples)
    selected_ids = set(selected_example_ids) if selected_example_ids is not None else {example.id for example in examples}
    if selected_ids - {example.id for example in examples}:
        raise ValueError("dataset audit selection contains unknown example IDs")

    def entropy(counts: Mapping[Any, int]) -> float | None:
        n = sum(counts.values())
        return -sum((count / n) * math.log2(count / n) for count in counts.values() if count) if n else None

    def wine(records: Sequence[Any]) -> dict[str, Any]:
        bins: dict[str, Counter[int]] = {label: Counter() for label in manifest["labels"]}
        for example in records:
            grade = example.metadata["original_grade"]
            label = str(example.targets["decision"])
            if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 10 or label not in bins:
                raise ValueError("wine audit requires original integer grades and declared bins")
            bounds = manifest["metadata"]["grade_bins"][int(label)]
            if not bounds[0] <= grade <= bounds[1]:
                raise ValueError("wine original grade does not match its declared bin")
            bins[label][grade] += 1
        grade_counts: Counter[int] = Counter()
        for histogram in bins.values():
            grade_counts.update(histogram)
        n = len(records)
        return {"n": n, "original_grade_histogram": {str(grade): grade_counts[grade] for grade in range(11)},
            "bins": {label: {"n": sum(histogram.values()), "original_grade_histogram": {str(grade): count for grade, count in sorted(histogram.items())},
                              "grade_entropy_bits": entropy(histogram)} for label, histogram in bins.items()},
            "original_grade_entropy_bits": entropy(grade_counts), "bin_entropy_bits": entropy({label: sum(hist.values()) for label, hist in bins.items()}),
            "conditional_grade_entropy_bits": sum(sum(hist.values()) / n * (entropy(hist) or 0) for hist in bins.values()) if n else None}

    def cohort(records: Sequence[Any]) -> dict[str, Any]:
        counts = Counter(example.group_id for example in records)
        splits: dict[str, set[str]] = defaultdict(set)
        targets: dict[str, set[str]] = defaultdict(set)
        for example in records:
            splits[example.group_id].add(example.split)
            targets[example.group_id].add(json.dumps(example.to_dict()["targets"], sort_keys=True, allow_nan=False))
        result: dict[str, Any] = {"examples": len(records), "split_counts": dict(Counter(e.split for e in records)),
            "independent_input_groups": len(counts), "duplicate_groups": sum(count > 1 for count in counts.values()),
            "duplicate_rows": sum(count for count in counts.values() if count > 1),
            "duplicate_excess_rows": sum(count - 1 for count in counts.values()),
            "cross_split_groups": sum(len(values) > 1 for values in splits.values()),
            "conflicting_target_groups": sum(len(values) > 1 for values in targets.values()),
            "leakage_clean_examples": sum(e.metadata.get("duplicate_sensitivity_cohort", True) for e in records)}
        if manifest["name"] == "wine":
            result["wine_binning"] = {**wine(records), "by_type": {kind: wine([e for e in records if e.metadata["wine_type"] == kind]) for kind in ("red", "white")},
                "grade_bins": manifest["metadata"]["grade_bins"],
                "information_loss_semantics": "empirical H(original_grade | bin), in bits; information lost by binning, not model prediction error"}
        return result
    metadata = manifest["metadata"]
    return {"dataset": manifest["name"], "source": manifest["source"], "source_revision": metadata.get("source_revision"),
        "license": manifest["license"], "source_sha256": manifest["sha256"],
        "official_bytes_verified": metadata.get("official_bytes_verified"), "source_counts": metadata.get("source_counts"),
        "split_policy": metadata.get("split_policy"), "split_seed": metadata.get("split_seed"),
        "selection_scope": "frozen planned quality/timing examples; independent of execution completion",
        "full": cohort(examples), "selected": cohort([example for example in examples if example.id in selected_ids])}


def score_predictions(rows: Sequence[Mapping[str, Any]], *, labels: Sequence[str] | None = None,
                      label_kind: str | None = None, n_buckets: int = 10,
                      wall_s: float | None = None, bootstrap_samples: int = 2000,
                      seed: int = 0, planned_rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Reduce one comparable cohort of question-level observation mappings.

    Keys: example_id/group_id, target, prediction, optional probabilities,
    confidence, latency_s, error, abstained and cost_usd. Soft probability
    targets receive proper distribution scores, never invented hard accuracy.
    ``wall_s`` must be the externally measured cohort wall time for throughput.
    ``planned_rows`` supplies frozen OOS denominators without creating outcomes.
    """
    if isinstance(n_buckets, bool) or not isinstance(n_buckets, int) or n_buckets < 1:
        raise ValueError("n_buckets must be a positive integer")
    if wall_s is not None:
        wall_s = _number(wall_s, "wall_s", minimum=0)
    hard: list[tuple[str, str, str]] = []
    correct: list[tuple[str, float]] = []
    absolute: list[tuple[str, float]] = []
    squared: list[tuple[str, float]] = []
    briers: list[tuple[str, float]] = []
    binary_briers: list[tuple[str, float]] = []
    log_losses: list[tuple[str, float]] = []
    calibration: list[tuple[float, float]] = []
    row_sum_deviations: list[float] = []
    latencies: list[float] = []
    costs: list[Decimal] = []
    n_errors = n_abstained = n_success = n_missing_cost = n_infinite = 0
    binary = label_kind == "binary" or (labels is not None and set(labels) == {"false", "true"})
    vocabulary = list(labels) if labels is not None else None
    for i, row in enumerate(rows):
        group = str(row.get("group_id", row.get("example_id", i)))
        if row.get("latency_s") is not None:
            latencies.append(_number(row["latency_s"], "latency_s", minimum=0))
        if row.get("cost_usd") is None:
            n_missing_cost += 1
        else:
            costs.append(_cost(row["cost_usd"]))
        if row.get("error") is not None:
            n_errors += 1
            continue
        if row.get("abstained") or row.get("prediction") is None:
            n_abstained += 1
            continue
        target = row["target"]
        prediction = row["prediction"]
        n_success += 1
        probs = row.get("probabilities")
        if probs is not None:
            probs = validate_probabilities(probs, labels=vocabulary,
                                           rounding_digits=row.get("probability_rounding_digits"))
            row_sum_deviations.append(sum(probs.values()) - 1)
        target_probs = validate_probabilities(target, labels=vocabulary) if isinstance(target, Mapping) else None
        confidence = row.get("confidence")
        if confidence is not None:
            confidence = _number(confidence, "confidence", minimum=0, maximum=1)
        if target_probs is None:
            target_label = _label(target, binary=binary)
            predicted_label = max(probs, key=lambda label: probs[label]) if label_kind == "ordinal" and probs is not None else _label(prediction, binary=binary)
            if vocabulary is not None and target_label not in vocabulary:
                raise ValueError("target label outside task vocabulary")
            if vocabulary is not None and predicted_label not in vocabulary and label_kind != "ordinal":
                raise ValueError("predicted label outside task vocabulary")
            correctness = float(predicted_label == target_label)
            correct.append((group, correctness))
            hard.append((group, target_label, predicted_label))
            if confidence is not None:
                calibration.append((confidence, correctness))
            if label_kind == "ordinal":
                delta = _number(prediction, "ordinal prediction") - _number(target, "ordinal target")
                absolute.append((group, abs(delta)))
                squared.append((group, delta * delta))
            if probs is not None:
                if target_label not in probs:
                    raise ValueError("probability vector is missing the target label")
                target_probs = {label: float(label == target_label) for label in probs}
        if probs is not None and target_probs is not None:
            if set(probs) != set(target_probs):
                raise ValueError("probabilities and soft targets have different labels")
            briers.append((group, sum((probs[outcome] - target_probs[outcome]) ** 2 for outcome in probs)))
            if set(probs) == {"false", "true"}:
                binary_briers.append((group, (probs["true"] - target_probs["true"]) ** 2))
            if any(target_probs[outcome] > 0 and probs[outcome] == 0 for outcome in probs):
                n_infinite += 1
            else:
                loss = -sum(target_probs[outcome] * math.log(probs[outcome]) for outcome in probs if target_probs[outcome] > 0)
                log_losses.append((group, loss))
    classes = vocabulary or sorted({t for _, t, _ in hard} | {p for _, _, p in hard})
    confusion = {target: {pred: 0 for pred in classes} for target in classes}
    for _, target, predicted in hard:
        if predicted not in confusion[target]:
            # Fractional ordinal predictions have no categorical label; retain
            # them as explicit confusion columns, with MAE/RMSE as primary scores.
            for values in confusion.values():
                values.setdefault(predicted, 0)
        confusion[target][predicted] += 1
    f1s = []
    for label in classes:
        tp = sum(t == label and p == label for _, t, p in hard)
        fp = sum(t != label and p == label for _, t, p in hard)
        fn = sum(t == label and p != label for _, t, p in hard)
        f1s.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    buckets = []
    for i in range(n_buckets):
        pairs = [(c, y) for c, y in calibration if min(int(c * n_buckets), n_buckets - 1) == i]
        if pairs:
            buckets.append({"bucket_lo": i / n_buckets, "bucket_hi": (i + 1) / n_buckets,
                            "n": len(pairs), "mean_confidence": sum(c for c, _ in pairs) / len(pairs),
                            "accuracy": sum(y for _, y in pairs) / len(pairs)})
    ece = sum(b["n"] * abs(b["mean_confidence"] - b["accuracy"]) for b in buckets) / len(calibration) if calibration else None

    def mean(values: Sequence[tuple[str, float]]) -> float | None:
        return sum(v for _, v in values) / len(values) if values else None

    accuracy = mean(correct)
    total_correct = sum(value for _, value in correct)
    oos_detection = None
    positive_labels = set(labels or ()) & {"oos", "out_of_scope"}
    if positive_labels:
        tp = sum(target in positive_labels and predicted in positive_labels for _, target, predicted in hard)
        fp = sum(target not in positive_labels and predicted in positive_labels for _, target, predicted in hard)
        fn = sum(target in positive_labels and predicted not in positive_labels for _, target, predicted in hard)
        tn = sum(target not in positive_labels and predicted not in positive_labels for _, target, predicted in hard)
        statuses: Counter[str] = Counter()
        positive_statuses: Counter[str] = Counter()
        soft_planned = 0
        for row in planned_rows if planned_rows is not None else rows:
            target = row["target"]
            if isinstance(target, Mapping):
                soft_planned += 1
                continue
            target_label = _label(target, binary=False)
            if target_label not in (labels or ()):
                raise ValueError("planned OOS target outside task vocabulary")
            status = row.get("status") or ("failed" if row.get("error") is not None else "abstained" if row.get("prediction") is None or row.get("abstained") else "completed")
            statuses[status] += 1
            if target_label in positive_labels:
                positive_statuses[status] += 1
        oos_detection = {"positive_labels": sorted(positive_labels), "semantics": "out-of-scope detection over valid hard outcomes; official labels unchanged",
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "specificity": tn / (tn + fp) if tn + fp else None,
            "n_planned_hard": sum(statuses.values()), "n_planned_soft": soft_planned,
            "n_planned_oos": sum(positive_statuses.values()), "n_valid_hard": len(hard), "n_valid_oos": tp + fn,
            "n_failed_oos": positive_statuses["failed"], "planned_status_counts": dict(statuses),
            "planned_oos_status_counts": dict(positive_statuses)}
    result: dict[str, Any] = {
        "n_attempted": len(rows), "n_success": n_success, "n_errors": n_errors,
        "n_abstained": n_abstained, "n_hard_targets": len(hard), "probability_meaning_summary": {"declared": sorted({row["probability_semantics"] for row in rows if row.get("probabilities") is not None and row.get("probability_semantics") is not None}),
            "unknown_distributions": sum(row.get("probabilities") is not None and row.get("probability_semantics") is None for row in rows)},
        "n_probability_scores": len(briers),
        "probability_row_sum_deviations": row_sum_deviations,
        "accuracy": accuracy, "macro_f1": sum(f1s) / len(f1s) if hard and f1s else None,
        "confusion": confusion, "ordinal_mae": mean(absolute),
        "ordinal_rmse": math.sqrt(mean(squared) or 0) if squared else None,
        "brier": mean(briers), "brier_definition": "sum of squared errors over all classes",
        "binary_brier": mean(binary_briers),
        "log_loss": None if n_infinite else mean(log_losses),
        "log_loss_status": "infinite" if n_infinite else "ok" if log_losses else "unavailable",
        "n_infinite_log_loss": n_infinite, "ece": ece, "reliability": buckets,
        "out_of_scope_detection": oos_detection,
        "coverage": n_success / len(rows) if rows else None,
        "selective_risk": 1 - accuracy if accuracy is not None else None,
        "failure_rate": n_errors / len(rows) if rows else None,
        "latency": {"n": len(latencies), "mean_s": sum(latencies) / len(latencies) if latencies else None,
                    "p50_s": nearest_rank_percentile(latencies, 50) if latencies else None,
                    "p95_s": nearest_rank_percentile(latencies, 95) if latencies else None,
                    "p99_s": nearest_rank_percentile(latencies, 99) if latencies else None,
                    "percentile_method": "nearest_rank"},
        "throughput_per_s": n_success / wall_s if wall_s else None,
        "throughput_wall_s": wall_s, **_currency_summary(costs, n_missing_cost, n_success, total_correct),
        "n_missing_cost": n_missing_cost,
        "uncertainty": {"accuracy": grouped_bootstrap(correct, samples=bootstrap_samples, seed=seed),
                        "brier": grouped_bootstrap(briers, samples=bootstrap_samples, seed=seed),
                        "ordinal_mae": grouped_bootstrap(absolute, samples=bootstrap_samples, seed=seed)},
    }
    return result
