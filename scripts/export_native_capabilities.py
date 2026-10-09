"""Export one hash-bound, terminal native capability cut without opening a run.

The journal is published byte for byte. Manifest/report projections are declared
documentary derivatives: neither projection can be used to resume inference.
No live journal/head, RunStore, allocation, credential or network is consulted.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import math
import re
import sys
from collections import Counter
from dataclasses import fields
from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from daf_jev._json import strict_json_loads  # noqa: E402
from daf_jev._types import validate_probability_row  # noqa: E402
from daf_jev.benchmark_runner import _input_bytes  # noqa: E402
from daf_jev.benchmark_store import currency_context, usd, usd_total  # noqa: E402
from daf_jev.decision_backends import (  # noqa: E402
    CallReceipt,
    DecisionPrediction,
    HTTPResponseDiagnostics,
    canonical_json,
    content_hash,
)

_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_MODEL = "typesafe/jev-1.13"
_STATUSES = ("completed", "failed", "unsupported", "unattempted", "unresolved")
_PHASES = ("capability_probe", "quality", "warm_repeat", "graphical")
_DIRECTORY_DISPLAY = "<SHARED_ALLOCATION_DIRECTORY>"
_PRIVATE = re.compile(r"/Users/|/home/|/private/|/tmp/|[A-Za-z]:[\\/]Users[\\/]", re.I)
_SECRET = re.compile(r"sk-or-|sk-[A-Za-z0-9]{12,}|Bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
_SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "proxy_authorization", "headers",
                   "request_headers", "response_headers", "access_token", "refresh_token", "password", "secret"}
_QUALITY_ESTIMATES = {"accuracy", "macro_f1", "ordinal_mae", "ordinal_rmse", "brier", "binary_brier", "log_loss",
                      "ece", "coverage", "selective_risk", "failure_rate", "out_of_scope_detection", "throughput_per_s",
                      "throughput_wall_s", "cost_per_decision_usd", "cost_per_correct_decision_usd",
                      "mean_pairwise_label_agreement", "mean_modal_share", "mean_distribution_pairwise_half_l1",
                      "precision", "recall", "f1", "specificity", "pairwise_label_agreement", "modal_share",
                      "distribution_mean_pairwise_half_l1", "distribution_max_pairwise_half_l1"}
_OBSERVED_COUNTS = {"n_attempted", "n_success", "n_errors", "n_abstained", "n_hard_targets", "n_probability_scores",
                    "n_infinite_log_loss", "n_missing_cost", "n_repeated_completed_observations",
                    "n_completed_warm_repeats", "n_estimable_label_groups", "n_estimable_distribution_groups", "evaluated",
                    "n_groups", "validation_groups", "unknown_distributions", "tp", "fp", "fn", "tn",
                    "n_valid_hard", "n_valid_oos", "n_failed_oos", "completed_observations", "label_observations",
                    "distribution_observations", "missing_distributions", "invalid_distributions", "unknown_probability_semantics"}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected a lowercase SHA-256 digest")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid evidence timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid evidence timestamp") from exc
    if stamp.tzinfo is None:
        raise ValueError("evidence timestamp must have a timezone")
    return stamp


def _number(value: Any, *, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite nonnegative number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("expected a finite nonnegative number") from exc
    if not math.isfinite(number) or number < 0 or (upper is not None and number > upper):
        raise ValueError("expected a finite nonnegative number within its declared range")
    return number


def _privacy(value: Any) -> None:
    """Refuse private material; API-key environment names/auth schemes are metadata."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise ValueError("private credential/header field in public evidence")
            _privacy(key)
            _privacy(item)
    elif isinstance(value, list):
        for item in value:
            _privacy(item)
    elif isinstance(value, str) and (_PRIVATE.search(value) or _SECRET.search(value)):
        raise ValueError("unrecognized private material in public evidence")


