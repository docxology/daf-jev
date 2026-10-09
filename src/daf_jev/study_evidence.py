"""Pure consumption of selected study aggregates; no inference or plotting.

These are retained descriptive summaries, not newly executed studies. Interval
limits are consumed as recorded, never refitted from summary point estimates.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import localcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ._json import strict_json_loads
from ._types import validate_probability_row
from .benchmark_policies import GateCalibration
from .benchmark_store import currency_context, usd, usd_total
from .decision_backends import CallReceipt, HTTPResponseDiagnostics
from .evidence import has_selected_study, selected_study_bytes

NATIVE_HOSTED_FORMAT = "dafjev.native-hosted-study-summary/1"
_PHASES = ("capability_probe", "quality", "warm_repeat", "graphical")
_STATUSES = ("completed", "unsupported", "failed", "unresolved", "unattempted")
_METRIC_KEYS = frozenset({"metrics", "accuracy", "macro_f1", "f1", "brier", "binary_brier", "log_loss",
                          "calibration", "ece", "ordinal_mae", "ordinal_rmse", "selective_risk",
                          "confusion", "reliability", "uncertainty", "cost_per_correct_decision"})
_PROBE_TARGETS = {"banking77": ("choice", 77), "clinc150": ("choice", 151), "wine": ("score", 5),
                  "synthetic-binary": ("noul", 0), "synthetic-categorical": ("choice", 3),
                  "synthetic-ordinal": ("score", 4), "synthetic-bayes": ("choice", 2),
                  "synthetic-categorical-matched-options-v3": ("choice", 3)}
_PRIVATE_TEXT = re.compile(r"/Users/|/home/|/private/|/tmp/|[A-Za-z]:[\\/]Users[\\/]", re.I)
_SECRET_TEXT = re.compile(r"sk-or-|sk-[A-Za-z0-9]{12,}|Bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
_SENSITIVE_KEYS = frozenset({"api_key", "apikey", "authorization", "proxy_authorization", "headers",
                           "request_headers", "response_headers", "access_token", "refresh_token", "password", "secret"})
_RECEIPT_FIELDS = frozenset(field.name for field in fields(CallReceipt))
_DIAGNOSTIC_FIELDS = frozenset(field.name for field in fields(HTTPResponseDiagnostics))


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


def _identity(value: Any, *, sha: bool = False) -> str:
    if (not isinstance(value, str) or not value.strip()
            or (sha and not re.fullmatch(r"[a-f0-9]{64}", value))):
        raise ValueError("native study requires complete identities and SHA-256 hashes")
    return value


def _timestamp(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(_identity(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("native study timestamp must be ISO UTC") from exc
    if stamp.utcoffset() != timedelta(0):
        raise ValueError("native study timestamp must be ISO UTC")
    return stamp


def _no_supplied_metrics(value: Any) -> None:
    """This export records observations; quality estimates require another schema."""
    if isinstance(value, dict):
        if _METRIC_KEYS.intersection(value):
            raise ValueError("native capability summary cannot supply quality metrics")
        for item in value.values():
            _no_supplied_metrics(item)
    elif isinstance(value, list):
        for item in value:
            _no_supplied_metrics(item)


def _publication_privacy(value: Any) -> None:
    """Check decoded keys and text before identifiers can reach figure labels.

    Credential environment names and bearer scheme metadata remain permissible;
    credential/header values and personal filesystem paths never become public.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or key.lower().replace("-", "_") in _SENSITIVE_KEYS:
                    raise ValueError("private credential/header field in native publication evidence")
                pending.extend((key, child))
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and (item.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", item)
                                       or _PRIVATE_TEXT.search(item) or _SECRET_TEXT.search(item)):
            raise ValueError("private material in native publication evidence")


def _evidence_refs(value: Any) -> None:
    """Provenance references never expose absolute or private campaign paths."""
    if not isinstance(value, dict):
        raise ValueError("native study evidence references must be an object")
    for item in value.values():
        if not isinstance(item, dict):
            raise ValueError("native study evidence reference requires path and SHA-256")
        path = Path(_identity(item.get("path")))
        _identity(item.get("sha256"), sha=True)
        if (path.is_absolute() or ".." in path.parts or not path.parts
                or any(part.startswith(".") for part in path.parts)
                or "\\" in str(path) or ":" in str(path)):
            raise ValueError("native study evidence paths must be public relative paths")
        if "bytes" in item:
            count(item["bytes"])


