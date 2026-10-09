"""Validation-only confidence gates and explicit offline policy replay.

Gate admission uses a two-sided 95% Wilson upper bound over independent
groups. Insufficient validation evidence abstains; repeated requests cannot
inflate the effective validation sample. These replay functions do no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import localcontext
from typing import Any

from daf_jev.benchmark_metrics import validate_probabilities
from daf_jev.benchmark_store import currency_context, usd_total

__all__ = ["GateCalibration", "calibrate_gate", "entropy_reask", "replay_policy", "wilson_upper"]


@dataclass(frozen=True)
class GateCalibration:
    status: str
    threshold: float | None
    max_risk: float
    wilson_upper: float | None
    n_groups: int
    n_errors: int
    validation_groups: int
    confidence_level: float = .95

    def __post_init__(self) -> None:
        if self.status not in {"admitted", "insufficient_evidence"}:
            raise ValueError("gate status must be admitted or insufficient_evidence")
        if (isinstance(self.max_risk, bool) or not isinstance(self.max_risk, (int, float))
                or not math.isfinite(self.max_risk) or not 0 < self.max_risk < 1):
            raise ValueError("gate max_risk must be strictly between zero and one")
        if self.confidence_level != .95:
            raise ValueError("gate confidence_level must match the supported 95% Wilson rule")
        for name in ("n_groups", "n_errors", "validation_groups"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"gate {name} must be a nonnegative integer")
        if self.status == "insufficient_evidence":
            if self.threshold is not None or self.wilson_upper is not None or self.n_groups != 0 or self.n_errors != 0:
                raise ValueError("unadmitted gate must not carry accepted groups or a threshold")
            return
        if self.n_groups < 1 or self.n_errors > self.n_groups or self.n_groups > self.validation_groups:
            raise ValueError("admitted gate requires consistent independent validation group counts")
        if (self.threshold is None or isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float))
                or not math.isfinite(self.threshold)
                or not 0 <= self.threshold <= 1):
            raise ValueError("admitted gate threshold must be finite and in [0,1]")
        expected = wilson_upper(self.n_errors, self.n_groups)
        if (self.wilson_upper is None or isinstance(self.wilson_upper, bool)
                or not isinstance(self.wilson_upper, (int, float))
                or not math.isfinite(self.wilson_upper)
                or not math.isclose(self.wilson_upper, expected, rel_tol=0, abs_tol=1e-12)
                or self.wilson_upper > self.max_risk):
            raise ValueError("admitted gate requires its exact Wilson upper bound within max_risk")

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "threshold": self.threshold, "max_risk": self.max_risk,
                "wilson_upper": self.wilson_upper, "n_groups": self.n_groups,
                "n_errors": self.n_errors, "validation_groups": self.validation_groups,
                "confidence_level": self.confidence_level, "method": "grouped_wilson_upper",
                "target_semantics": "independent hard validation labels"}


def wilson_upper(errors: int, n: int, *, z: float = 1.959963984540054) -> float:
    """Upper endpoint of the two-sided 95% Wilson interval by default."""
    if isinstance(errors, bool) or isinstance(n, bool) or not isinstance(errors, int) or not isinstance(n, int) or n < 1 or not 0 <= errors <= n:
        raise ValueError("Wilson needs integer 0 <= errors <= n and n >= 1")
    if not math.isfinite(z) or z <= 0:
        raise ValueError("Wilson z must be finite and positive")
    p, z2 = errors / n, z * z
    return (p + z2 / (2 * n) + z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def _valid_confidence(row: Mapping[str, Any]) -> float | None:
    confidence = row.get("confidence")
    if confidence is None:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("policy confidence must be finite and in [0,1]")
    return float(confidence)


def _correct(row: Mapping[str, Any]) -> bool:
    target, prediction = row["target"], row.get("prediction")
    if isinstance(target, Mapping):
        raise ValueError("confidence gate fitting requires independent hard labels, not soft targets")
    if isinstance(target, (int, float)) and not isinstance(target, bool) and row.get("probabilities") is not None:
        probs = validate_probabilities(row["probabilities"], rounding_digits=row.get("probability_rounding_digits"))
        if set(probs) == {"false", "true"} and target in (0, 1):
            if isinstance(prediction, (int, float)) and not isinstance(prediction, bool):
                if not math.isfinite(prediction) or not 0 <= prediction <= 1:
                    raise ValueError("binary gate prediction must be finite and in [0,1]")
                return (prediction >= .5) == bool(target)
            return prediction == ("true" if target == 1 else "false")
        return max(probs, key=lambda label: probs[label]) == str(int(target))
    if isinstance(prediction, (int, float)) and not isinstance(prediction, bool) and target in {"false", "true"}:
        prediction = "true" if prediction >= .5 else "false"
    return prediction == target


def calibrate_gate(rows: Sequence[Mapping[str, Any]], *, max_risk: float = .05) -> GateCalibration:
    """Choose highest-coverage admitted threshold using validation rows only.

    All accepted rows of a group must be correct for that group to count as
    correct. The Wilson bound is a descriptive validation admission rule, not
    a distribution-free guarantee for a threshold selected on the same data.
    """
    if not math.isfinite(max_risk) or not 0 < max_risk < 1:
        raise ValueError("max_risk must be strictly between zero and one")
    if any(row.get("split") != "validation" for row in rows):
        raise ValueError("gate calibration is validation-only; test/train rows are forbidden")
    eligible = []
    all_groups = set()
    for i, row in enumerate(rows):
        group = str(row.get("group_id", row.get("example_id", i)))
        all_groups.add(group)
        confidence = _valid_confidence(row)
        if confidence is not None and row.get("error") is None and row.get("prediction") is not None and not row.get("abstained"):
            eligible.append((group, confidence, _correct(row)))
    candidates = sorted({c for _, c, _ in eligible})
    best: tuple[float, float, int, int] | None = None
    for threshold in candidates:
        accepted: dict[str, bool] = {}
        for group, confidence, correct in eligible:
            if confidence >= threshold:
                accepted[group] = accepted.get(group, True) and correct
        n = len(accepted)
        errors = sum(not value for value in accepted.values())
        upper = wilson_upper(errors, n)
        if upper <= max_risk and (best is None or n > best[2]):
            best = (threshold, upper, n, errors)
    if best is None:
        return GateCalibration("insufficient_evidence", None, max_risk, None, 0, 0, len(all_groups))
    threshold, upper, n, errors = best
    return GateCalibration("admitted", threshold, max_risk, upper, n, errors, len(all_groups))


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    if row.get("example_id") is None:
        raise ValueError("policy replay requires stable example_id")
    return str(row["example_id"]), str(row.get("question_id", "decision"))


def replay_policy(rows: Sequence[Mapping[str, Any]], *, policy: str = "direct",
                  threshold: float | None = None, gate: GateCalibration | None = None,
                  strong_rows: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Replay direct, confidence gate or weak→strong cascade from receipts.

    Cascades require aligned independent strong-model rows; no idealized
    strong oracle is silently invented. Only invoked strong rows are charged.
    An unadmitted calibrated gate abstains (or sends every row to strong).
    """
    if policy not in {"direct", "gate", "cascade"}:
        raise ValueError("policy must be direct, gate or cascade")
    if gate is not None:
        if threshold is not None:
            raise ValueError("choose a calibration or an explicit threshold, not both")
        threshold = gate.threshold if gate.status == "admitted" else None
    elif policy != "direct" and threshold is None:
        raise ValueError("gate/cascade requires explicit calibration or threshold")
    if threshold is not None and (isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1):
        raise ValueError("policy threshold must be finite and in [0,1]")
    strong: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in strong_rows or ():
        key = _key(row)
        if key in strong:
            raise ValueError("duplicate strong-model replay identity")
        strong[key] = row
    results = []
    for row in rows:
        if row.get("cost_usd") is not None:
            usd_total(row["cost_usd"])
        result = dict(row)
        confidence = _valid_confidence(row)
        accepted = row.get("error") is None and row.get("prediction") is not None and not row.get("abstained") and confidence is not None and threshold is not None and confidence >= threshold
        result.update({"policy": policy, "policy_replay": True, "strong_invoked": False,
                       "weak_backend_id": row.get("backend_id"), "strong_backend_id": None})
        if policy == "direct" or accepted:
            results.append(result)
            continue
        if policy == "gate":
            result.update({"prediction": None, "abstained": True, "policy_reason": "confidence_gate"})
        else:
            other = strong.get(_key(row))
            result["strong_invoked"] = True
            if other is None:
                result.update({"prediction": None, "abstained": True, "error": "missing_strong_receipt",
                               "policy_reason": "missing_strong_receipt", "cost_usd": None})
            else:
                if other["target"] != row["target"] or str(other.get("group_id")) != str(row.get("group_id")):
                    raise ValueError("strong replay row target/group does not align")
                if other.get("cost_usd") is not None:
                    usd_total(other["cost_usd"])
                for field in ("prediction", "probabilities", "confidence", "error", "abstained",
                              "probability_source", "probability_semantics", "confidence_semantics", "probability_rounding_digits", "backend_id"):
                    result[field] = other.get(field)
                result["policy_reason"] = "strong_fallback"
                for field in ("latency_s", "cost_usd"):
                    a, b = row.get(field), other.get(field)
                    if a is not None and b is not None:
                        if field == "cost_usd":
                            with localcontext(currency_context()):
                                result[field] = str(usd_total(a) + usd_total(b))
                            continue
                        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in (a, b)):
                            raise ValueError(f"cascade {field} must be finite and nonnegative")
                        result[field] = a + b
                    else:
                        result[field] = None
                result["strong_backend"] = other.get("backend_id")
                result["strong_backend_id"] = other.get("backend_id")
        results.append(result)
    return results