def _no_quality_claims(value: Any) -> None:
    """A rowless capability cut can retain planned counts and unavailable metrics."""
    if isinstance(value, list):
        for item in value:
            _no_quality_claims(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "out_of_scope_detection" and isinstance(item, dict):
                # Empty CLINC reductions retain class/planned metadata, zero
                # observed confusion counts and unavailable detection scores.
                _no_quality_claims(item)
                continue
            if key == "uncertainty":
                if not isinstance(item, dict) or any(
                    not isinstance(interval, dict) or interval.get("status") != "insufficient_groups"
                    or interval.get("low") is not None or interval.get("high") is not None
                    or type(interval.get("groups")) is not int or interval["groups"] != 0
                    for interval in item.values()
                ):
                    raise ValueError("capability cut cannot supply quality intervals")
                continue
            if key in _QUALITY_ESTIMATES and item is not None:
                raise ValueError("capability cut cannot supply quality/timing estimates")
            if key in _OBSERVED_COUNTS and (type(item) is not int or item != 0):
                raise ValueError("capability cut cannot supply observed quality/timing counts")
            if key in {"confusion", "reliability", "probability_row_sum_deviations", "label_counts"}:
                def empty_observations(data: Any) -> bool:
                    if isinstance(data, dict):
                        return all(empty_observations(x) for x in data.values())
                    return data == [] if isinstance(data, list) else type(data) is int and data == 0
                if not empty_observations(item):
                    raise ValueError("capability cut cannot supply quality/timing observations")
                continue
            if key == "latency":
                if (not isinstance(item, dict) or type(item.get("n")) is not int or item["n"] != 0
                        or any(item.get(k) is not None for k in ("mean_s", "p50_s", "p95_s", "p99_s"))):
                    raise ValueError("capability cut cannot supply quality/timing latency")
                continue
            if key in {"known_cost_usd", "total_cost_usd"} and usd_total(item) != 0:
                raise ValueError("capability cut cannot supply quality/timing billing")
            if key == "planned_coverage" and item is not None and _number(item) != 0:
                raise ValueError("capability cut has no completed quality/timing coverage")
            if key in {"threshold", "wilson_upper"} and item is not None:
                raise ValueError("capability cut cannot supply fitted policy estimates")
            if key == "primary_completed" and item is not False:
                raise ValueError("capability cut cannot supply completed repeatability observations")
            _no_quality_claims(item)


def _read(path: Path, expected: str) -> tuple[bytes, str]:
    _digest(expected)
    raw = _input_bytes(path)  # one identity-checked read; never a live RunStore
    if _hash(raw) != expected:
        raise ValueError("input SHA-256 mismatch")
    return raw, expected


def _manifest(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if manifest.get("format") != "dafjev.benchmark-run/1" or manifest.get("public_projection") is not None:
        raise ValueError("an original executable manifest is required")
    datasets, profiles, cells = (manifest.get(key) for key in ("datasets", "backends", "cells"))
    if not isinstance(datasets, list) or len(datasets) != 12 or not isinstance(profiles, list) or len(profiles) != 1:
        raise ValueError("this export requires twelve dataset configurations and one native profile")
    profile = profiles[0]
    if (not isinstance(profile, dict) or profile.get("model") != _MODEL or profile.get("endpoint") != _ENDPOINT
            or profile.get("mode") != "systemone" or profile.get("hosted") is not True
            or profile.get("kind") != "http" or set(profile.get("options", {})) != {"provider"}):
        raise ValueError("unsupported native profile")
    route = profile["options"]["provider"]
    if (not isinstance(route, dict) or route.get("only") != ["typesafe"]
            or route.get("allow_fallbacks") is not False or route.get("require_parameters") is not True):
        raise ValueError("native export requires the frozen TypeSafe-only route")
    _digest(manifest.get("config_sha256"))
    if not isinstance(cells, list) or not cells:
        raise ValueError("missing planned cells")
    inventory: dict[str, dict[str, Any]] = {}
    probe_indices = []
    for cell in cells:
        if (not isinstance(cell, dict) or cell.get("id") in inventory or cell.get("backend") != profile.get("id")
                or type(cell.get("dataset")) is not int or not 0 <= cell["dataset"] < 12
                or cell.get("phase") not in _PHASES or type(cell.get("repeat")) is not int or cell["repeat"] < 0
                or not isinstance(cell.get("example_id"), str) or not cell["example_id"]):
            raise ValueError("invalid frozen cell inventory")
        _digest(cell["id"])
        inventory[cell["id"]] = cell
        if cell["phase"] == "capability_probe":
            probe_indices.append(cell["dataset"])
    if sorted(probe_indices) != list(range(12)):
        raise ValueError("exactly one capability probe per dataset configuration is required")
    identifiers = []
    for dataset in datasets:
        if (not isinstance(dataset, dict) or not isinstance(dataset.get("manifest"), dict)
                or not isinstance(dataset.get("id"), str) or not dataset["id"]):
            raise ValueError("invalid frozen dataset identity")
        descriptor = dataset["manifest"]
        labels = descriptor.get("labels")
        if (not isinstance(descriptor.get("name"), str) or not descriptor["name"]
                or descriptor.get("label_kind") not in {"binary", "categorical", "ordinal", "soft"}
                or not isinstance(labels, list) or not labels or not all(isinstance(x, str) and x for x in labels)
                or len(set(labels)) != len(labels)):
            raise ValueError("invalid frozen dataset vocabulary")
        _digest(dataset.get("sha256"))
        identifiers.append(dataset["id"])
    if len(set(identifiers)) != 12:
        raise ValueError("dataset configuration identities must remain distinct")
    usd(manifest.get("budget_usd"))
    return inventory, profile


def _prediction(outcome: dict[str, Any], dataset: dict[str, Any], profile: dict[str, Any]) -> None:
    predictions, evidence = outcome.get("predictions"), outcome.get("capability_evidence")
    if not isinstance(predictions, dict) or set(predictions) != {"decision"} or not isinstance(evidence, dict):
        raise ValueError("missing typed selected-fixture result")
    if (evidence.get("scope") != "selected_validation_fixture" or evidence.get("empirical_success") is not True
            or evidence.get("maximum_boundaries_verified") is not False
            or type(evidence.get("question_count")) is not int or evidence["question_count"] != 1):
        raise ValueError("capability evidence may establish only selected-fixture success")
    _digest(evidence.get("state_sha256"))
    raw = predictions["decision"]
    if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(DecisionPrediction)}:
        raise ValueError("incomplete typed native prediction")
    try:
        prediction = DecisionPrediction(**raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid typed native prediction") from exc
    descriptor = dataset["manifest"]
    labels = descriptor["labels"]
    kind = {"binary": "noul", "categorical": "choice", "soft": "choice", "ordinal": "score"}[descriptor["label_kind"]]
    rounding = profile["capabilities"].get("probability_rounding_digits")
    if prediction.type != kind or prediction.probability_rounding_digits != rounding:
        raise ValueError("prediction primitive/precision differs from frozen profile")
    if prediction.confidence is not None:
        _number(prediction.confidence, upper=1)
    probabilities = prediction.probabilities
    expected_labels = {"false", "true"} if kind == "noul" else set(labels)
    if not isinstance(probabilities, dict) or set(probabilities) != expected_labels:
        raise ValueError("prediction must retain the complete option vocabulary")
    validate_probability_row(probabilities, rounding_digits=rounding)
    if evidence.get("primitives") != [kind] or evidence.get("options_per_question") != ({} if kind == "noul" else {"decision": len(labels)}):
        raise ValueError("capability evidence vocabulary differs from typed result")
    if kind == "choice":
        if not isinstance(prediction.value, str) or prediction.value not in labels or prediction.probability_source != "native":
            raise ValueError("invalid native Choice result")
    elif kind == "score":
        _number(prediction.value, upper=len(labels) - 1)
        if prediction.probability_source != "native":
            raise ValueError("invalid native Score provenance")
    else:
        value = _number(prediction.value, upper=1)
        if (prediction.probability_source != "native_binary_scalar" or prediction.confidence is not None
                or not math.isclose(probabilities["true"], value, abs_tol=1e-12)
                or not math.isclose(probabilities["false"], 1 - value, abs_tol=1e-12)):
            raise ValueError("invalid native binary scalar provenance")
    if prediction.confidence_semantics != profile["capabilities"].get("confidence_semantics"):
        raise ValueError("prediction confidence provenance differs from frozen profile")
    _number(outcome.get("elapsed_s"))
    if outcome.get("error") is not None or outcome.get("workflow") is not None:
        raise ValueError("a completed direct capability probe cannot carry errors/workflows")


def _receipt(raw: dict[str, Any], admission: dict[str, Any], cell_id: str) -> None:
    if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(CallReceipt)}:
        raise ValueError("incomplete physical attempt receipt")
    try:
        receipt = CallReceipt(**raw)
        if raw["response_diagnostics"] is not None:
            HTTPResponseDiagnostics(**raw["response_diagnostics"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid typed physical attempt receipt") from exc
    if (cell_id != admission["cell_id"] or receipt.attempt_id != admission["attempt_id"]
            or receipt.request_hash != admission["request_hash"] or receipt.requested_model != admission["model"]
            or receipt.endpoint != admission["endpoint"]):
        raise ValueError("receipt identity differs from admitted physical request")
    _digest(receipt.request_hash)
    _timestamp(receipt.timestamp)
    _number(receipt.elapsed_s)
    for value in (receipt.input_tokens, receipt.output_tokens):
        if type(value) is not int or value < 0:
            raise ValueError("physical receipts require nonnegative integer token counts")
    if type(receipt.status_code) is not int or not 100 <= receipt.status_code <= 599:
        raise ValueError("physical receipt requires its HTTP status")
    if receipt.cost_status == "reported":
        usd(receipt.cost_usd)
    elif receipt.cost_status != "unknown" or receipt.cost_usd is not None:
        raise ValueError("invalid hosted accounting provenance")
    if receipt.resolved_model is not None and (not isinstance(receipt.resolved_model, str) or not receipt.resolved_model):
        raise ValueError("invalid resolved model identity")
    if receipt.provider is not None and receipt.provider != "TypeSafe":
        raise ValueError("receipt provider differs from the frozen TypeSafe-only route")


def _prefix(raw: bytes, manifest: dict[str, Any], inventory: dict[str, dict[str, Any]],
            profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    if not raw or not raw.endswith(b"\n") or any(not line.strip() for line in raw.splitlines()):
        raise ValueError("journal cut must contain complete nonblank JSONL rows")
    events: list[dict[str, Any]] = []
    previous = content_hash(manifest)
    starts: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    cell_starts: set[str] = set()
    ready: set[int] = set()
    wrappers = []
    charged = Decimal(0)
    reserved: dict[str, Decimal] = {}
    stopped = False
    allowed = {"execution_started", "backend_ready", "cell_started", "attempt_started", "attempt_finished", "cell_finished", "execution_finished"}
    for line in raw.splitlines():
        event = strict_json_loads(line)
        if not isinstance(event, dict):
            raise ValueError("journal row must be an object")
        digest = _digest(event.get("hash"))
        unsigned = {key: value for key, value in event.items() if key != "hash"}
        if type(event.get("sequence")) is not int or event["sequence"] != len(events) + 1 or event.get("previous") != previous or content_hash(unsigned) != digest:
            raise ValueError("journal cut hash/sequence mismatch")
        stamp = _timestamp(event.get("timestamp"))
        if events and stamp < _timestamp(events[-1]["timestamp"]):
            raise ValueError("journal timestamps must preserve the recorded terminal cut")
        previous = digest
        name = event.get("event")
        if name not in allowed:
            raise ValueError("unsupported event in capability-only journal cut")
        if name == "execution_started":
            if events or event.get("through_phase") != "capability_probe" or event.get("unresolved_cells") != []:
                raise ValueError("cut must begin with one clean capability-only execution")
        elif not events or events[0]["event"] != "execution_started" or events[-1]["event"] == "execution_finished":
            raise ValueError("invalid terminal execution cut")
        if name == "backend_ready":
            index = event.get("dataset")
            if (type(index) is not int or not 0 <= index < 12 or index in ready
                    or event.get("backend") != profile["id"] or event.get("training") is not None
                    or event.get("profile") != profile.get("artifact")):
                raise ValueError("backend setup differs from frozen native profile")
            _number(event.get("setup_elapsed_s"))
            ready.add(index)
        if name in {"cell_started", "attempt_started", "attempt_finished", "cell_finished"}:
            cell_id = event.get("cell_id")
            if not isinstance(cell_id, str):
                raise ValueError("invalid journal cell identity")
            cell = inventory.get(cell_id)
            if cell is None or cell["phase"] != "capability_probe":
                raise ValueError("journal cut attempted a non-capability or unknown cell")
            if name == "cell_started":
                if cell_id in cell_starts or cell["dataset"] not in ready:
                    raise ValueError("duplicate or unprepared capability cell")
                cell_starts.add(cell_id)
            elif cell_id not in cell_starts or cell_id in outcomes:
                raise ValueError("attempt/outcome must follow an unfinished cell start")
            if name == "attempt_started":
                attempt = event.get("attempt_id")
                if (not isinstance(attempt, str) or not attempt or attempt in starts or event.get("hosted") is not True
                        or event.get("model") != _MODEL or event.get("endpoint") != _ENDPOINT):
                    raise ValueError("invalid native physical admission")
                _digest(event.get("request_hash"))
                bound = usd(event.get("liability_usd"))
                if bound != usd(profile.get("liability_usd")) or stopped:
                    raise ValueError("admission differs from frozen liability or follows accounting stop")
                with localcontext(currency_context()):
                    if charged + sum(reserved.values(), Decimal(0)) + bound > usd(manifest["budget_usd"]):
                        raise ValueError("physical admission exceeded the frozen allowance")
                starts[attempt] = event
                reserved[attempt] = bound
            elif name == "attempt_finished":
                receipt = event.get("receipt")
                if not isinstance(receipt, dict) or receipt.get("attempt_id") not in starts or receipt["attempt_id"] in receipts:
                    raise ValueError("receipt has no unique matching admission")
                attempt = receipt["attempt_id"]
                _receipt(receipt, starts[attempt], cell_id)
                if not _timestamp(starts[attempt]["timestamp"]) <= _timestamp(receipt["timestamp"]) <= stamp:
                    raise ValueError("receipt timestamp is outside its admitted/finished journal interval")
                receipts[attempt] = receipt
                if receipt["cost_status"] == "reported":
                    cost = usd(receipt["cost_usd"])
                    with localcontext(currency_context()):
                        charged += cost
                    stopped |= cost > reserved.pop(attempt) or charged > usd(manifest["budget_usd"])
                else:
                    stopped = True
                wrappers.append({"cell_id": cell_id, "phase": cell["phase"], "dataset_index": cell["dataset"], "receipt": receipt})
            elif name == "cell_finished":
                physical = [receipt for attempt, receipt in receipts.items() if starts[attempt]["cell_id"] == cell_id]
                if (event.get("status") != "completed" or not physical
                        or any(a not in receipts for a, start in starts.items() if start["cell_id"] == cell_id)):
                    raise ValueError("each selected probe needs completed typed output and finished physical receipts")
                last = physical[-1]
                diagnostics = last.get("response_diagnostics")
                if (last["status_code"] != 200 or last["error"] is not None or not last.get("response_id")
                        or last.get("provider") != "TypeSafe" or not last.get("resolved_model")
                        or not isinstance(diagnostics, dict) or diagnostics.get("body_complete") is not True
                        or diagnostics.get("classification") != "json_object"):
                    raise ValueError("successful native probe lacks a successful complete physical receipt")
                _prediction(event, manifest["datasets"][cell["dataset"]], profile)
                outcomes[cell_id] = event
        events.append(event)
    if (events[-1]["event"] != "execution_finished" or events[-1].get("unavailable_backends") != []
            or len(outcomes) != 12 or len(ready) != 12 or set(starts) != set(receipts)):
        raise ValueError("cut must end after all twelve completed capability probes")
    with localcontext(currency_context()):
        accounting = {"limit_usd": manifest["budget_usd"], "reported_cost_usd": str(charged),
                      "reserved_usd": str(sum(reserved.values(), Decimal(0))),
                      "unresolved_attempts": sorted(reserved), "admission_stopped": stopped}
    _accounting(events[-1].get("accounting"), accounting)
    return events, wrappers, outcomes, accounting


def _accounting(actual: Any, expected: dict[str, Any]) -> None:
    if not isinstance(actual, dict) or set(actual) != set(expected):
        raise ValueError("invalid per-run accounting snapshot")
    for key in ("limit_usd", "reported_cost_usd", "reserved_usd"):
        if not isinstance(actual[key], str) or usd_total(actual[key]) != usd_total(expected[key]):
            raise ValueError("accounting conflicts with retained physical receipts")
    if actual["unresolved_attempts"] != expected["unresolved_attempts"] or actual["admission_stopped"] is not expected["admission_stopped"]:
        raise ValueError("accounting unresolved/stopped state conflicts with physical receipts")


def _report(report: dict[str, Any], manifest: dict[str, Any], events: list[dict[str, Any]],
            wrappers: list[dict[str, Any]], outcomes: dict[str, dict[str, Any]], accounting: dict[str, Any]) -> dict[str, Any]:
    if (report.get("format") != "dafjev.benchmark-report/1" or report.get("public_projection") is not None
            or report.get("manifest_hash") != content_hash(manifest) or report.get("journal_hash") != events[-1]["hash"]
            or report.get("execution_phase_boundary") != "capability_probe"
            or canonical_json(report.get("inference_source")) != canonical_json(manifest.get("source"))):
        raise ValueError("report does not bind the original manifest and terminal capability cut")
    source = manifest.get("source")
    if (not isinstance(source, dict) or not isinstance(source.get("files"), dict) or not source["files"]
            or not isinstance(source.get("git_head"), str) or re.fullmatch(r"[0-9a-f]{40}", source["git_head"]) is None
            or report.get("inference_source_hash") != content_hash(source["files"])):
        raise ValueError("missing or inconsistent frozen inference source identity")
    for digest in source["files"].values():
        _digest(digest)
    _accounting(report.get("accounting"), accounting)
    expected_cells = [{**cell, "status": "completed" if cell["id"] in outcomes else "unattempted",
                       "reason": None if cell["id"] in outcomes else "execution_phase_boundary"} for cell in manifest["cells"]]
    denominators = dict(Counter(cell["status"] for cell in expected_cells))
    if (canonical_json(report.get("cells")) != canonical_json(expected_cells) or report.get("planned_cells") != len(expected_cells)
            or type(report.get("planned_cells")) is not int or canonical_json(report.get("denominators")) != canonical_json(denominators)
            or report.get("status") != ("partial" if denominators.get("unattempted") else "complete")):
        raise ValueError("report denominators/cell outcomes differ from the retained prefix")
    expected_probes = []
    for cell in manifest["cells"]:
        if cell["phase"] != "capability_probe":
            continue
        dataset = manifest["datasets"][cell["dataset"]]
        expected_probes.append({"backend": cell["backend"], "dataset": dataset["manifest"]["name"],
            "dataset_id": dataset["id"], "dataset_index": cell["dataset"], "prepared_dataset_sha256": dataset["sha256"],
            "cell_id": cell["id"], "example_id": cell["example_id"], "status": "completed", "reason": None,
            "evidence": outcomes[cell["id"]]["capability_evidence"],
            "attempts": sum(item["cell_id"] == cell["id"] for item in wrappers)})
    if canonical_json(report.get("capability_probes")) != canonical_json(expected_probes):
        raise ValueError("report capability evidence differs from retained typed results/receipts")
    if any(cohort.get("rows") for cohort in report.get("cohorts", [])):
        raise ValueError("capability report contains quality/timing observations")
    for key in ("cohorts", "policies", "repeatability", "gate_evidence"):
        _no_quality_claims(report.get(key, []))
    shared, binding = report.get("shared_accounting"), manifest.get("shared_allocation")
    if (not isinstance(shared, dict) or shared.get("status") != "observed" or not isinstance(binding, dict)
            or shared.get("binding") != binding or not isinstance(shared.get("snapshot"), dict)):
        raise ValueError("shared accounting must retain the frozen original allocation binding")
    snapshot = shared["snapshot"]
    if any(snapshot.get(key) != binding.get(key) for key in ("allocation_id", "manifest_hash")):
        raise ValueError("shared allocation identity differs from manifest")
    for key in ("limit_usd", "reported_cost_usd", "externally_verified_cost_usd", "effective_cost_usd", "reserved_usd", "held_upper_bound_usd", "total_liability_usd"):
        if not isinstance(snapshot.get(key), str):
            raise ValueError("shared accounting currency must retain recorded decimal strings")
        usd_total(snapshot[key])
    if usd_total(snapshot["limit_usd"]) != usd_total(accounting["limit_usd"]):
        raise ValueError("shared and per-run allowance differ")
    with localcontext(currency_context()):
        effective = usd_total(snapshot["reported_cost_usd"]) + usd_total(snapshot["externally_verified_cost_usd"])
        if effective != usd_total(snapshot["effective_cost_usd"]):
            raise ValueError("shared reported/external components do not conserve the effective cost")
        liability = sum((usd_total(snapshot[key]) for key in ("effective_cost_usd", "reserved_usd", "held_upper_bound_usd")), Decimal(0))
        if liability != usd_total(snapshot["total_liability_usd"]):
            raise ValueError("shared allocation liability components do not conserve the retained total")
    histories = {}
    for key in ("unknown_attempts", "historical_unknown_attempts", "bounded_unknown_attempts", "historical_bounded_unknown_attempts"):
        values = snapshot.get(key)
        if not isinstance(values, list) or not all(isinstance(x, str) and x for x in values) or len(set(values)) != len(values):
            raise ValueError("invalid historical UNKNOWN identity inventory")
        histories[key] = set(values)
    historical = histories["historical_bounded_unknown_attempts"]
    if not historical <= histories["unknown_attempts"] & histories["historical_unknown_attempts"] or not histories["bounded_unknown_attempts"] <= historical:
        raise ValueError("historical bounded charge status is no longer UNKNOWN")
    return {"original_attempt_ids": snapshot["historical_bounded_unknown_attempts"],
            "held_upper_bound_usd": snapshot["held_upper_bound_usd"], "charge_status": "UNKNOWN"}


def export(manifest_path: Path, journal_path: Path, report_path: Path, out: Path, *,
           manifest_sha256: str, journal_sha256: str, report_sha256: str) -> Path:
    """Validate all supplied bytes and public projections before creating output."""
    out = out.absolute()
    if out.exists() or ".." in out.parts or any(path.is_symlink() for path in [out, *out.parents]):
        raise ValueError("output directory must be fresh, canonical and nonsymlink")
    original_manifest, _ = _read(manifest_path, manifest_sha256)
    original_journal, _ = _read(journal_path, journal_sha256)
    original_report, _ = _read(report_path, report_sha256)
    manifest, report = strict_json_loads(original_manifest), strict_json_loads(original_report)
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        raise ValueError("original manifest/report must be JSON objects")
    inventory, profile = _manifest(manifest)
    events, wrappers, outcomes, accounting = _prefix(original_journal, manifest, inventory, profile)
    historical = _report(report, manifest, events, wrappers, outcomes, accounting)
    # Scan both decoded content and literal bytes: no escaped private strings can pass.
    for event in events:
        _privacy(event)
    _privacy(original_journal.decode("utf-8"))
    directory = manifest["shared_allocation"].get("directory")
    if not isinstance(directory, str) or not Path(directory).is_absolute() or ".." in Path(directory).parts:
        raise ValueError("invalid original shared-allocation directory")
    projected_manifest = copy.deepcopy(manifest)
    projected_manifest.pop("lock_identities", None)
    projected_manifest["shared_allocation"].pop("directory")
    projected_manifest["public_projection"] = {
        "format": "dafjev.documentary-manifest-projection/1", "executable": False,
        "original_manifest_sha256": manifest_sha256, "original_manifest_hash": content_hash(manifest),
        "transformations": ["remove shared_allocation.directory", "remove physical lock_identities"],
        "scope": "full frozen plan, documentary only; no RunStore/resume acceptance; original bytes are retained privately",
    }
    projected_report = copy.deepcopy(report)
    projected_report["shared_accounting"]["binding"]["directory"] = _DIRECTORY_DISPLAY
    projected_report["public_projection"] = {
        "format": "dafjev.documentary-report-projection/1", "original_report_sha256": report_sha256,
        "transformations": ["substitute only shared_accounting.binding.directory display"],
        "scope": "offline derivative of one retained capability-only cut; shared accounting is the report-time snapshot",
    }
    phase_counts = {phase: {"planned": 0, **dict.fromkeys(_STATUSES, 0)} for phase in _PHASES}
    for cell in report["cells"]:
        phase_counts[cell["phase"]]["planned"] += 1
        phase_counts[cell["phase"]][cell["status"]] += 1
    payloads = {"manifest-public.json": (canonical_json(projected_manifest) + "\n").encode(),
                "capability-prefix.jsonl": original_journal,
                "report-public.json": (canonical_json(projected_report) + "\n").encode()}
    evidence = {name: {"path": filename, "sha256": _hash(payloads[filename]), "bytes": len(payloads[filename])}
                for name, filename in (("manifest", "manifest-public.json"), ("journal", "capability-prefix.jsonl"), ("report", "report-public.json"))}
    evidence["manifest"].update({"original_sha256": manifest_sha256, "original_content_hash": content_hash(manifest), "derivative": True, "executable": False})
    evidence["journal"].update({"original_sha256": journal_sha256, "byte_identical": True, "terminal_sequence": len(events)})
    evidence["report"].update({"original_sha256": report_sha256, "derivative": True})
    summary = {
        "format": "dafjev.native-hosted-study-summary/1", "manifest_hash": content_hash(manifest),
        "journal_hash": events[-1]["hash"], "inference_source_hash": report["inference_source_hash"],
        "source_git_head": manifest["source"]["git_head"],
        "scope": {"through_phase": "capability_probe", "cut_timestamp": events[-1]["timestamp"],
                  "maximum_boundaries_verified": False, "quality_claims": False},
        "planned_cells": report["planned_cells"],
        "denominators": {status: report["denominators"].get(status, 0) for status in _STATUSES}, "phase_counts": phase_counts,
        "datasets": [{"index": index, "id": dataset["id"], "name": dataset["manifest"]["name"],
                      "family": dataset["manifest"]["name"]} for index, dataset in enumerate(manifest["datasets"])],
        "actual_transport_attempts": len(wrappers), "attempt_receipts": wrappers,
        "capability_probes": report["capability_probes"], "completed_quality_predictions": [], "completed_warm_predictions": [],
        "accounting": report["accounting"], "historical_bounded_unknown": historical,
        "shared_accounting": projected_report["shared_accounting"], "evidence": evidence,
    }
    payloads["summary.json"] = (canonical_json(summary) + "\n").encode()
    closure = {"format": "dafjev.native-capability-publication-evidence/1",
        "scope": "offline export only; no inference, publication or executable-manifest acceptance",
        "original_inputs": {"manifest_sha256": manifest_sha256, "journal_sha256": journal_sha256, "report_sha256": report_sha256},
        "files": {name: {"sha256": _hash(raw), "bytes": len(raw)} for name, raw in payloads.items()}}
    payloads["publication-evidence.json"] = (canonical_json(closure) + "\n").encode()
    for filename, raw in payloads.items():
        _privacy(raw.decode("utf-8"))
        if filename != "capability-prefix.jsonl":
            _privacy(strict_json_loads(raw))
    # Every check precedes the first output write. mkdir/open are exclusive.
    out.mkdir(parents=True, exist_ok=False)
    for filename, raw in payloads.items():
        with (out / filename).open("xb") as handle:
            handle.write(raw)
    return out / "summary.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("manifest", "journal-prefix", "report", "out-dir"):
        parser.add_argument("--" + option, required=True, type=Path)
    for option in ("manifest-sha256", "journal-sha256", "report-sha256"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args(argv)
    try:
        result = export(args.manifest, args.journal_prefix, args.report, args.out_dir,
                        manifest_sha256=args.manifest_sha256, journal_sha256=args.journal_sha256, report_sha256=args.report_sha256)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Do not echo private exception values/pathnames supplied as inputs.
        print("Capability export refused: " + type(exc).__name__, file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
