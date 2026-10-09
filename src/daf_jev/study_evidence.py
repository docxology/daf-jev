"""Pure consumption of selected study aggregates; no inference or plotting.

These are retained descriptive summaries, not newly executed studies. Interval
limits are consumed as recorded, never refitted from summary point estimates.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import localcontext
from pathlib import Path
from typing import Any

from ._json import strict_json_loads
from .benchmark_policies import GateCalibration
from .benchmark_store import currency_context, usd_total
from .evidence import selected_study_bytes


def count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("study count must be a nonnegative integer")
    return value


def number(value: Any, *, upper: float | None = None) -> float:
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and value >= 0 and (upper is None or value <= upper))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("study metric must be finite and within its declared bounds")
    return float(value)


def interval(item: Any, estimate: float, *, upper: float | None = None,
             max_groups: int | None = None) -> tuple[float, float]:
    if (not isinstance(item, dict) or item.get("status") != "ok"
            or item.get("method") != "grouped_percentile_95"
            or count(item.get("samples")) != 2000 or count(item.get("groups")) < 2):
        raise ValueError("study interval requires retained grouped percentile evidence")
    if max_groups is not None and count(item["groups"]) > count(max_groups):
        raise ValueError("study interval groups exceed observed scoring units")
    low, high = number(item.get("low"), upper=upper), number(item.get("high"), upper=upper)
    number(estimate, upper=upper)
    if low > high:
        raise ValueError("study interval bounds must be ordered")
    return low, high


def statuses(item: dict[str, Any], *, nested: bool = False) -> dict[str, int]:
    source = item["denominators"] if nested else item
    values = {k: count(source.get(k, 0)) for k in (
        "completed", "unsupported", "failed", "unresolved", "unattempted")}
    if sum(values.values()) != count(item.get("planned_cells")):
        raise ValueError("study status denominator mismatch")
    return values


@dataclass(frozen=True)
class StudyEvidence:
    cpu: dict[str, Any]
    hosted: dict[str, Any]
    hashes: dict[str, str]

    def arm(self, dataset: str, backend: str, *, job: str = "official-final-train",
            split: str = "test") -> dict[str, Any]:
        rows = [r for r in self.cpu["arms"] if (r["dataset"], r["backend"], r["job"], r["split"])
                == (dataset, backend, job, split)]
        if len(rows) != 1:
            raise ValueError("selected study arm must be unique")
        return rows[0]

    def metric(self, row: dict[str, Any], key: str) -> float:
        return number(row["metrics"][key], upper={"accuracy": 1.0, "brier": 2.0 + 1e-12}.get(key))

    def limits(self, row: dict[str, Any], key: str) -> tuple[float, float]:
        units = "n_probability_scores" if key == "brier" else "n_hard_targets"
        return interval(row["metrics"]["uncertainty"][key], self.metric(row, key),
                        upper={"accuracy": 1.0, "brier": 2.0 + 1e-12}.get(key),
                        max_groups=min(count(row["independent_groups"]), count(row["metrics"][units])))

    def gates(self) -> list[dict[str, Any]]:
        # Primary validation fits, excluding final refits and small synthetic suites.
        return [r for r in self.cpu["validation_gates"]
                if r["job"].startswith("banking77-selection-fold") or r["job"] == "clinc-wine-selection"]

    def tokens(self) -> dict[str, str]:
        h = self.hosted["hosted_pilot"]
        native = self.hosted["historical_native_study"]
        cpu_counts = self.cpu["status_counts"]
        quality = count(self.cpu["phase_status_counts"]["quality"]["completed"])
        values = {
            "STUDY_CPU_JOBS": len(self.cpu["runs"]),
            "STUDY_CPU_PLANNED": self.cpu["planned_cells"],
            "STUDY_CPU_COMPLETED": cpu_counts["completed"],
            "STUDY_CPU_QUALITY": quality,
            "STUDY_CPU_UNSUPPORTED": cpu_counts["unsupported"],
            "STUDY_BANK_ACCURACY_PCT": f"{100 * self.metric(self.arm('banking77', 'tfidf-logistic-C1'), 'accuracy'):.2f}",
            "STUDY_CLINC_ACCURACY_PCT": f"{100 * self.metric(self.arm('clinc150', 'tfidf-logistic-C1'), 'accuracy'):.2f}",
            "STUDY_WINE_MAE": f"{self.metric(self.arm('wine', 'wine-hist-gradient-boosting'), 'ordinal_mae'):.4f}",
            "STUDY_WINE_PRIOR_MAE": f"{self.metric(self.arm('wine', 'prior'), 'ordinal_mae'):.4f}",
            "STUDY_NATIVE_COMPLETED": native["completed"],
            "STUDY_HOSTED_PLANNED": h["planned_cells"],
            "STUDY_HOSTED_ATTEMPTS": h["actual_transport_attempts"],
            "STUDY_HOSTED_FAILED": h["denominators"]["failed"],
            "STUDY_HOSTED_UNSUPPORTED": h["denominators"]["unsupported"],
            "STUDY_HOSTED_UNATTEMPTED": h["denominators"]["unattempted"],
            "STUDY_HOSTED_LIMIT_USD": h["accounting"]["limit_usd"],
            "STUDY_HOSTED_UNRESOLVED_BILLING": len(h["accounting"]["unresolved_attempts"]),
        }
        return {k: str(v) for k, v in values.items()}


def load_studies(project_root: Path) -> StudyEvidence:
    docs: dict[str, Any] = {}
    hashes = {}
    for key, format_name in (
        ("cpu", "dafjev.full-offline-comparison/1"),
        ("hosted", "dafjev.hosted-pilot-continuation-summary/1"),
    ):
        raw = selected_study_bytes(project_root, key)
        value = strict_json_loads(raw)
        if not isinstance(value, dict) or value.get("format") != format_name:
            raise ValueError("invalid selected study summary format")
        docs[key], hashes[key] = value, hashlib.sha256(raw).hexdigest()
    cpu, hosted = docs["cpu"], docs["hosted"]
    try:
        cpu_counts = statuses({"planned_cells": cpu["planned_cells"], **cpu["status_counts"]})
        phase_totals = {k: 0 for k in cpu_counts}
        for phase in cpu["phase_status_counts"].values():
            if not isinstance(phase, dict) or set(phase) - set(phase_totals):
                raise ValueError("invalid study phase inventory")
            for key, value in phase.items():
                phase_totals[key] += count(value)
        if phase_totals != cpu_counts:
            raise ValueError("study phase/status denominator mismatch")
        if not isinstance(cpu["runs"], list) or not cpu["runs"]:
            raise ValueError("study run inventory must be nonempty")
        run_totals = {k: 0 for k in cpu_counts}
        for run in cpu["runs"]:
            for key, value in statuses(run, nested=True).items():
                run_totals[key] += value
        if run_totals != cpu_counts:
            raise ValueError("study run/status denominator mismatch")
        h = hosted["hosted_pilot"]
        hosted_counts = statuses(h, nested=True)
        if (sum(count(v) for v in h["phase_denominators"].values()) != count(h["planned_cells"])
                or count(h["completed_quality_predictions"]) + count(h["completed_warm_predictions"])
                > hosted_counts["completed"]):
            raise ValueError("hosted study phase/prediction denominator mismatch")
        statuses(hosted["historical_native_study"])
        count(h["actual_transport_attempts"])
        count(hosted["full_study_obligations"]["full_proposed_cells"])
        if count(h["actual_transport_attempts"]) != len(h["attempt_receipts"]):
            raise ValueError("study attempt denominator mismatch")
        accounting = h["accounting"]
        usd_total(accounting["limit_usd"])
        usd_total(accounting["reserved_usd"])
        if not isinstance(accounting["unresolved_attempts"], list):
            raise ValueError("invalid unresolved attempt inventory")
        attempt_ids: set[str] = set()
        unknown: set[str] = set()
        with localcontext(currency_context()):
            reported = usd_total("0")
            for receipt in h["attempt_receipts"]:
                ident = receipt["attempt_id"]
                if not isinstance(ident, str) or not ident or ident in attempt_ids:
                    raise ValueError("invalid study attempt identity")
                attempt_ids.add(ident)
                if receipt["cost_status"] == "unknown" and receipt["cost_usd"] is None:
                    unknown.add(ident)
                elif receipt["cost_status"] == "reported":
                    reported += usd_total(receipt["cost_usd"])
                else:
                    raise ValueError("invalid study billing provenance")
            if reported != usd_total(accounting["reported_cost_usd"]):
                raise ValueError("reported study billing total mismatch")
        unresolved = accounting["unresolved_attempts"]
        if (any(not isinstance(k, str) for k in unresolved)
                or len(unresolved) != len(set(unresolved)) or set(unresolved) != unknown
                or type(accounting["admission_stopped"]) is not bool
                or (unknown and accounting["admission_stopped"] is not True)):
            raise ValueError("unresolved study billing requires stopped admission")
        count(cpu["phase_status_counts"]["quality"]["completed"])
        identities = set()
        for row in cpu["arms"]:
            ident = tuple(row[k] for k in ("dataset", "backend", "job", "split"))
            if any(not isinstance(k, str) or not k for k in ident) or ident in identities:
                raise ValueError("study arm identity must be unique and complete")
            identities.add(ident)
            metrics = row["metrics"]
            successful, hard, planned = (count(metrics[k]) for k in
                                         ("n_success", "n_hard_targets", "planned_cells"))
            if not hard <= successful <= planned:
                raise ValueError("invalid study prediction denominators")
            groups = count(row["independent_groups"])
            if groups > planned:
                raise ValueError("study input groups exceed planned decisions")
            scored = count(metrics["n_probability_scores"])
            if scored > successful or (scored == 0 and metrics["brier"] is not None):
                raise ValueError("study probability metrics require scored predictions")
            if ((hard == 0 and metrics["accuracy"] is not None)
                    or (successful == 0 and any(metrics[k] is not None for k in
                                               ("brier", "ordinal_mae", "ordinal_rmse")))):
                raise ValueError("study metrics require observed predictions and targets")
            for k in ("accuracy", "brier", "ordinal_mae", "ordinal_rmse"):
                if metrics[k] is not None:
                    value = number(metrics[k], upper={"accuracy": 1.0, "brier": 2.0 + 1e-12}.get(k))
                    if k != "ordinal_rmse" and metrics["uncertainty"][k].get("status") == "ok":
                        interval(metrics["uncertainty"][k], value,
                                 upper={"accuracy": 1.0, "brier": 2.0 + 1e-12}.get(k),
                                 max_groups=min(groups, scored if k == "brier" else hard))
        for row in cpu["banking77_fivefold_oof"]:
            groups, rows = count(row["input_groups"]), count(row["physical_rows"])
            if groups > rows:
                raise ValueError("pooled study input groups exceed observations")
            interval(row["grouped_interval"], number(row["accuracy"], upper=1), upper=1, max_groups=groups)
        for row in cpu["validation_gates"]:
            c = row["calibration"]
            accepted, errors, total = (count(c[k]) for k in ("n_groups", "n_errors", "validation_groups"))
            if total == 0 or not errors <= accepted <= total:
                raise ValueError("invalid validation gate denominators")
            if (c["method"] != "grouped_wilson_upper" or c["confidence_level"] != .95
                    or c["max_risk"] != .05):
                raise ValueError("validation gate must use the declared Wilson protocol")
            GateCalibration(**{k: c[k] for k in (
                "status", "threshold", "max_risk", "wilson_upper", "n_groups", "n_errors",
                "validation_groups", "confidence_level")})
            if c["threshold"] is None:
                if accepted or errors or c["wilson_upper"] is not None:
                    raise ValueError("ineligible gate cannot imply zero risk")
            else:
                number(c["threshold"], upper=1)
                bound = number(c["wilson_upper"], upper=1)
                if accepted == 0 or bound < errors / accepted:
                    raise ValueError("invalid validation risk bound")
    except (KeyError, TypeError) as exc:
        raise ValueError("incomplete selected study summary") from exc
    return StudyEvidence(cpu, hosted, hashes)