def entropy_reask(posteriors: Mapping[str, Mapping[str, float]], oracle: Mapping[str, str], *,
                  asked: Sequence[str] = (), max_reveals: int = 3) -> dict[str, Any]:
    """Synthetic independent-variable oracle simulation with at most 3 reveals.

    This exposes supplied hidden assignments; it performs no model request and
    must be labeled an oracle policy rather than actual repeated inference.
    Ties use insertion order. A reveal replaces only its own posterior row.
    """
    if isinstance(max_reveals, bool) or not isinstance(max_reveals, int) or not 0 <= max_reveals <= 3:
        raise ValueError("synthetic oracle permits zero through three reveals")
    probabilities = {var: validate_probabilities(row) for var, row in posteriors.items()}
    if set(asked) - set(probabilities):
        raise ValueError("asked variable is absent from the posterior rows")
    remaining = [var for var in probabilities if var not in asked]
    reveals = []
    for _ in range(min(max_reveals, len(remaining))):
        entropies = {var: -sum(p * math.log2(p) for p in probabilities[var].values() if p > 0) for var in remaining}
        variable = max(remaining, key=lambda var: entropies[var])
        if variable not in oracle or oracle[variable] not in probabilities[variable]:
            raise ValueError("synthetic oracle assignment missing or outside the variable vocabulary")
        observed = oracle[variable]
        probabilities[variable] = {label: float(label == observed) for label in probabilities[variable]}
        reveals.append({"variable": variable, "value": observed, "entropy_before_bits": entropies[variable]})
        remaining.remove(variable)
    return {"policy": "synthetic_entropy_oracle", "simulation": True,
            "assumption": "independent variables; reveal only updates its own row",
            "max_reveals": max_reveals, "reveals": reveals, "posteriors": probabilities}
