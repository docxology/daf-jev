"""Offline native capability publication: synthetic journal/currency adversaries."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest

from daf_jev.decision_backends import (
    CallReceipt,
    DecisionPrediction,
    HTTPResponseDiagnostics,
    canonical_json,
    content_hash,
)

_PATH = Path(__file__).resolve().parents[2] / "scripts/export_native_capabilities.py"
_SPEC = importlib.util.spec_from_file_location("native_capability_export", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_EXPORTER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORTER)
_STAMP = "2026-10-09T18:00:00+00:00"


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _save(bundle: dict[str, Any], *, bind: bool = True) -> None:
    manifest, events, report = (bundle[key] for key in ("manifest", "events", "report"))
    previous = content_hash(manifest)
    for sequence, event in enumerate(events, 1):
        event.pop("hash", None)
        event.update(sequence=sequence, previous=previous)
        event["hash"] = previous = content_hash(event)
    if bind:
        report.update(
            manifest_hash=content_hash(manifest),
            journal_hash=previous,
            inference_source=copy.deepcopy(manifest["source"]),
            inference_source_hash=content_hash(manifest["source"]["files"]),
        )
    bundle["paths"][0].write_text(canonical_json(manifest) + "\n")
    bundle["paths"][1].write_text(
        "".join(canonical_json(event) + "\n" for event in events)
    )
    bundle["paths"][2].write_text(canonical_json(report) + "\n")


@pytest.fixture()
def bundle(tmp_path: Path) -> dict[str, Any]:
    """Twelve selected fixtures; 77/151/five options are never abbreviated."""
    profile: dict[str, Any] = {
        "id": "native",
        "model": "typesafe/jev-1.13",
        "kind": "http",
        "hosted": True,
        "mode": "systemone",
        "endpoint": "https://openrouter.ai/api/alpha/decisions",
        "api_key_env": "OPENROUTER_API_KEY",
        "liability_usd": "0.001344000",
        "capabilities": {
            "probability_rounding_digits": 2,
            "confidence_semantics": "provider_defined",
            "authentication": "bearer",
        },
        "artifact": {"provider": "TypeSafe"},
        "options": {
            "provider": {
                "only": ["typesafe"],
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        },
    }
    datasets: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for index in range(12):
        kind = "binary" if index == 3 else ("ordinal" if index == 2 else "categorical")
        count = (
            77
            if index in {0, 8, 9, 10, 11}
            else (151 if index == 1 else (5 if index == 2 else 2))
        )
        labels = [str(i) for i in range(count)]
        name = (
            "banking77"
            if count == 77
            else ("clinc150" if count == 151 else "synthetic-fixture")
        )
        datasets.append(
            {
                "id": f"configuration-{index}",
                "sha256": content_hash(index),
                "manifest": {"name": name, "label_kind": kind, "labels": labels},
            }
        )
        for phase in ("capability_probe", "quality", "warm_repeat"):
            cells.append(
                {
                    "id": content_hash([index, phase]),
                    "phase": phase,
                    "backend": "native",
                    "dataset": index,
                    "example_id": f"example-{index}",
                    "repeat": 0,
                }
            )
    cells.append(
        {
            "id": content_hash("graphical"),
            "phase": "graphical",
            "backend": "native",
            "dataset": 0,
            "example_id": "example-0",
            "repeat": 0,
        }
    )
    allocation = {
        "allocation_id": "allowance",
        "manifest_hash": "b" * 64,
        "directory": "/Users/private/retained/allocation",
    }
    manifest = {
        "format": "dafjev.benchmark-run/1",
        "config_sha256": "d" * 64,
        "budget_usd": "25",
        "backends": [profile],
        "datasets": datasets,
        "cells": cells,
        "shared_allocation": allocation,
        "source": {"git_head": "a" * 40, "files": {"src/daf_jev/fixture.py": "c" * 64}},
        "lock_identities": {".journal.lock": [1, 2], ".run.lock": [1, 3]},
    }
    events: list[dict[str, Any]] = [
        {
            "event": "execution_started",
            "timestamp": _STAMP,
            "through_phase": "capability_probe",
            "unresolved_cells": [],
        }
    ]
    probes = []
    for cell in cells:
        if cell["phase"] != "capability_probe":
            continue
        index = cell["dataset"]
        dataset = datasets[index]
        descriptor = dataset["manifest"]
        kind = {"binary": "noul", "ordinal": "score", "categorical": "choice"}[
            descriptor["label_kind"]
        ]
        probabilities = (
            {"false": 0.25, "true": 0.75}
            if kind == "noul"
            else dict.fromkeys(
                descriptor["labels"], round(1 / len(descriptor["labels"]), 2)
            )
        )
        prediction = DecisionPrediction(
            kind,
            0.75 if kind == "noul" else (2.2 if kind == "score" else "0"),
            probabilities,
            None if kind == "noul" else 0.7,
            "native_binary_scalar" if kind == "noul" else "native",
            "provider_defined",
            2,
            None,
        )
        evidence = {
            "scope": "selected_validation_fixture",
            "empirical_success": True,
            "maximum_boundaries_verified": False,
            "question_count": 1,
            "primitives": [kind],
            "options_per_question": {}
            if kind == "noul"
            else {"decision": len(descriptor["labels"])},
            "state_sha256": content_hash(["state", index]),
        }
        diagnostics = HTTPResponseDiagnostics(
            content_hash(index),
            123,
            True,
            "complete_decoded_body",
            "application/json",
            "json_object",
        )
        receipt = CallReceipt(
            f"attempt-{index}",
            _STAMP,
            profile["endpoint"],
            profile["model"],
            "typesafe/jev-1.13-20260917",
            "TypeSafe",
            f"response-{index}",
            content_hash(["request", index]),
            0.1,
            200,
            1000,
            10,
            "0.000042000",
            "reported",
            None,
            diagnostics,
        )
        events.extend(
            [
                {
                    "event": "backend_ready",
                    "timestamp": _STAMP,
                    "backend": "native",
                    "dataset": index,
                    "profile": profile["artifact"],
                    "training": None,
                    "setup_elapsed_s": 0.01,
                },
                {"event": "cell_started", "timestamp": _STAMP, "cell_id": cell["id"]},
                {
                    "event": "attempt_started",
                    "timestamp": _STAMP,
                    "cell_id": cell["id"],
                    "attempt_id": receipt.attempt_id,
                    "request_hash": receipt.request_hash,
                    "model": receipt.requested_model,
                    "endpoint": receipt.endpoint,
                    "hosted": True,
                    "liability_usd": profile["liability_usd"],
                },
                {
                    "event": "attempt_finished",
                    "timestamp": _STAMP,
                    "cell_id": cell["id"],
                    "receipt": receipt.to_dict(),
                },
                {
                    "event": "cell_finished",
                    "timestamp": _STAMP,
                    "cell_id": cell["id"],
                    "status": "completed",
                    "error": None,
                    "elapsed_s": 0.2,
                    "predictions": {"decision": asdict(prediction)},
                    "capability_evidence": evidence,
                    "workflow": None,
                },
            ]
        )
        probes.append(
            {
                "backend": "native",
                "dataset": descriptor["name"],
                "dataset_id": dataset["id"],
                "dataset_index": index,
                "prepared_dataset_sha256": dataset["sha256"],
                "cell_id": cell["id"],
                "example_id": cell["example_id"],
                "status": "completed",
                "reason": None,
                "evidence": copy.deepcopy(evidence),
                "attempts": 1,
            }
        )
    accounting = {
        "limit_usd": "25",
        "reported_cost_usd": "0.000504000",
        "reserved_usd": "0",
        "unresolved_attempts": [],
        "admission_stopped": False,
    }
    events.append(
        {
            "event": "execution_finished",
            "timestamp": _STAMP,
            "accounting": copy.deepcopy(accounting),
            "unavailable_backends": [],
        }
    )
    reported_cells = [
        {
            **cell,
            "status": "completed"
            if cell["phase"] == "capability_probe"
            else "unattempted",
            "reason": None
            if cell["phase"] == "capability_probe"
            else "execution_phase_boundary",
        }
        for cell in cells
    ]
    shared = {
        "allocation_id": "allowance",
        "manifest_hash": "b" * 64,
        "limit_usd": "25",
        "reported_cost_usd": "0.000504000",
        "externally_verified_cost_usd": "0",
        "effective_cost_usd": "0.000504000",
        "reserved_usd": "0",
        "held_upper_bound_usd": "0.001344000",
        "total_liability_usd": "0.001848000",
        "unknown_attempts": ["historical-unknown"],
        "historical_unknown_attempts": ["historical-unknown"],
        "bounded_unknown_attempts": ["historical-unknown"],
        "historical_bounded_unknown_attempts": ["historical-unknown"],
    }
    report = {
        "format": "dafjev.benchmark-report/1",
        "planned_cells": len(cells),
        "cells": reported_cells,
        "denominators": dict(Counter(cell["status"] for cell in reported_cells)),
        "status": "partial",
        "execution_phase_boundary": "capability_probe",
        "capability_probes": probes,
        "accounting": accounting,
        "cohorts": [{"rows": []}],
        "shared_accounting": {
            "status": "observed",
            "binding": copy.deepcopy(allocation),
            "snapshot": shared,
            "scope": "report-time current allocation; not inference-time billing",
        },
    }
    result = {
        "manifest": manifest,
        "events": events,
        "report": report,
        "paths": [
            tmp_path / name for name in ("manifest.json", "prefix.jsonl", "report.json")
        ],
        "out": tmp_path / "public",
    }
    _save(result)
    return result


def _export(bundle: dict[str, Any], **overrides: Any) -> Path:
    manifest, journal, report = bundle["paths"]
    arguments = {
        "manifest_sha256": _hash(manifest.read_bytes()),
        "journal_sha256": _hash(journal.read_bytes()),
        "report_sha256": _hash(report.read_bytes()),
    }
    arguments.update(overrides)
    return _EXPORTER.export(manifest, journal, report, bundle["out"], **arguments)


def _refuse(bundle: dict[str, Any], *, save: bool = True) -> None:
    if save:
        _save(bundle)
    before = {path: path.read_bytes() for path in bundle["paths"]}
    with pytest.raises((ValueError, TypeError, KeyError)):
        _export(bundle)
    assert not bundle["out"].exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_export_preserves_prefix_and_all_provenance_without_runstore_or_network(
    bundle, monkeypatch
):
    reads = []
    original_reader = _EXPORTER._input_bytes

    def read_once(path):
        reads.append(path)
        return original_reader(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("offline exporter must not open RunStore or transport")

    monkeypatch.setattr(_EXPORTER, "_input_bytes", read_once)
    monkeypatch.setattr("daf_jev.benchmark_runner.RunStore", forbidden)
    monkeypatch.setattr("httpx.Client", forbidden)
    monkeypatch.setattr("httpx.AsyncClient", forbidden)
    before = {path: path.read_bytes() for path in bundle["paths"]}
    result = _export(bundle)
    assert reads == bundle["paths"]
    summary = json.loads(result.read_bytes())
    assert summary["scope"] == {
        "through_phase": "capability_probe",
        "cut_timestamp": _STAMP,
        "maximum_boundaries_verified": False,
        "quality_claims": False,
    }
    assert summary["denominators"] == {"completed": 12, "failed": 0, "unsupported": 0, "unattempted": 25, "unresolved": 0}
    assert summary["actual_transport_attempts"] == 12
    assert (
        summary["completed_quality_predictions"]
        == summary["completed_warm_predictions"]
        == []
    )
    assert summary["accounting"] == bundle["report"]["accounting"]
    assert summary["historical_bounded_unknown"] == {
        "original_attempt_ids": ["historical-unknown"],
        "held_upper_bound_usd": "0.001344000",
        "charge_status": "UNKNOWN",
    }
    assert summary["datasets"][0] == {
        "index": 0,
        "id": "configuration-0",
        "name": "banking77",
        "family": "banking77",
    }
    assert [item["dataset_index"] for item in summary["attempt_receipts"]] == list(
        range(12)
    )
    assert summary["phase_counts"]["quality"]["unattempted"] == 12
    assert summary["phase_counts"]["quality"]["completed"] == 0
    assert (bundle["out"] / "capability-prefix.jsonl").read_bytes() == before[
        bundle["paths"][1]
    ]
    manifest = json.loads((bundle["out"] / "manifest-public.json").read_bytes())
    declaration = manifest.pop("public_projection")
    expected_manifest = copy.deepcopy(bundle["manifest"])
    expected_manifest.pop("lock_identities")
    expected_manifest["shared_allocation"].pop("directory")
    assert manifest == expected_manifest and declaration["executable"] is False
    assert declaration["original_manifest_sha256"] == _hash(before[bundle["paths"][0]])
    assert declaration["original_manifest_hash"] == content_hash(bundle["manifest"])
    report = json.loads((bundle["out"] / "report-public.json").read_bytes())
    report_declaration = report.pop("public_projection")
    expected_report = copy.deepcopy(bundle["report"])
    expected_report["shared_accounting"]["binding"]["directory"] = (
        "<SHARED_ALLOCATION_DIRECTORY>"
    )
    assert report == expected_report and report_declaration[
        "original_report_sha256"
    ] == _hash(before[bundle["paths"][2]])
    closure = json.loads((bundle["out"] / "publication-evidence.json").read_bytes())
    for name, ref in closure["files"].items():
        raw = (bundle["out"] / name).read_bytes()
        assert ref == {"sha256": _hash(raw), "bytes": len(raw)}
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize(
    "argument", ["manifest_sha256", "journal_sha256", "report_sha256"]
)
def test_explicit_sha_mismatch_refuses_before_output(bundle, argument):
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _export(bundle, **{argument: "0" * 64})
    assert not bundle["out"].exists()


@pytest.mark.parametrize("digest", ["", "x" * 64, "A" * 64, False, 123])
def test_invalid_expected_digest_refuses_before_consumption(
    bundle, digest, monkeypatch
):
    monkeypatch.setattr(
        _EXPORTER, "_input_bytes", lambda path: pytest.fail("must reject digest first")
    )
    with pytest.raises(ValueError, match="SHA-256"):
        _export(bundle, manifest_sha256=digest)
    assert not bundle["out"].exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "terminal_missing",
        "extra_after_terminal",
        "quality_cut",
        "unknown_event",
        "missing_probe",
        "unknown_cell",
        "duplicate_admission",
        "unfinished_admission",
        "receipt_identity",
        "missing_diagnostics",
        "wrong_provider",
        "negative_tokens",
        "bool_tokens",
        "infinite_latency",
        "over_bound_cost",
        "unknown_cost_value",
        "typed_result",
        "partial_vocab",
        "invalid_mass",
        "invented_confidence",
        "invented_maximum",
        "vocabulary_evidence",
        "result_primitive",
        "result_precision",
    ],
)
def test_semantically_rehashed_invalid_journal_cuts_refuse(bundle, mutation):
    events = bundle["events"]
    admission = next(e for e in events if e["event"] == "attempt_started")
    receipt_event = next(e for e in events if e["event"] == "attempt_finished")
    outcome = next(e for e in events if e["event"] == "cell_finished")
    receipt, prediction = receipt_event["receipt"], outcome["predictions"]["decision"]
    if mutation == "terminal_missing":
        events.pop()
    elif mutation == "extra_after_terminal":
        events.append(copy.deepcopy(events[1]))
    elif mutation == "quality_cut":
        events[0]["through_phase"] = "quality"
    elif mutation == "unknown_event":
        events[1]["event"] = "unreviewed_event"
    elif mutation == "missing_probe":
        events[:] = [e for e in events if e.get("cell_id") != outcome["cell_id"]]
    elif mutation == "unknown_cell":
        admission["cell_id"] = "0" * 64
    elif mutation == "duplicate_admission":
        events.insert(4, copy.deepcopy(admission))
    elif mutation == "unfinished_admission":
        events.remove(receipt_event)
    elif mutation == "receipt_identity":
        receipt["request_hash"] = "0" * 64
    elif mutation == "missing_diagnostics":
        receipt["response_diagnostics"] = None
    elif mutation == "wrong_provider":
        receipt["provider"] = "OtherProvider"
    elif mutation == "negative_tokens":
        receipt["input_tokens"] = -1
    elif mutation == "bool_tokens":
        receipt["output_tokens"] = True
    elif mutation == "infinite_latency":
        receipt["elapsed_s"] = -1  # JSON rejects infinity separately
    elif mutation == "over_bound_cost":
        receipt["cost_usd"] = "1"
    elif mutation == "unknown_cost_value":
        receipt.update(cost_status="unknown", cost_usd="0")
    elif mutation == "typed_result":
        prediction.pop("probability_semantics")
    elif mutation == "partial_vocab":
        prediction["probabilities"].pop("0")
    elif mutation == "invalid_mass":
        prediction["probabilities"] = dict.fromkeys(prediction["probabilities"], 0)
    elif mutation == "invented_confidence":
        prediction["confidence"] = 2
    elif mutation == "invented_maximum":
        outcome["capability_evidence"]["maximum_boundaries_verified"] = True
    elif mutation == "vocabulary_evidence":
        outcome["capability_evidence"]["options_per_question"]["decision"] = 24
    elif mutation == "result_primitive":
        prediction["type"] = "chat"
    elif mutation == "result_precision":
        prediction["probability_rounding_digits"] = 0
    _refuse(bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "denominator",
        "bool_denominator",
        "cell_status",
        "probe_receipts",
        "probe_evidence",
        "reported_cost",
        "held_cost",
        "unresolved",
        "stop",
        "quality_rows",
        "historical_charge",
        "allocation_binding",
        "boundary",
    ],
)
def test_report_conflicts_refuse_without_output(bundle, mutation):
    report = bundle["report"]
    if mutation == "source":
        report["inference_source_hash"] = "0" * 64
    elif mutation == "denominator":
        report["denominators"]["completed"] = 13
    elif mutation == "bool_denominator":
        report["cells"][0]["dataset"] = False
    elif mutation == "cell_status":
        report["cells"][1]["status"] = "completed"
    elif mutation == "probe_receipts":
        report["capability_probes"][0]["attempts"] = 2
    elif mutation == "probe_evidence":
        report["capability_probes"][0]["evidence"]["question_count"] = True
    elif mutation == "reported_cost":
        report["accounting"]["reported_cost_usd"] = "0"
    elif mutation == "held_cost":
        report["accounting"]["reserved_usd"] = "1"
    elif mutation == "unresolved":
        report["accounting"]["unresolved_attempts"] = ["attempt-0"]
    elif mutation == "stop":
        report["accounting"]["admission_stopped"] = True
    elif mutation == "quality_rows":
        report["cohorts"][0]["rows"] = [{"prediction": "invented"}]
    elif mutation == "historical_charge":
        report["shared_accounting"]["snapshot"]["unknown_attempts"] = []
    elif mutation == "allocation_binding":
        report["shared_accounting"]["binding"]["allocation_id"] = "other"
    elif mutation == "boundary":
        report["execution_phase_boundary"] = "quality"
    _save(bundle, bind=False)
    _refuse(bundle, save=False)


@pytest.mark.parametrize("location", ["manifest", "report", "journal"])
@pytest.mark.parametrize(
    "private",
    [
        "/Users/private/other",
        "/home/private/evidence",
        "/private/tmp/evidence",
        "C:\\Users\\private\\evidence",
        "sk-or-public-synthetic-marker",
        "Bearer synthetic-fixture-token",
    ],
)
def test_unrecognized_private_strings_refuse_without_broad_replacement(
    bundle, location, private
):
    target = (
        bundle["manifest"]
        if location == "manifest"
        else (bundle["report"] if location == "report" else bundle["events"][1])
    )
    target["unreviewed_metadata"] = private
    _refuse(bundle)


@pytest.mark.parametrize(
    "key", ["Authorization", "headers", "request_headers", "api_key", "access_token"]
)
def test_private_field_names_refuse_even_when_value_empty(bundle, key):
    bundle["report"][key] = ""
    _refuse(bundle)


def test_unknown_occurrence_of_known_allocation_path_is_not_substituted(bundle):
    bundle["report"]["unexpected_path"] = bundle["manifest"]["shared_allocation"][
        "directory"
    ]
    _refuse(bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        "sequence",
        "hash",
        "previous",
        "partial_line",
        "blank_line",
        "duplicate_key",
        "nan",
        "overflow",
    ],
)
def test_raw_input_corruption_refuses_before_output(bundle, mutation):
    path = bundle["paths"][1]
    raw = path.read_bytes()
    if mutation == "sequence":
        raw = raw.replace(b'"sequence":1,', b'"sequence":2,', 1)
    elif mutation == "hash":
        raw = raw.replace(bundle["events"][0]["hash"].encode(), b"0" * 64, 1)
    elif mutation == "previous":
        raw = raw.replace(content_hash(bundle["manifest"]).encode(), b"0" * 64, 1)
    elif mutation == "partial_line":
        raw = raw[:-1]
    elif mutation == "blank_line":
        raw += b"\n"
    elif mutation == "duplicate_key":
        raw = raw.replace(b'{"event":', b'{"event":"duplicate","event":', 1)
    elif mutation == "nan":
        raw = raw.replace(b'"elapsed_s":0.1', b'"elapsed_s":NaN', 1)
    elif mutation == "overflow":
        raw = raw.replace(b'"elapsed_s":0.1', b'"elapsed_s":1e1000', 1)
    path.write_bytes(raw)
    _refuse(bundle, save=False)


def test_existing_output_is_never_overwritten(bundle):
    bundle["out"].mkdir()
    sentinel = bundle["out"] / "keep"
    sentinel.write_bytes(b"existing unrelated evidence")
    with pytest.raises(ValueError, match="fresh"):
        _export(bundle)
    assert sentinel.read_bytes() == b"existing unrelated evidence"
    assert list(bundle["out"].iterdir()) == [sentinel]


def test_input_symlink_is_refused_and_outputs_not_created(bundle):
    path = bundle["paths"][0]
    target = path.with_name("actual-manifest.json")
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        _export(bundle)
    assert not bundle["out"].exists()


def test_aggregate_currency_ignores_ambient_decimal_context(bundle):
    with localcontext() as context:
        context.prec = 2
        summary = json.loads(_export(bundle).read_bytes())
    assert Decimal(summary["accounting"]["reported_cost_usd"]) == Decimal("0.000504000")


def test_each_retry_retains_its_separate_physical_receipt_and_charge(bundle):
    events = bundle["events"]
    admission = copy.deepcopy(events[3])
    retry = copy.deepcopy(events[4])
    admission["attempt_id"] = retry["receipt"]["attempt_id"] = "attempt-0-retry"
    retry["receipt"]["response_id"] = "response-0-retry"
    events[4]["receipt"].update(status_code=429, error="backend HTTP 429", cost_usd="0")
    events[5:5] = [admission, retry]
    bundle["report"]["capability_probes"][0]["attempts"] = 2
    _save(bundle)
    summary = json.loads(_export(bundle).read_bytes())
    assert summary["actual_transport_attempts"] == 13
    receipts = summary["attempt_receipts"][:2]
    assert [item["receipt"]["attempt_id"] for item in receipts] == ["attempt-0", "attempt-0-retry"]
    assert receipts[0]["receipt"]["status_code"] == 429
    assert receipts[0]["receipt"]["cost_usd"] == "0"
    assert summary["accounting"]["reported_cost_usd"] == "0.000504000"


@pytest.mark.parametrize("mutation", ["receipt_after_cut", "receipt_before_admission", "terminal_before_events", "shared_liability_total", "shared_effective_total"])
def test_independent_cut_chronology_and_shared_liability_findings_refuse(bundle, mutation):
    if mutation == "receipt_after_cut":
        next(event for event in bundle["events"] if event["event"] == "attempt_finished")["receipt"]["timestamp"] = "2026-10-10T00:00:00+00:00"
    elif mutation == "receipt_before_admission":
        next(event for event in bundle["events"] if event["event"] == "attempt_finished")["receipt"]["timestamp"] = "2026-10-08T00:00:00+00:00"
    elif mutation == "terminal_before_events":
        bundle["events"][-1]["timestamp"] = "2026-10-08T00:00:00+00:00"
    elif mutation == "shared_liability_total":
        bundle["report"]["shared_accounting"]["snapshot"]["total_liability_usd"] = "0"
    elif mutation == "shared_effective_total":
        bundle["report"]["shared_accounting"]["snapshot"].update(effective_cost_usd="0", total_liability_usd="0.001344000")
    _refuse(bundle)


@pytest.mark.parametrize("claim", [
    {"accuracy": 1, "macro_f1": 1, "evaluated": 999},
    {"accuracy": 0}, {"n_attempted": 1}, {"confusion": {"a": {"a": 1}}},
    {"latency": {"n": 1, "p50_s": 0.1}}, {"throughput_per_s": 1},
    {"uncertainty": {"accuracy": {"status": "ok", "groups": 1, "low": 0, "high": 1}}},
    {"reliability": [{"confidence": 1}]}, {"total_cost_usd": "1"},
    {"mean_modal_share": 1}, {"threshold": 0.9, "validation_groups": 1},
    {"groups": [{"planned_observations": 6, "completed_observations": 0, "modal_share": 1}]},
])
def test_rowless_quality_or_timing_claims_are_not_emitted(bundle, claim):
    bundle["report"]["cohorts"][0]["quality"] = claim
    _refuse(bundle)


def test_unavailable_metrics_and_positive_planned_protocol_counts_are_retained(bundle):
    metrics: dict[str, Any] = {"accuracy": None, "macro_f1": None, "n_attempted": 0, "n_success": 0,
               "confusion": {"a": {"a": 0}}, "latency": {"n": 0, "mean_s": None, "p50_s": None, "p95_s": None, "p99_s": None},
               "uncertainty": {"accuracy": {"status": "insufficient_groups", "low": None, "high": None, "groups": 0, "samples": 2000}},
               "planned_decisions": 999, "planned_cells": 999, "planned_status_counts": {"unattempted": 999},
               "n_repeated_groups": 14, "n_repeated_planned_observations": 84, "n_repeated_completed_observations": 0,
               "groups": [{"planned_observations": 6, "planned_warm_repeats": 5, "completed_observations": 0,
                   "primary_completed": False, "label_observations": 0, "label_counts": {}, "modal_share": None}],
               "planned_coverage": 0.0, "total_cost_usd": "0", "known_cost_usd": "0",
               "out_of_scope_detection": {"positive_labels": ["oos"], "n_planned_hard": 5500, "n_planned_oos": 1000,
                   "tp": 0, "fp": 0, "fn": 0, "tn": 0, "n_valid_hard": 0, "n_valid_oos": 0, "n_failed_oos": 0,
                   "precision": None, "recall": None, "f1": None, "specificity": None}}
    bundle["report"]["cohorts"][0]["metrics"] = metrics
    _save(bundle)
    _export(bundle)
    projected = json.loads((bundle["out"] / "report-public.json").read_bytes())
    assert projected["cohorts"][0]["metrics"] == metrics


def test_new_unresolved_billing_is_retained_separately_from_historical_bound(bundle):
    final_receipt = [event for event in bundle["events"] if event["event"] == "attempt_finished"][-1]["receipt"]
    final_receipt.update(cost_status="unknown", cost_usd=None)
    accounting = {"limit_usd": "25", "reported_cost_usd": "0.000462000", "reserved_usd": "0.001344000",
                  "unresolved_attempts": ["attempt-11"], "admission_stopped": True}
    bundle["events"][-1]["accounting"] = copy.deepcopy(accounting)
    bundle["report"]["accounting"] = accounting
    shared = bundle["report"]["shared_accounting"]["snapshot"]
    shared["unknown_attempts"].append("attempt-11")
    shared["historical_unknown_attempts"].append("attempt-11")
    shared.update(reported_cost_usd="0.000462000", effective_cost_usd="0.000462000", reserved_usd="0.001344000",
                  total_liability_usd="0.003150000", pending_attempts=["attempt-11"], admission_stopped=True)
    _save(bundle)
    summary = json.loads(_export(bundle).read_bytes())
    assert summary["accounting"] == accounting
    assert summary["historical_bounded_unknown"]["original_attempt_ids"] == ["historical-unknown"]
    assert summary["historical_bounded_unknown"]["charge_status"] == "UNKNOWN"
    assert summary["attempt_receipts"][-1]["receipt"]["cost_usd"] is None


def test_cli_failure_does_not_print_private_input_names_or_exception_values(bundle):
    args = [
        sys.executable,
        str(_PATH),
        "--manifest",
        str(bundle["paths"][0]),
        "--journal-prefix",
        str(bundle["paths"][1]),
        "--report",
        str(bundle["paths"][2]),
        "--out-dir",
        str(bundle["out"]),
    ]
    for name, path in zip(
        ("manifest", "journal", "report"), bundle["paths"], strict=True
    ):
        args.extend(
            [
                "--" + name + "-sha256",
                "0" * 64 if name == "manifest" else _hash(path.read_bytes()),
            ]
        )
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr == "Capability export refused: ValueError\n"
    assert not bundle["out"].exists()