def _prediction_outputs(value: Any, family: str) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("native study completed records require retained outputs")
    for key, prediction in value.items():
        _identity(key)
        kind = prediction["type"]
        expected = _PROBE_TARGETS.get(family)
        if expected and kind != expected[0]:
            raise ValueError("native study output primitive differs from its dataset")
        if kind == "choice":
            _identity(prediction["value"])
        elif kind in {"noul", "score"}:
            upper = 1 if kind == "noul" else expected[1] - 1 if expected else None
            number(prediction["value"], upper=upper)
        else:
            raise ValueError("native study output has an unknown primitive")
        if prediction.get("confidence") is not None:
            number(prediction["confidence"], upper=1)
        probabilities = prediction.get("probabilities")
        if probabilities is not None:
            if not isinstance(probabilities, dict) or not probabilities:
                raise ValueError("native study output requires an explicit probability vocabulary")
            for option, probability in probabilities.items():
                _identity(option)
                number(probability, upper=1)
            if expected and expected[1] and len(probabilities) != expected[1]:
                raise ValueError("native study output lacks the complete dataset vocabulary")
            validate_probability_row(probabilities, rounding_digits=prediction.get("probability_rounding_digits"))
            if kind == "choice" and prediction["value"] not in probabilities:
                raise ValueError("native study output choice differs from the retained vocabulary")
        for field in ("probability_source", "probability_semantics", "confidence_semantics"):
            if prediction.get(field) is not None:
                _identity(prediction[field])


def validate_native_hosted_summary(value: Any) -> dict[str, Any]:
    """Validate the selected terminal cut without upgrading it to a quality study.

    Counts retain the complete plan. Billing totals reduce physical receipts
    exactly; a historical reviewed UNKNOWN remains distinct from reported cost.
    Later journal rows are outside the explicitly recorded cut.
    """
    if not isinstance(value, dict) or value.get("format") != NATIVE_HOSTED_FORMAT:
        raise ValueError("invalid selected native study summary format")
    _publication_privacy(value)
    _no_supplied_metrics(value)
    try:
        allowed_fields = {"format", "manifest_hash", "journal_hash", "inference_source_hash", "source_git_head",
                          "scope", "planned_cells", "denominators", "phase_counts", "datasets",
                          "actual_transport_attempts", "attempt_receipts", "capability_probes",
                          "completed_quality_predictions", "completed_warm_predictions", "accounting",
                          "historical_bounded_unknown", "evidence", "shared_accounting", "completed_graphical_workflows"}
        if set(value) - allowed_fields:
            raise ValueError("unknown native study summary fields")
        for field in ("manifest_hash", "journal_hash", "inference_source_hash"):
            _identity(value[field], sha=True)
        if not re.fullmatch(r"[a-f0-9]{40}", _identity(value["source_git_head"])):
            raise ValueError("native study requires an exact source Git identity")
        scope = value["scope"]
        if (set(scope) != {"through_phase", "cut_timestamp", "quality_claims", "maximum_boundaries_verified"}
                or scope["through_phase"] not in _PHASES or scope["quality_claims"] is not False
                or scope["maximum_boundaries_verified"] is not False):
            raise ValueError("native study scope cannot claim quality or maximum boundaries")
        cut = _timestamp(scope["cut_timestamp"])
        if set(value["denominators"]) != set(_STATUSES):
            raise ValueError("native study requires complete status denominators")
        totals = statuses(value, nested=True)
        phases = value["phase_counts"]
        if not isinstance(phases, dict) or set(phases) != set(_PHASES):
            raise ValueError("native study phase denominator mismatch")
        phase_totals = dict.fromkeys(_STATUSES, 0)
        for counts in phases.values():
            if not isinstance(counts, dict) or set(counts) != {"planned", *_STATUSES}:
                raise ValueError("native study requires complete phase denominators")
            phase_status = statuses({"planned_cells": counts["planned"], "denominators": counts}, nested=True)
            for key, n in phase_status.items():
                phase_totals[key] += n
        if phase_totals != totals:
            raise ValueError("native study phase/status denominator mismatch")
        for phase in _PHASES[_PHASES.index(scope["through_phase"]) + 1:]:
            if any(count(phases[phase][k]) for k in _STATUSES if k != "unattempted"):
                raise ValueError("native study phase statuses are outside the selected cut")
        datasets = value["datasets"]
        if not isinstance(datasets, list) or not datasets:
            raise ValueError("native study dataset inventory must be nonempty")
        dataset_ids: set[str] = set()
        for index, dataset in enumerate(datasets):
            if set(dataset) != {"index", "id", "name", "family"}:
                raise ValueError("native study dataset requires exact identity fields")
            if count(dataset["index"]) != index or _identity(dataset["id"]) in dataset_ids:
                raise ValueError("native study dataset indices and identities must be unique")
            dataset_ids.add(dataset["id"])
            _identity(dataset["name"])
            _identity(dataset["family"])

        wrappers = value["attempt_receipts"]
        if (not isinstance(wrappers, list)
                or count(value["actual_transport_attempts"]) != len(wrappers)):
            raise ValueError("native study attempt denominator mismatch")
        attempts: set[str] = set()
        unknown: set[str] = set()
        cell_bindings: dict[str, tuple[str, int]] = {}
        cell_timestamps: dict[str, datetime] = {}
        cell_attempts: dict[str, int] = {}
        successful: set[str] = set()
        with localcontext(currency_context()):
            reported = usd_total("0")
            for item in wrappers:
                if set(item) != {"cell_id", "phase", "dataset_index", "receipt"}:
                    raise ValueError("native study receipt wrapper requires exact identity fields")
                cell_id = _identity(item["cell_id"], sha=True)
                phase, index = item["phase"], count(item["dataset_index"])
                if phase not in phases or index >= len(datasets):
                    raise ValueError("native study receipt has unknown phase or dataset")
                if _PHASES.index(phase) > _PHASES.index(scope["through_phase"]):
                    raise ValueError("native study receipt is outside the selected phase cut")
                binding = (phase, index)
                if cell_id in cell_bindings and cell_bindings[cell_id] != binding:
                    raise ValueError("native study retry changed cell identity")
                cell_bindings[cell_id] = binding
                receipt = item["receipt"]
                if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
                    raise ValueError("native study receipt must match the complete CallReceipt schema")
                ident = _identity(receipt["attempt_id"])
                if ident in attempts:
                    raise ValueError("native study attempt identities must be unique")
                attempts.add(ident)
                cell_attempts[cell_id] = cell_attempts.get(cell_id, 0) + 1
                stamp = _timestamp(receipt["timestamp"])
                if stamp > cut:
                    raise ValueError("native study receipt falls after the selected cut")
                if cell_id in cell_timestamps and stamp < cell_timestamps[cell_id]:
                    raise ValueError("native study retry receipts must preserve attempt order")
                cell_timestamps[cell_id] = stamp
                _identity(receipt["request_hash"], sha=True)
                _identity(receipt["requested_model"])
                for field in ("resolved_model", "provider", "response_id", "error"):
                    if receipt[field] is not None:
                        _identity(receipt[field])
                endpoint = urlsplit(_identity(receipt["endpoint"]))
                if (endpoint.scheme != "https" or endpoint.netloc != "openrouter.ai"
                        or endpoint.path != "/api/alpha/decisions" or endpoint.query or endpoint.fragment):
                    raise ValueError("native hosted receipt requires the Decisions endpoint")
                number(receipt["elapsed_s"])
                for field in ("input_tokens", "output_tokens"):
                    if receipt[field] is not None:
                        count(receipt[field])
                status = receipt["status_code"]
                if status is not None and (type(status) is not int or not 100 <= status <= 599):
                    raise ValueError("invalid native study HTTP status")
                cost, cost_status = receipt["cost_usd"], receipt["cost_status"]
                if cost_status == "reported" and isinstance(cost, str):
                    reported += usd(cost)
                elif cost_status == "unknown" and cost is None:
                    unknown.add(ident)
                else:
                    raise ValueError("invalid native study billing provenance")
                diagnostic = receipt["response_diagnostics"]
                if diagnostic is not None:
                    if not isinstance(diagnostic, dict) or set(diagnostic) != _DIAGNOSTIC_FIELDS:
                        raise ValueError("native study diagnostic must match the complete SDK schema")
                    HTTPResponseDiagnostics(**diagnostic)
                successful.discard(cell_id)
                if status == 200 and receipt["error"] is None and cost_status == "reported":
                    for field in ("resolved_model", "provider", "response_id"):
                        _identity(receipt[field])
                    if receipt["input_tokens"] is None or receipt["output_tokens"] is None:
                        raise ValueError("successful native study receipts require usage")
                    if (diagnostic is None or diagnostic["body_complete"] is not True
                            or diagnostic["digest_scope"] != "complete_decoded_body"
                            or diagnostic["classification"] != "json_object"
                            or count(diagnostic["body_bytes_observed"]) > count(diagnostic["body_limit_bytes"])):
                        raise ValueError("successful native study requires complete response custody")
                    _identity(diagnostic["body_sha256"], sha=True)
                    successful.add(cell_id)
            accounting = value["accounting"]
            if set(accounting) != {"reported_cost_usd", "limit_usd", "reserved_usd", "unresolved_attempts", "admission_stopped"}:
                raise ValueError("native study requires the complete accounting schema")
            if any(not isinstance(accounting[k], str) for k in
                   ("reported_cost_usd", "limit_usd", "reserved_usd")):
                raise ValueError("native study currency requires exact decimal strings")
            if reported != usd_total(accounting["reported_cost_usd"]):
                raise ValueError("reported native study billing total mismatch")
            usd_total(accounting["limit_usd"])
            reserved = usd_total(accounting["reserved_usd"])
        unresolved = accounting["unresolved_attempts"]
        if (not isinstance(unresolved, list) or any(not isinstance(k, str) for k in unresolved)
                or len(unresolved) != len(set(unresolved)) or set(unresolved) != unknown
                or type(accounting["admission_stopped"]) is not bool
                or (unknown and accounting["admission_stopped"] is not True)):
            raise ValueError("unresolved native study billing requires stopped admission")
        if reserved and not unresolved:
            raise ValueError("native study reserved balance requires unresolved attempt identities")
        historical = value["historical_bounded_unknown"]
        if (set(historical) != {"original_attempt_ids", "held_upper_bound_usd", "charge_status"}
                or historical["charge_status"] != "UNKNOWN"):
            raise ValueError("historical native billing must retain UNKNOWN provenance")
        historical_ids = historical["original_attempt_ids"]
        if (not isinstance(historical_ids, list) or any(not isinstance(k, str) or not k for k in historical_ids)
                or len(historical_ids) != len(set(historical_ids)) or attempts.intersection(historical_ids)):
            raise ValueError("historical native billing must have separate unique attempt identities")
        if not isinstance(historical["held_upper_bound_usd"], str):
            raise ValueError("native study currency requires exact decimal strings")
        held = usd_total(historical["held_upper_bound_usd"])
        if not historical_ids and held:
            raise ValueError("historical native billing bound requires an original attempt")
        with localcontext(currency_context()):
            liability = reported + held + usd_total(accounting["reserved_usd"])
            if liability > usd_total(accounting["limit_usd"]) and not accounting["admission_stopped"]:
                raise ValueError("native study liability over the retained limit requires stopped admission")

        completed: set[str] = set()
        for phase, field in (("capability_probe", "capability_probes"),
                             ("quality", "completed_quality_predictions"),
                             ("warm_repeat", "completed_warm_predictions"),
                             ("graphical", "completed_graphical_workflows")):
            rows = value.get(field, []) if phase == "graphical" else value[field]
            if not isinstance(rows, list) or len(rows) > count(phases[phase]["planned"]):
                raise ValueError("native study completion/phase denominator mismatch")
            row_ids: set[str] = set()
            probe_datasets: set[int] = set()
            completed_before = len(completed)
            probe_status_counts = dict.fromkeys(_STATUSES, 0)
            for row in rows:
                ident = _identity(row["cell_id"], sha=True)
                index = count(row["dataset_index"])
                if ident in row_ids or ident in completed or index >= len(datasets):
                    raise ValueError("native study cell identities must be unique")
                row_ids.add(ident)
                _identity(row["example_id"])
                if phase == "capability_probe":
                    allowed_probe_fields = {"cell_id", "dataset_index", "example_id", "status", "evidence",
                                            "attempts", "backend", "dataset", "dataset_id", "prepared_dataset_sha256", "reason"}
                    if set(row) - allowed_probe_fields:
                        raise ValueError("unknown native probe fields")
                    if "attempts" in row and count(row["attempts"]) != cell_attempts.get(ident, 0):
                        raise ValueError("native probe physical attempt denominator mismatch")
                    if "dataset_id" in row and row["dataset_id"] != datasets[index]["id"]:
                        raise ValueError("native probe dataset identity mismatch")
                    if "dataset" in row and row["dataset"] != datasets[index]["name"]:
                        raise ValueError("native probe dataset family mismatch")
                    if "prepared_dataset_sha256" in row:
                        _identity(row["prepared_dataset_sha256"], sha=True)
                    if "backend" in row:
                        _identity(row["backend"])
                    if row.get("reason") is not None:
                        _identity(row["reason"])
                    probe_datasets.add(index)
                    if row["status"] not in _STATUSES or row["status"] == "unattempted":
                        raise ValueError("native probe requires an observed outcome")
                    evidence = row["evidence"]
                    if set(evidence) != {"scope", "maximum_boundaries_verified", "empirical_success",
                                         "state_sha256", "question_count", "primitives", "options_per_question"}:
                        raise ValueError("native probe requires the complete capability evidence schema")
                    probe_status_counts[row["status"]] += 1
                    if (evidence["scope"] != "selected_validation_fixture"
                            or evidence["maximum_boundaries_verified"] is not False
                            or evidence["empirical_success"] is not (row["status"] == "completed")):
                        raise ValueError("native probe scope/status mismatch")
                    _identity(evidence["state_sha256"], sha=True)
                    questions = count(evidence["question_count"])
                    primitives, options = evidence["primitives"], evidence["options_per_question"]
                    if (questions == 0 or not isinstance(primitives, list) or not primitives
                            or len(primitives) != len(set(primitives))
                            or set(primitives) - {"noul", "choice", "score"}
                            or not isinstance(options, dict) or len(options) > questions
                            or any(not isinstance(k, str) or not k or count(n) < 2 for k, n in options.items())
                            or ("noul" not in primitives and len(options) != questions)):
                        raise ValueError("native probe has invalid question/option vocabulary")
                    family = datasets[index]["family"]
                    expected = _PROBE_TARGETS.get(family)
                    if expected and (primitives != [expected[0]] or
                                     (set(options.values()) != {expected[1]} if expected[1] else bool(options))):
                        raise ValueError("native probe target vocabulary differs from the complete dataset")
                    if row["status"] != "completed":
                        continue
                elif phase != "graphical":
                    _prediction_outputs(row["predictions"], datasets[index]["family"])
                elif not isinstance(row["workflow"], dict) or not row["workflow"]:
                    raise ValueError("native study completed records require retained outputs")
                if cell_bindings.get(ident) != (phase, index) or ident not in successful:
                    raise ValueError("native study completion requires a matching successful receipt")
                if _PHASES.index(phase) > _PHASES.index(scope["through_phase"]):
                    raise ValueError("native study completion is outside the selected phase cut")
                completed.add(ident)
            if len(completed) - completed_before != count(phases[phase]["completed"]):
                raise ValueError("native study completed phase denominator mismatch")
            if phase == "capability_probe" and any(
                probe_status_counts[k] != count(phases[phase][k]) for k in _STATUSES if k != "unattempted"
            ):
                raise ValueError("native probe status denominator mismatch")
            if (phase == "capability_probe" and phases[phase]["planned"] == len(datasets)
                    and not phases[phase]["unattempted"] and probe_datasets != set(range(len(datasets)))):
                raise ValueError("native probes omit a dataset in the completed inventory")
        if len(completed) != totals["completed"]:
            raise ValueError("native study completed denominator mismatch")
        for phase in _PHASES:
            attempted = sum(binding[0] == phase for binding in cell_bindings.values())
            observed = count(phases[phase]["planned"]) - count(phases[phase]["unattempted"])
            if attempted > observed:
                raise ValueError("native study attempted cells exceed observed phase denominator")
        if "evidence" in value:
            _evidence_refs(value["evidence"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("incomplete selected native study summary") from exc
    return value


def selected_native_study(project_root: Path) -> tuple[dict[str, Any], str]:
    """Consume exactly the verified bytes of the explicitly selected native cut."""
    raw = selected_study_bytes(project_root, "native_hosted")
    return validate_native_hosted_summary(strict_json_loads(raw)), hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class StudyEvidence:
    cpu: dict[str, Any]
    hosted: dict[str, Any]
    hashes: dict[str, str]
    native_hosted: dict[str, Any] | None = None

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
        if self.native_hosted is not None:
            study = self.native_hosted
            values.update({
                "NATIVE_HOSTED_PLANNED": study["planned_cells"],
                "NATIVE_HOSTED_PROBES_COMPLETED": sum(r["status"] == "completed" for r in study["capability_probes"]),
                "NATIVE_HOSTED_ATTEMPTS": study["actual_transport_attempts"],
                "NATIVE_HOSTED_REPORTED_COST_USD": study["accounting"]["reported_cost_usd"],
                "NATIVE_HOSTED_QUALITY_COMPLETED": len(study["completed_quality_predictions"]),
                "NATIVE_HOSTED_WARM_COMPLETED": len(study["completed_warm_predictions"]),
                "NATIVE_HOSTED_UNATTEMPTED": study["denominators"]["unattempted"],
            })
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
    native_hosted = None
    if has_selected_study(project_root, "native_hosted"):
        native_hosted, hashes["native_hosted"] = selected_native_study(project_root)
    return StudyEvidence(cpu, hosted, hashes, native_hosted)
