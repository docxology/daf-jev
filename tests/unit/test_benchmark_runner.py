"""Offline experiment planning/reporting and real local transport execution."""

import hashlib
import json
import shutil
import time
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext

import pytest

from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import (
    catalog_profiles,
    execute_run,
    plan_run,
    report_run,
    save_report,
)
from daf_jev.benchmark_store import RunStore
from daf_jev.cli import main
from daf_jev.decision_backends import content_hash


def _config(tmp_path, *, backends=None, budget="0", kind="categorical"):
    data = tmp_path / "dataset.json"
    save_dataset(make_synthetic_dataset(kind, seed=13, n=6), data)
    config = {"format": "dafjev.benchmark-run/1", "seed": 13, "budget_usd": budget,
              "sampling": "all", "timing_samples": 1, "timing_repetitions": 1,
              "capability_probes": False,
              "timeout_s": 2, "datasets": [{"path": data.name}],
              "backends": backends or [{"id": "uniform", "kind": "uniform", "model": "uniform"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def test_overage_aggregate_allocation_conserves_every_currency_unit():
    from daf_jev.benchmark_runner import _allocated_billing

    total = "18000000000.000000000000000003"
    rows = _allocated_billing(total, ["first", "second", "third"])
    with localcontext() as context:
        context.prec = 50
        assert sum(map(Decimal, rows.values()), Decimal(0)) == Decimal(total)
    assert len(rows) == 3


def _native():
    return {"model": "fixture", "answers": {"decision": {"type": "choice", "choice": "billing",
            "probabilities": {"billing": .6, "account": .2, "technical": .2}, "confidence": .6}}, "usage": {}}


def test_plan_execute_report_resume_local_prior_has_exact_frozen_identity(tmp_path):
    store = plan_run(_config(tmp_path), tmp_path / "runs")
    assert len(store.manifest["cells"]) == 4
    assert store.manifest["protocol"]["test_labels_used_for_selection"] is False
    report = execute_run(store.directory)
    assert report["status"] == "complete" and report["denominators"] == {"completed": 4}
    assert report["manifest_hash"] == store.manifest_hash
    assert report["repeatability"][0]["n_repeated_planned_observations"] == 2
    assert report["repeatability"][0]["n_primary_only_groups"] == 2
    assert report["dataset_audits"][0]["full"]["examples"] == 6
    assert report["dataset_audits"][0]["selected"]["examples"] == 3
    assert report["gate_evidence"]["source_manifest_hash"] == store.manifest_hash
    assert len(report["policies"]) == 1
    assert report["policies"][0]["evidence"] == "offline_replay"
    assert report["policies"][0]["gate"]["status"] == "insufficient_evidence"
    assert report["policies"][0]["metrics"]["coverage"] == 0
    assert report["resources"][0]["backend"] == "uniform"
    assert all(c["metrics"]["throughput_wall_s"] > 0 for c in report["cohorts"])
    assert report_run(store.directory)["journal_hash"] == report["journal_hash"]
    completed_before = [e for e in store.events() if e.get("event") == "cell_finished"]
    resumed = execute_run(store.directory)
    assert resumed["denominators"] == {"completed": 4}
    assert len([e for e in store.events() if e.get("event") == "cell_finished"]) == len(completed_before)
    output = tmp_path / "report.json"
    save_report(resumed, output)
    assert json.loads(output.read_text())["manifest_hash"] == store.manifest_hash
    with pytest.raises(FileExistsError):
        save_report(resumed, output)


def test_report_primary_plus_five_warm_repeats_and_planned_denominators(tmp_path):
    path = _config(tmp_path)
    config = json.loads(path.read_text())
    config["timing_repetitions"] = 5
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    before = report_run(store.directory)["repeatability"][0]
    assert before["n_repeated_planned_observations"] == 6
    assert before["n_repeated_completed_observations"] == 0
    assert before["mean_modal_share"] is None
    report = execute_run(store.directory)
    result = report["repeatability"][0]
    assert result["n_planned_observations"] == 8
    assert result["n_repeated_planned_observations"] == result["n_repeated_completed_observations"] == 6
    assert result["n_planned_warm_repeats"] == result["n_completed_warm_repeats"] == 5
    assert result["groups"][0]["primary_completed"] is True
    assert result["mean_pairwise_label_agreement"] == result["mean_modal_share"] == 1
    assert result["mean_distribution_pairwise_half_l1"] == 0


@pytest.mark.parametrize("null_pack", [False, True])
def test_validation_only_quality_plan_never_requires_test_timing_samples(tmp_path, null_pack):
    from dataclasses import replace

    from daf_jev.benchmark_datasets import BenchmarkDataset

    dataset = make_synthetic_dataset("categorical", seed=13, n=6)
    selected = tuple(replace(example, split="validation") for example in dataset.examples
                     if example.split == "validation")
    path = _config(tmp_path)
    manifest = replace(dataset.manifest, metadata={})
    save_dataset(BenchmarkDataset(manifest, selected), tmp_path / "validation.json")
    config = json.loads(path.read_text())
    config.update({"datasets": [{"path": "validation.json"}], "timing_samples": 100,
                   "execution_selection": {"phase": "quality"}})
    if null_pack:
        config["timing_sample_pack"] = None
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    assert store.manifest["protocol"]["timing_enabled"] is False
    assert not store.manifest["protocol"]["timing_sample_pack"]["examples"]
    assert len(store.manifest["cells"]) == len(selected)
    report = execute_run(store.directory)
    assert report["denominators"] == {"completed": len(selected)}
    assert {cell["phase"] for cell in report["cells"]} == {"quality"}
    assert all(cohort["split"] == "validation" for cohort in report["cohorts"])


def test_explicit_quality_timing_binding_still_requires_exact_shared_test_cohort(tmp_path):
    path = _config(tmp_path)
    config = json.loads(path.read_text())
    config.update({"execution_selection": {"phase": "quality"}, "timing_samples": 100,
                   "timing_sample_pack": {"examples": []}})
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="exact cohort timing requires"):
        plan_run(path, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("sampling", ["full", "ALL", "", None, True, 1])
def test_unknown_sampling_mode_is_rejected_before_artifacts_or_requests(tmp_path, sampling):
    path = _config(tmp_path)
    config = json.loads(path.read_text())
    config["sampling"] = sampling
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="sampling must be pilot or all"):
        plan_run(path, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_real_local_http_cells_retry_receipts_and_offline_report(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    stub.enqueue(503, body={"usage": {}, "error": "retry fixture"})
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())
    result = execute_run(store.directory)
    assert result["status"] == "complete"
    assert len(stub.hits) == len(store.manifest["cells"]) + 1
    attempts = [e for e in store.events() if e.get("event") == "attempt_finished"]
    assert len(attempts) == len(stub.hits)
    assert attempts[0]["receipt"]["status_code"] == 503
    assert all(e["receipt"]["input_tokens"] is None for e in attempts)
    hits = len(stub.hits)
    assert report_run(store.directory)["status"] == "complete"
    assert len(stub.hits) == hits
    assert execute_run(store.directory)["status"] == "complete"
    assert len(stub.hits) == hits


@pytest.mark.parametrize("fixture_cost", ["11", None])
def test_retry_budget_refusal_after_real_503_preserves_failed_cell_and_receipt(tmp_path, stub, fixture_cost):
    """Loopback is keyless/local; the observer's billing is explicit fixture data.

    A paid hosted execute_run cannot be pointed at loopback. This exercises its
    exact journal-based refusal classifier, real transport and real report/resume
    without relaxing that endpoint boundary or claiming provider billing evidence.
    """
    import asyncio
    from dataclasses import asdict, replace

    from daf_jev.benchmark_datasets import load_prepared_dataset
    from daf_jev.benchmark_runner import _budget_stop_outcome
    from daf_jev.benchmark_store import BudgetStopped, SpendLedger
    from daf_jev.decision_backends import (
        AsyncHTTPDecisionBackend,
        BackendHTTPError,
        DecisionRequest,
    )

    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    store = plan_run(_config(tmp_path, backends=[profile], budget="25"), tmp_path / "runs")
    cell = next(c for c in store.manifest["cells"] if c["phase"] == "quality")
    dataset = load_prepared_dataset(tmp_path / "dataset.json")
    example = next(e for e in dataset.examples if e.id == cell["example_id"])
    ledger = SpendLedger(store, limit="25")
    original_receipts = []

    class SyntheticBillingObserver:
        def before(self, request_hash, model, endpoint):
            return ledger.reserve(cell["id"], request_hash, model, endpoint, True, "15")

        def after(self, receipt):
            original_receipts.append(receipt)
            assert receipt.cost_status == "local" and receipt.cost_usd is None
            synthetic = replace(receipt, cost_usd=fixture_cost,
                                cost_status="reported" if fixture_cost is not None else "unknown")
            ledger.finish(cell["id"], synthetic)

    stub.enqueue(503, body={"error": "owned fixture", "usage": {"cost": 11}})
    store.append({"event": "cell_started", "cell_id": cell["id"]})

    async def transport_attempts():
        backend = AsyncHTTPDecisionBackend(endpoint=profile["endpoint"], model="fixture")
        request = DecisionRequest(example.state, example.questions, timeout=2, observer=SyntheticBillingObserver())
        try:
            with pytest.raises(BackendHTTPError) as first:
                await backend.predict(request)
            assert first.value.status_code == 503
            with pytest.raises(BudgetStopped) as retry:
                await backend.predict(request)
            return _budget_stop_outcome(store, cell["id"], retry.value)
        finally:
            await backend.close()

    status, error = asyncio.run(transport_attempts())
    assert (status, error) == ("failed", "BudgetStopped")
    original = asdict(original_receipts[0])
    store.append({"event": "cell_finished", "cell_id": cell["id"], "status": status,
                  "error": error, "elapsed_s": .1, "predictions": {}})
    for other in store.manifest["cells"]:
        if other["id"] != cell["id"]:
            store.append({"event": "cell_finished", "cell_id": other["id"], "status": "unsupported",
                          "reason": "owned fixture excludes unrelated cells"})
    events = store.events()
    admitted = [event for event in events if event["event"] == "attempt_started"]
    finished = [event for event in events if event["event"] == "attempt_finished"]
    assert len(admitted) == len(finished) == len(stub.hits) == 1
    assert admitted[0]["attempt_id"] == finished[0]["receipt"]["attempt_id"] == original["attempt_id"]
    retained = finished[0]["receipt"]
    assert {key: value for key, value in retained.items() if key not in ("cost_usd", "cost_status")} == {
        key: value for key, value in original.items() if key not in ("cost_usd", "cost_status")}
    assert retained["status_code"] == 503 and retained["error"] == "BackendHTTPError"
    assert retained["request_hash"] == content_hash(stub.hits[0]["json"])
    snapshot = ledger.snapshot()
    assert snapshot["reported_cost_usd"] == (fixture_cost or "0")
    assert snapshot["reserved_usd"] == ("0" if fixture_cost is not None else "15")
    assert bool(snapshot["unresolved_attempts"]) is (fixture_cost is None)
    report = report_run(store.directory)
    assert report["denominators"] == {"failed": 1, "unsupported": len(store.manifest["cells"]) - 1}
    assert next(c for c in report["cells"] if c["id"] == cell["id"])["reason"] == "BudgetStopped"
    assert report["accounting"] == snapshot
    resumed = execute_run(store.directory)
    assert resumed["denominators"] == report["denominators"]
    assert len(stub.hits) == len(original_receipts) == 1
    assert ledger.snapshot() == snapshot
    assert [event for event in store.events() if event["event"] == "attempt_finished"] == finished


def test_initial_budget_refusal_with_cell_start_but_no_admitted_intent_is_unattempted(tmp_path, stub):
    import asyncio

    from daf_jev.benchmark_datasets import load_prepared_dataset
    from daf_jev.benchmark_runner import _budget_stop_outcome
    from daf_jev.benchmark_store import BudgetStopped, SpendLedger
    from daf_jev.decision_backends import AsyncHTTPDecisionBackend, DecisionRequest

    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    cell = next(c for c in store.manifest["cells"] if c["phase"] == "quality")
    example = next(e for e in load_prepared_dataset(tmp_path / "dataset.json").examples
                   if e.id == cell["example_id"])
    ledger = SpendLedger(store, limit="0")
    observer = ledger.observer(cell_id=cell["id"], hosted=True, liability_usd="15")
    store.append({"event": "cell_started", "cell_id": cell["id"]})

    async def refuse():
        backend = AsyncHTTPDecisionBackend(endpoint=profile["endpoint"], model="fixture")
        try:
            with pytest.raises(BudgetStopped) as stopped:
                await backend.predict(DecisionRequest(example.state, example.questions, timeout=2, observer=observer))
            return _budget_stop_outcome(store, cell["id"], stopped.value)
        finally:
            await backend.close()

    status, error = asyncio.run(refuse())
    assert (status, error) == ("unattempted", "USD budget exhausted")
    store.append({"event": "cell_finished", "cell_id": cell["id"], "status": status, "error": error})
    assert not stub.hits
    assert not any(event["event"] in ("attempt_started", "attempt_finished") for event in store.events())
    assert next(c for c in report_run(store.directory)["cells"] if c["id"] == cell["id"])["status"] == "unattempted"
    assert ledger.snapshot()["reported_cost_usd"] == ledger.snapshot()["reserved_usd"] == "0"


def test_local_execution_deadline_cancels_one_attempt_and_retains_unattempted_cells(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    path = _config(tmp_path, backends=[profile])
    config = json.loads(path.read_text())
    config.update({"local_time_limit_s": 2, "timeout_s": 10})
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    stub.enqueue(body=_native(), delay=6)

    started = time.perf_counter()
    report = execute_run(store.directory)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.5  # includes setup/accounting/report; handler still takes 6s
    assert report["denominators"] == {"failed": 1, "unattempted": len(store.manifest["cells"]) - 1}
    assert len(stub.hits) == 1
    events = store.events()
    started_attempts = [row for row in events if row.get("event") == "attempt_started"]
    receipts = [row["receipt"] for row in events if row.get("event") == "attempt_finished"]
    assert len(started_attempts) == len(receipts) == 1
    assert receipts[0]["attempt_id"] == started_attempts[0]["attempt_id"]
    assert receipts[0]["error"] == "CancelledError" and receipts[0]["status_code"] is None
    interrupted = [row for row in events if row.get("event") == "cell_finished" and row["status"] == "failed"]
    assert len(interrupted) == 1 and interrupted[0]["error"] == "TimeoutError"
    assert all(cell["reason"] == "local_execution_deadline" for cell in report["cells"] if cell["status"] == "unattempted")
    assert report["accounting"]["unresolved_attempts"] == []
    assert report["accounting"]["reported_cost_usd"] == "0"
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())
    resumed = execute_run(store.directory)
    assert resumed["denominators"] == report["denominators"]
    assert len(stub.hits) == len(receipts) == 1
    assert len([row for row in store.events() if row.get("event") == "attempt_finished"]) == 1
    assert all(cell["reason"] == "local_execution_deadline" for cell in resumed["cells"] if cell["status"] == "unattempted")


def test_local_execution_deadline_includes_transient_error_backoff_and_retry(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    path = _config(tmp_path, backends=[profile])
    config = json.loads(path.read_text())
    config.update({"local_time_limit_s": 2.5, "timeout_s": 10})
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    stub.enqueue(503, body={"usage": {}, "error": "public transient fixture"})
    stub.enqueue(body=_native(), delay=6)

    began = time.perf_counter()
    report = execute_run(store.directory)
    assert time.perf_counter() - began < 5.5
    assert len(stub.hits) == 2
    assert report["denominators"] == {"failed": 1, "unattempted": len(store.manifest["cells"]) - 1}
    events = store.events()
    receipts = [row["receipt"] for row in events if row.get("event") == "attempt_finished"]
    assert len(receipts) == 2 and receipts[0]["status_code"] == 503
    assert receipts[0]["error"] == "BackendHTTPError"
    assert receipts[1]["status_code"] is None and receipts[1]["error"] == "CancelledError"
    failed = next(row for row in events if row.get("event") == "cell_finished" and row["status"] == "failed")
    assert failed["error"] == "TimeoutError"
    assert report["accounting"]["unresolved_attempts"] == []


def test_resume_of_unclosed_profile_time_window_refuses_local_http(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    store.append({"event": "local_profile_started", "backend": "local", "profile_execution_id": "interrupted-fixture"})
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())

    report = execute_run(store.directory)
    assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
    assert all(cell["reason"] == "local_execution_time_unknown" for cell in report["cells"])
    assert stub.hits == []
    assert not any(row.get("event") in ("attempt_started", "attempt_finished") for row in store.events())


def test_local_execution_deadline_midgraph_preserves_completed_and_cancelled_receipts(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture",
               "capabilities": {"primitives": ["choice"]}}
    path = _config(tmp_path, backends=[profile], kind="ordinal")
    config = json.loads(path.read_text())
    config.update({"local_time_limit_s": 2.5, "timeout_s": 10, "graphical_experiments": True})
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    rows = {"cpt::cloudy|": (.5, .5), "cpt::rain|cloudy=false": (.8, .2),
            "cpt::rain|cloudy=true": (.2, .8), "cpt::wet|rain=false": (.9, .1),
            "cpt::wet|rain=true": (.1, .9)}
    cpt_response = {"model": "fixture", "usage": {}, "answers": {
        qid: {"type": "choice", "choice": "false" if row[0] >= row[1] else "true",
              "probabilities": dict(zip(("false", "true"), row, strict=True)), "confidence": .8}
        for qid, row in rows.items()}}
    stub.enqueue(body=cpt_response)
    stub.enqueue(body={"usage": {}, "answers": {}}, delay=6)

    report = execute_run(store.directory)
    assert len(stub.hits) == 2
    graphical = next(cell for cell in report["cells"] if cell["phase"] == "graphical")
    assert graphical["status"] == "failed" and graphical["reason"] == "TimeoutError"
    workflow = next(item["record"] for item in report["graphical_experiments"] if item["cell_id"] == graphical["id"])
    assert workflow["status"] == "interrupted" and workflow["phase"] == "propose_structure"
    assert workflow["cpt_soft_brier_mean"] == 0
    assert len(workflow["calls"]) == 1
    assert len(workflow["attempt_ids"]) == len(workflow["observed_receipts"]) == 2
    receipts = [row["receipt"] for row in store.events() if row.get("event") == "attempt_finished"]
    assert [receipt["status_code"] for receipt in receipts] == [200, None]
    assert receipts[1]["error"] == "CancelledError"
    assert workflow["observed_receipts"] == receipts
    assert report["accounting"]["unresolved_attempts"] == []


def test_graphical_noul_only_backend_is_unsupported_before_graphical_http(tmp_path, stub):
    profile = {"id": "binary-only", "kind": "http", "endpoint": stub.base_url + "/v1/systemone",
               "model": "fixture", "capabilities": {"primitives": ["noul"], "probability_source": "native"}}
    path = _config(tmp_path, backends=[profile], kind="binary")
    config = json.loads(path.read_text())
    config["graphical_experiments"] = True
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    for cell in store.manifest["cells"]:
        if cell["phase"] != "graphical":
            stub.enqueue(body={"model": "fixture", "answers": {"decision": {"type": "noul", "noul": .7,
                              "confidence": .7}}, "usage": {}})
    report = execute_run(store.directory)
    graphical = next(cell for cell in report["cells"] if cell["phase"] == "graphical")
    assert graphical["status"] == "unsupported"
    assert graphical["reason"] == "graphical_requires_choice_primitive"
    assert report["denominators"] == {"completed": len(store.manifest["cells"]) - 1, "unsupported": 1}
    assert len(stub.hits) == len(store.manifest["cells"]) - 1
    assert not any(event.get("cell_id") == graphical["id"] and event["event"] in
                   {"cell_started", "attempt_started", "attempt_finished"} for event in store.events())


def test_runtime_probe_runs_first_and_retry_receipts_do_not_contaminate_quality_metrics(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    path = _config(tmp_path, backends=[profile])
    payload = json.loads(path.read_text())
    payload.pop("capability_probes")  # the normal default must probe
    path.write_text(json.dumps(payload))
    store = plan_run(path, tmp_path / "runs")
    probe = next(c for c in store.manifest["cells"] if c["phase"] == "capability_probe")
    assert len(store.manifest["cells"]) == 5
    assert all(c.get("capability_probe_id") == probe["id"] for c in store.manifest["cells"] if c != probe)
    stub.enqueue(503, body={"error": "public retry fixture", "usage": {}})
    for _ in range(5):
        stub.enqueue(body=_native())
    report = execute_run(store.directory)
    assert report["denominators"] == {"completed": 5}
    assert len(stub.hits) == 6
    finished = [e for e in store.events() if e.get("event") == "cell_finished"]
    assert finished[0]["cell_id"] == probe["id"]
    evidence = report["capability_probes"][0]
    assert evidence["attempts"] == 2 and evidence["evidence"]["empirical_success"] is True
    assert evidence["evidence"]["maximum_boundaries_verified"] is False
    assert sum(c["metrics"]["n_attempted"] for c in report["cohorts"]) == 4
    assert all(c["phase"] != "capability_probe" for c in report["cohorts"])
    assert execute_run(store.directory)["denominators"] == {"completed": 5}
    assert len(stub.hits) == 6


def test_runtime_phase_boundary_retains_manifest_ledger_and_resumes_only_pending_http(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    path = _config(tmp_path, backends=[profile])
    config = json.loads(path.read_text())
    config["capability_probes"] = True
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    manifest_before = (store.directory / "manifest.json").read_bytes()
    probe = next(c for c in store.manifest["cells"] if c["phase"] == "capability_probe")
    stub.enqueue(503, body={"error": "public retry fixture", "usage": {}})
    stub.enqueue(body=_native())
    probes = execute_run(store.directory, through_phase="capability_probe")
    assert len(stub.hits) == 2
    assert probes["status"] == "partial" and probes["denominators"] == {"completed": 1, "unattempted": 4}
    assert probes["execution_phase_boundary"] == "capability_probe"
    assert all(c["reason"] == "execution_phase_boundary" for c in probes["cells"] if c != probe and c["status"] == "unattempted")
    assert len([e for e in store.events() if e.get("event") == "cell_finished"]) == 1
    assert report_run(store.directory)["journal_hash"] == probes["journal_hash"]
    assert len(stub.hits) == 2  # offline reduction never resumes transport
    assert execute_run(store.directory, through_phase="capability_probe")["denominators"] == probes["denominators"]
    assert len(stub.hits) == 2

    for _ in range(3):
        stub.enqueue(body=_native())
    quality = execute_run(store.directory, through_phase="quality")
    assert len(stub.hits) == 5
    assert quality["denominators"] == {"completed": 4, "unattempted": 1}
    assert all(c["phase"] == "warm_repeat" and c["reason"] == "execution_phase_boundary"
               for c in quality["cells"] if c["status"] == "unattempted")
    stub.enqueue(body=_native())
    finished = execute_run(store.directory)
    assert finished["denominators"] == {"completed": 5} and len(stub.hits) == 6
    assert finished["execution_phase_boundary"] is None
    assert finished["accounting"] == probes["accounting"]  # same zero-cost local ledger
    assert (store.directory / "manifest.json").read_bytes() == manifest_before
    assert [e["through_phase"] for e in store.events() if e.get("event") == "execution_started"] == [
        "capability_probe", "capability_probe", "quality", None]
    assert len([e for e in store.events() if e.get("event") == "cell_finished" and e["cell_id"] == probe["id"]]) == 1


@pytest.mark.parametrize("boundary", ["warm_repeat", "graphical"])
def test_runtime_later_phase_boundaries_include_all_earlier_http_work(tmp_path, stub, boundary):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    path = _config(tmp_path, backends=[profile])
    config = json.loads(path.read_text())
    config["capability_probes"] = True
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    for _ in range(5):
        stub.enqueue(body=_native())
    report = execute_run(store.directory, through_phase=boundary)
    assert report["denominators"] == {"completed": 5}
    assert report["execution_phase_boundary"] == boundary and len(stub.hits) == 5


@pytest.mark.parametrize("boundary", ["probe", "all", "", True, 1, [], {}])
def test_invalid_runtime_boundary_is_rejected_before_opening_or_creating_run(tmp_path, boundary):
    directory = tmp_path / "missing-run"
    with pytest.raises(ValueError, match="through_phase must be"):
        execute_run(directory, through_phase=boundary)
    assert not directory.exists()


def test_cli_runtime_boundary_preserves_partial_exit_and_later_resume(tmp_path, capsys):
    store = plan_run(_config(tmp_path), tmp_path / "runs")
    assert main(["benchmark", "run", str(store.directory), "--through-phase", "quality"]) == 1
    partial = json.loads(capsys.readouterr().out)
    assert partial["denominators"] == {"completed": 3, "unattempted": 1}
    assert partial["execution_phase_boundary"] == "quality"
    assert main(["benchmark", "resume", str(store.directory), "--through-phase", "warm_repeat"]) == 0
    assert json.loads(capsys.readouterr().out)["denominators"] == {"completed": 4}


@pytest.mark.parametrize("declared_unsupported", [False, True])
def test_failed_or_unsupported_probe_records_dependents_without_more_requests(tmp_path, stub, declared_unsupported):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    if declared_unsupported:
        profile["capabilities"] = {"max_options": 2}
    path = _config(tmp_path, backends=[profile])
    payload = json.loads(path.read_text())
    payload["capability_probes"] = True
    path.write_text(json.dumps(payload))
    store = plan_run(path, tmp_path / "runs")
    if not declared_unsupported:
        stub.enqueue(422, body={"error": "unsupported public fixture", "usage": {}})
    report = execute_run(store.directory)
    assert report["denominators"] == ({"unsupported": 5} if declared_unsupported else {"failed": 1, "unsupported": 4})
    assert len(stub.hits) == (0 if declared_unsupported else 1)
    assert len(report["cohorts"]) == 3
    assert sum(c["metrics"]["planned_cells"] for c in report["cohorts"]) == 4
    assert all(c["rows"] == [] and c["metrics"]["accuracy"] is None for c in report["cohorts"])
    assert all(c["metrics"]["planned_cell_status_counts"] == {"unsupported": c["metrics"]["planned_cells"]}
               for c in report["cohorts"])
    dependent = [c for c in report["cells"] if c["phase"] != "capability_probe"]
    assert all(c["reason"] == "capability_probe_" + ("unsupported" if declared_unsupported else "failed") for c in dependent)
    assert execute_run(store.directory)["denominators"] == report["denominators"]


def test_unattempted_missing_key_probe_leaves_frozen_dependents_unattempted(tmp_path, monkeypatch):
    monkeypatch.delenv("DAFJEV_MISSING_PROBE_CREDENTIAL", raising=False)
    profile = {"id": "hosted", "kind": "http", "hosted": True,
        "endpoint": "https://openrouter.ai/api/v1/chat/completions", "mode": "chat", "model": "fixture",
        "api_key_env": "DAFJEV_MISSING_PROBE_CREDENTIAL", "context_length": 100,
        "pricing": {"source": "fixture", "snapshot_at": "2026-10-07T00:00:00Z", "rates": {"prompt": ".001", "completion": "0"}}}
    path = _config(tmp_path, backends=[profile])
    payload = json.loads(path.read_text())
    payload["capability_probes"] = True
    path.write_text(json.dumps(payload))
    store = plan_run(path, tmp_path / "runs")
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": 5}
        assert all(c["reason"] == "capability_probe_unattempted" for c in report["cells"] if c["phase"] != "capability_probe")
        assert not any(e.get("event") == "attempt_started" for e in store.events())


def test_declared_dataset_allowlist_retains_unsupported_cells_without_fit_or_transport(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture",
               "datasets": ["wine"]}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    report = execute_run(store.directory)
    assert report["denominators"] == {"unsupported": 4}
    assert all(c["reason"] == "dataset_outside_backend_allowlist" for c in report["cells"])
    assert stub.hits == []


def test_input_ancestor_symlink_is_rejected_on_offline_report(tmp_path):
    store = plan_run(_config(tmp_path), tmp_path / "runs")
    inputs = store.directory / "inputs"
    original = store.directory / "original_inputs"
    inputs.rename(original)
    inputs.symlink_to(original, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        report_run(store.directory)


def test_decode_failure_is_failed_and_local_receipt_survives(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture"}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    for _ in store.manifest["cells"]:
        stub.enqueue(body={"model": "fixture", "answers": {}, "usage": {"cost": ".001"}})
    report = execute_run(store.directory)
    assert report["status"] == "partial" and report["denominators"] == {"failed": 4}
    receipts = [e["receipt"] for e in store.events() if e.get("event") == "attempt_finished"]
    assert len(receipts) == 4 and all(r["cost_usd"] is None and r["error"] is not None for r in receipts)
    assert report["accounting"]["reported_cost_usd"] == "0"
    assert sum(c["metrics"]["n_errors"] for c in report["cohorts"]) == 4


def test_unsupported_vocab_is_explicit_and_never_shrunk(tmp_path, stub):
    profile = {"id": "local", "kind": "http", "endpoint": stub.base_url + "/v1/systemone", "model": "fixture",
               "capabilities": {"max_options": 2}}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    report = execute_run(store.directory)
    assert report["denominators"] == {"unsupported": 4}
    assert stub.hits == []
    assert not any(e.get("event") == "attempt_started" for e in store.events())


def test_zero_budget_hosted_run_and_resume_never_admit_transport(tmp_path, monkeypatch):
    # A non-secret fixture credential exercises admission. No request is sent:
    # the strict zero budget cannot cover the declared positive liability.
    monkeypatch.setenv("DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "public-unit-test-placeholder")
    profile = {"id": "hosted", "kind": "http", "hosted": True,
               "endpoint": "https://openrouter.ai/api/v1/chat/completions", "mode": "chat", "model": "fixture",
               "api_key_env": "DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "context_length": 100,
               "pricing": {"source": "fixture tariff", "snapshot_at": "2026-10-07T00:00:00Z",
                           "rates": {"prompt": "0.001", "completion": "0"}}}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["status"] == "partial"
        assert report["denominators"] == {"unattempted": 4}
        assert report["accounting"]["reported_cost_usd"] == "0"
        assert not any(e.get("event") == "attempt_started" for e in store.events())


@pytest.mark.parametrize("mode", ["chat", "letter"])
@pytest.mark.parametrize("defect, reason", [
    ("liability", "frozen_liability_mismatch"),
    ("caps", "frozen_execution_settings_unbounded"),
    ("fallback", "frozen_execution_settings_unbounded"),
])
def test_stale_hosted_bounds_are_refused_before_backend_or_transport(tmp_path, mode, defect, reason):
    profile = {"id": "hosted", "kind": "http", "hosted": True, "mode": mode, "model": "fixture",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions", "context_length": 100,
        "pricing": {"source": "fixture tariff", "snapshot_at": "2026-10-07T00:00:00Z",
                    "rates": {"prompt": "0.001", "completion": "0"}},
        "options": {"stop": ["public-fixture-stop"]}}
    planned = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "planned")
    manifest = json.loads(json.dumps(planned.manifest))
    frozen = manifest["backends"][0]
    if defect == "liability":
        frozen["liability_usd"] = "0"
    elif defect == "caps":
        del frozen["options"]["provider"]["max_price"]
    else:
        frozen["options"]["provider"]["allow_fallbacks"] = True
    store = RunStore.create(tmp_path / "stale", manifest)
    (store.directory / "inputs").mkdir()
    shutil.copyfile(planned.directory / "inputs/dataset-0.json", store.directory / "inputs/dataset-0.json")
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": 4}
        assert {cell["reason"] for cell in report["cells"]} == {reason}
        assert report["accounting"]["reported_cost_usd"] == "0"
        assert not any(event["event"] in {"backend_ready", "cell_started", "attempt_started",
                                         "attempt_finished"} for event in store.events())


def test_honest_hosted_bounds_with_frozen_sequence_options_reach_zero_budget_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "public-unit-test-placeholder")
    profile = {"id": "hosted", "kind": "http", "hosted": True, "mode": "chat", "model": "fixture",
        "api_key_env": "DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions", "context_length": 100,
        "pricing": {"source": "fixture tariff", "snapshot_at": "2026-10-07T00:00:00Z",
                    "rates": {"prompt": "0.001", "completion": "0"}},
        "options": {"stop": ["public-fixture-stop"]}}
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    report = execute_run(store.directory)
    assert report["denominators"] == {"unattempted": 4}
    assert any(event["event"] == "backend_ready" for event in store.events())
    assert not any(event["event"] == "attempt_started" for event in store.events())
    assert not any(cell["reason"] in {"frozen_liability_mismatch", "frozen_execution_settings_unbounded"}
                   for cell in report["cells"])


def test_executed_cascade_frozen_gate_and_zero_hosted_budget_admission(tmp_path, monkeypatch):
    monkeypatch.setenv("DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "public-unit-test-placeholder")
    path = _config(tmp_path)
    baseline = plan_run(path, tmp_path / "runs")
    report = execute_run(baseline.directory)
    gate_file = tmp_path / "gates.json"
    gate_file.write_text(json.dumps(report["gate_evidence"]))
    payload = json.loads(path.read_text())
    payload["backends"] += [{"id": "hosted", "kind": "http", "hosted": True,
        "endpoint": "https://openrouter.ai/api/v1/chat/completions", "mode": "chat", "model": "fixture",
        "api_key_env": "DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "context_length": 100,
        "pricing": {"source": "fixture tariff", "snapshot_at": "2026-10-07T00:00:00Z",
                    "rates": {"prompt": "0.001", "completion": "0"}}},
        {"id": "cascade", "kind": "cascade", "weak": "uniform", "strong": "hosted", "gate_file": gate_file.name}]
    path.write_text(json.dumps(payload))
    store = plan_run(path, tmp_path / "runs")
    cascade = next(p for p in store.manifest["backends"] if p["id"] == "cascade")
    assert content_hash(cascade["gate_evidence"]) == content_hash(report["gate_evidence"])
    assert len(cascade["gate_sha256"]) == 64
    executed = execute_run(store.directory)
    assert executed["denominators"] == {"completed": 4, "unattempted": 4, "failed": 4}
    assert not any(e.get("event") == "attempt_started" for e in store.events())
    assert execute_run(store.directory)["denominators"] == executed["denominators"]


def test_unresolved_cells_never_replayed_and_input_tamper_rejected(tmp_path):
    store = plan_run(_config(tmp_path), tmp_path / "runs")
    first = store.manifest["cells"][0]
    store.append({"event": "cell_started", "cell_id": first["id"]})
    report = execute_run(store.directory)
    assert report["denominators"]["unresolved"] == 1
    assert not any(e.get("event") == "cell_finished" and e.get("cell_id") == first["id"] for e in store.events())
    dataset_path = store.directory / store.manifest["datasets"][0]["file"]
    dataset_path.write_text(dataset_path.read_text() + " ")
    with pytest.raises(ValueError, match="dataset bytes changed"):
        report_run(store.directory)


@pytest.mark.parametrize("change", [{"budget_usd": "25.01"}, {"timing_repetitions": 0},
                                     {"timeout_s": float("nan")}, {"seed": True},
                                     {"backends": [{"id": "bad", "api_key": "forbidden-value"}]}])
def test_plan_validation_rejects_before_inference(tmp_path, change):
    path = _config(tmp_path)
    payload = json.loads(path.read_text())
    payload.update(change)
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        plan_run(path, tmp_path / "runs")


def test_cli_offline_dataset_plan_run_report_resume(tmp_path, capsys):
    data = tmp_path / "dataset.json"
    assert main(["benchmark", "dataset", "synthetic", "--samples", "6", "--output", str(data)]) == 0
    assert json.loads(capsys.readouterr().out)["dataset"] == str(data)
    config = {"format": "dafjev.benchmark-run/1", "datasets": [{"path": "dataset.json"}], "sampling": "all",
              "budget_usd": "0", "timing_repetitions": 1, "timing_samples": 1,
              "backends": [{"id": "uniform", "kind": "uniform"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    assert main(["benchmark", "plan", "--config", str(path), "--out-dir", str(tmp_path / "runs")]) == 0
    planned = json.loads(capsys.readouterr().out)
    directory = planned["directory"]
    assert RunStore(directory).manifest_hash == planned["manifest_hash"]
    for command in ("run", "report", "resume"):
        assert main(["benchmark", command, directory]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "complete"


def test_catalog_discovery_profiles_preserve_model_metadata_without_inference(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"payload": {"data": [
        {"id": "vendor/model", "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]},
         "context_length": 1000, "pricing": {"prompt": "0.00001", "completion": "0"}},
        {"id": "alias", "alias_target": {"slug": "vendor/model"},
         "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]},
         "context_length": 1000, "pricing": {"prompt": "0.00001", "completion": "0"}},
    ]}, "fetched_at": "2026-10-07T00:00:00Z", "source": "https://openrouter.ai/api/v1/models"}))
    profiles = catalog_profiles(path)
    assert len(profiles) == 1
    assert profiles[0]["model"] == "vendor/model"
    assert profiles[0]["hosted"] is True


@pytest.mark.parametrize("difference", [
    {"pricing": {"prompt": "0.00002", "completion": "0"}},
    {"top_provider": {"context_length": 500}}, {"supported_parameters": ["seed"]},
    {"context_length": 2000},
])
def test_catalog_aliases_preserve_different_tariffs_or_routing_contracts(tmp_path, difference):
    target = {"id": "respan/reference", "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]},
              "context_length": 1000, "pricing": {"prompt": "0.00001", "completion": "0"}}
    alias = {**target, "id": "vendor/variant", "alias_target": {"slug": target["id"]}, **difference}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"payload": {"data": [target, alias]}, "source": "public fixture", "fetched_at": "2026-10-07"}))
    profiles = catalog_profiles(path)
    assert [profile["model"] for profile in profiles] == [target["id"], alias["id"]]
    assert profiles[1]["pricing"]["rates"] == alias["pricing"]
    assert profiles[1]["capabilities"]["primitives"] == ["noul"]
    assert profiles[1]["artifact"]["declared_alias_target"] == target["id"]


def test_catalog_unknown_alias_equivalence_is_retained_with_unknown_price(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"payload": {"data": [{"id": "vendor/unknown", "alias_target": "vendor/absent"}]},
                               "source": "public fixture", "fetched_at": "2026-10-07"}))
    profiles = catalog_profiles(path)
    assert len(profiles) == 1 and profiles[0]["model"] == "vendor/unknown"
    assert profiles[0]["pricing"]["rates"] == {}


def test_catalog_cyclic_aliases_do_not_erase_the_executable_pool(tmp_path):
    common = {"pricing": {"prompt": "0", "completion": "0"}, "context_length": 1000}
    models = [{**common, "id": "vendor/a", "alias_target": "vendor/b"},
              {**common, "id": "vendor/b", "alias_target": "vendor/a"},
              {**common, "id": "vendor/self", "alias_target": "vendor/self"}]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"payload": {"data": models}, "source": "public fixture", "fetched_at": "2026-10-07"}))
    assert len(catalog_profiles(path)) == 3


@pytest.mark.parametrize("incomplete", [
    {"pricing": {"prompt": "0", "completion": "0"}}, {"pricing": {}},
    {"pricing": {"prompt": "0", "completion": "0"}, "context_length": 0,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]}},
    {"pricing": {"prompt": "0", "completion": "0"}, "context_length": 1000,
     "architecture": {"input_modalities": [], "output_modalities": ["decisions"]}},
    {"pricing": {"prompt": "NaN", "completion": "0"}, "context_length": 1000,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]}},
])
def test_catalog_matching_incomplete_contracts_do_not_establish_alias_equivalence(tmp_path, incomplete):
    models = [{**incomplete, "id": "vendor/model"},
              {**incomplete, "id": "vendor/alias", "alias_target": "vendor/model"}]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"payload": {"data": models}, "source": "public fixture", "fetched_at": "2026-10-07"}))
    assert len(catalog_profiles(path)) == 2


def _priced_profile():
    return {"id": "hosted", "kind": "http", "hosted": True,
        "endpoint": "https://openrouter.ai/api/v1/chat/completions", "mode": "chat", "model": "fixture",
        "api_key_env": "DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "context_length": 1000,
        "pricing": {"source": "public fixture tariff", "snapshot_at": "2026-10-07T00:00:00Z",
                    "rates": {"prompt": "0.000001", "completion": "0.000002"}},
        "options": {"max_tokens": 20}}


def test_actual_sent_price_ceiling_is_reserved_instead_of_catalog_minimum(tmp_path):
    from daf_jev import choice
    from daf_jev.benchmark_store import BudgetStopped, SpendLedger
    from daf_jev.decision_backends import DecisionRequest, HTTPDecisionBackend

    profile = _priced_profile()
    # The model's nominal catalog prices are lower than these permitted route
    # prices. A budget just below the actual sent ceiling must stop before I/O.
    profile["options"]["provider"] = {"allow_fallbacks": True, "require_parameters": False,
        "max_price": {"prompt": 4, "completion": 9}}
    store = plan_run(_config(tmp_path, backends=[profile], budget="0.004179999"), tmp_path / "runs")
    frozen = store.manifest["backends"][0]
    assert Decimal(frozen["liability_usd"]) == Decimal("0.00418")
    ledger = SpendLedger(store, limit=store.manifest["budget_usd"])
    backend = HTTPDecisionBackend(endpoint=frozen["endpoint"], model=frozen["model"], hosted=True,
        mode="chat", api_key="public-unit-test-placeholder", options=frozen["options"],
        observer=ledger.observer(cell_id="public-tariff-fixture", hosted=True,
                                 liability_usd=frozen["liability_usd"]))
    request = DecisionRequest("public fixture", {"decision": choice("Choose.", {"a": None, "b": None})})
    try:
        body = backend._body(request)
        assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True,
            "max_price": {"prompt": 4, "completion": 9, "request": 0, "image": 0}}
        with pytest.raises(BudgetStopped, match="exhausted"):
            backend.predict(request)
    finally:
        backend.close()
    assert not any(event.get("event") == "attempt_started" for event in store.events())
    assert ledger.snapshot()["reported_cost_usd"] == "0"


def test_catalog_tariff_default_sends_token_ceilings_and_zero_surcharge_caps(tmp_path):
    profile = _priced_profile()
    # These known zero-priced metadata extras do not make a token-only route
    # ineligible. The actual request still sends explicit zero surcharge caps.
    profile["pricing"]["rates"].update({"request": "0", "web_search": "0", "image": "0"})
    store = plan_run(_config(tmp_path, backends=[profile]), tmp_path / "runs")
    frozen = store.manifest["backends"][0]
    assert Decimal(frozen["liability_usd"]) == Decimal("0.00104")
    assert frozen["options"]["provider"] == {"allow_fallbacks": False, "require_parameters": True,
        "max_price": {"prompt": 1, "completion": 2, "request": 0, "image": 0}}


def test_hosted_pricing_uses_isolated_currency_policy(tmp_path):
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 0
        ambient.traps[Inexact] = True
        store = plan_run(_config(tmp_path, backends=[_priced_profile()]), tmp_path / "runs")
        assert Decimal(store.manifest["backends"][0]["liability_usd"]) == Decimal("0.00104")
        assert store.manifest["backends"][0]["options"]["provider"]["max_price"]["completion"] == 2
        assert ambient.prec == 2 and ambient.traps[Inexact]


@pytest.mark.parametrize("charge,questions", [("1", 3), ("0.000000000000000001", 3),
                                              ("0.000000000000000006", 10)])
def test_report_apportions_batched_request_charge_exactly_without_changing_receipt(tmp_path, charge, questions):
    from daf_jev.benchmark_store import SpendLedger, currency_context
    from daf_jev.decision_backends import CallReceipt, utc_now

    profile = _priced_profile()
    profile["pricing"]["rates"] = {"prompt": ".001", "completion": "0"}
    path = _config(tmp_path, backends=[profile], budget="25")
    data_path = tmp_path / "dataset.json"
    data = json.loads(data_path.read_text())
    qids = [f"question-{i:02}" for i in range(questions)]
    for example in data["examples"]:
        question, target = example["questions"]["decision"], example["targets"]["decision"]
        example["questions"] = dict.fromkeys(qids, question)
        example["targets"] = dict.fromkeys(qids, target)
    data["manifest"]["metadata"]["examples_sha256"] = content_hash(data["examples"])
    data["manifest"]["metadata"]["order_sensitive_examples_sha256"] = hashlib.sha256(json.dumps(data["examples"], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    data_path.write_text(json.dumps(data))
    store = plan_run(path, tmp_path / "runs")
    cell = next(cell for cell in store.manifest["cells"] if cell["phase"] == "quality")
    example = next(example for example in data["examples"] if example["id"] == cell["example_id"])
    store.append({"event": "cell_started", "cell_id": cell["id"]})
    ledger = SpendLedger(store, limit=store.manifest["budget_usd"])
    attempt = ledger.reserve(cell["id"], "public-batched-billing-fixture", profile["model"],
                             profile["endpoint"], True, store.manifest["backends"][0]["liability_usd"])
    receipt = CallReceipt(attempt, utc_now(), profile["endpoint"], profile["model"], profile["model"],
                          "public-fixture-provider", "public-fixture-response", "public-batched-billing-fixture",
                          .1, 200, 10, 10, charge, "reported")
    ledger.finish(cell["id"], receipt)
    store.append({"event": "cell_finished", "cell_id": cell["id"], "status": "completed", "error": None,
                  "elapsed_s": .1, "predictions": {qid: {"value": example["targets"][qid]} for qid in qids}})
    original_events = store.events()

    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 0
        ambient.traps[Inexact] = True
        report = report_run(store.directory)
        assert Decimal(report["accounting"]["reported_cost_usd"]) == Decimal(charge)
        cohort = next(cohort for cohort in report["cohorts"] if cohort["phase"] == "quality")
        assert Decimal(cohort["metrics"]["total_cost_usd"]) == Decimal(charge)
        assert len(cohort["rows"]) == questions
        assert {row["billing_group_id"] for row in cohort["rows"]} == {cell["id"]}
        assert all("1E-18 USD units" in row["cost_allocation"] for row in cohort["rows"])
        assert all("local compute expense is separate" in row["cost_scope"] for row in cohort["rows"])
        with localcontext(currency_context()):
            allocations = [Decimal(row["cost_usd"]) for row in cohort["rows"]]
            assert sum(allocations, Decimal(0)) == Decimal(charge)
            assert max(allocations) - min(allocations) <= Decimal("1E-18")
            assert all(amount >= 0 and amount.as_tuple().exponent >= -18 for amount in allocations)
            assert cohort["rows"][0]["question_id"] == qids[0]
            assert allocations == sorted(allocations, reverse=True)
            if charge == "1":
                assert allocations == [Decimal("0.333333333333333334"),
                                       Decimal("0.333333333333333333"), Decimal("0.333333333333333333")]
        assert ambient.prec == 2 and ambient.traps[Inexact]
    assert store.events() == original_events
    finished = [event["receipt"] for event in store.events() if event.get("event") == "attempt_finished"]
    assert finished == [receipt.to_dict()]


@pytest.mark.parametrize("case", [
    "missing_pricing_source", "missing_pricing_time", "missing_completion_rate",
    "boolean_context", "zero_context", "native_charged_unbounded_output",
    "cache_write_premium", "cache_read_premium", "unknown_nonzero_surcharge", "per_request_price",
    "image_price", "insufficient_input_ceiling", "boolean_output_limit", "zero_output_limit",
])
def test_ineligible_tariff_retains_cells_without_paid_admission(tmp_path, monkeypatch, case):
    profile = _priced_profile()
    if case == "missing_pricing_source":
        profile["pricing"].pop("source")
    elif case == "missing_pricing_time":
        profile["pricing"].pop("snapshot_at")
    elif case == "missing_completion_rate":
        profile["pricing"]["rates"].pop("completion")
    elif case == "boolean_context":
        profile["context_length"] = True
    elif case == "zero_context":
        profile["context_length"] = 0
    elif case == "native_charged_unbounded_output":
        profile["mode"] = "systemone"
    elif case in {"cache_write_premium", "cache_read_premium"}:
        profile["pricing"]["rates"]["input_cache_write" if case == "cache_write_premium" else "input_cache_read"] = "0.000003"
    elif case == "unknown_nonzero_surcharge":
        profile["pricing"]["rates"]["internal_reasoning"] = "0.1"
    elif case in {"per_request_price", "image_price", "insufficient_input_ceiling"}:
        prices = {"prompt": 1, "completion": 2}
        prices[{"per_request_price": "request", "image_price": "image",
                "insufficient_input_ceiling": "prompt"}[case]] = .1
        profile["options"]["provider"] = {"max_price": prices}
    else:
        profile["options"]["max_tokens"] = True if case == "boolean_output_limit" else 0
    monkeypatch.setenv("DAFJEV_BENCHMARK_FIXTURE_CREDENTIAL", "public-unit-test-placeholder")
    store = plan_run(_config(tmp_path, backends=[profile], budget="25"), tmp_path / "runs")
    assert store.manifest["backends"][0]["liability_usd"] is None
    for _ in range(2):
        report = execute_run(store.directory)
        assert report["denominators"] == {"unattempted": 4}
        assert report["accounting"]["reported_cost_usd"] == "0"
        assert not any(event.get("event") == "attempt_started" for event in store.events())


@pytest.mark.parametrize("cancelled_receipt", [False, True])
def test_graphical_summary_preserves_started_nonterminal_status(tmp_path, cancelled_receipt):
    from daf_jev.benchmark_store import SpendLedger
    from daf_jev.decision_backends import CallReceipt

    profile = {"id": "local", "kind": "http", "model": "fixture",
               "endpoint": "http://127.0.0.1:1/v1/systemone"}
    path = _config(tmp_path, backends=[profile])
    config = json.loads(path.read_text())
    config["graphical_experiments"] = True
    path.write_text(json.dumps(config))
    store = plan_run(path, tmp_path / "runs")
    graph = next(cell for cell in store.manifest["cells"] if cell["phase"] == "graphical")
    store.append({"event": "cell_started", "cell_id": graph["id"]})
    if cancelled_receipt:
        ledger = SpendLedger(store, limit="0")
        request_hash = content_hash({"owned_fixture": "graphical"})
        attempt = ledger.reserve(graph["id"], request_hash, "fixture", profile["endpoint"], False, "0")
        ledger.finish(graph["id"], CallReceipt(
            attempt_id=attempt, timestamp="2026-10-08T00:00:00+00:00",
            endpoint=profile["endpoint"], requested_model="fixture", resolved_model=None,
            provider=None, response_id=None, request_hash=request_hash, elapsed_s=.1,
            status_code=None, input_tokens=None, output_tokens=None, cost_usd=None,
            cost_status="local", error="CancelledError"))
        store.append({"event": "cell_cancelled", "cell_id": graph["id"], "workflow": None})

    report = report_run(store.directory)
    main = next(cell for cell in report["cells"] if cell["id"] == graph["id"])
    summary = next(cell for cell in report["graphical_experiments"] if cell["cell_id"] == graph["id"])
    assert main["status"] == summary["status"] == "unresolved"
    assert report["denominators"]["unresolved"] == 1 and report["status"] == "partial"
    assert summary["record"] is None
    assert report["accounting"]["unresolved_attempts"] == []
    assert not any(event["event"] == "cell_finished" and event["cell_id"] == graph["id"]
                   for event in store.events())


def _http_cascade_store(tmp_path, stub, monkeypatch, *, local_limit=2, direct_weak=False):
    from daf_jev.benchmark_policies import GateCalibration
    from daf_jev.benchmark_runner import _gate_identity

    monkeypatch.setenv("DAFJEV_CASCADE_FIXTURE_KEY", "public-unit-test-placeholder")
    profiles = [
        {"id": "weak", "kind": "http", "endpoint": stub.base_url + "/weak", "model": "fixture"},
        {"id": "strong", "kind": "http", "hosted": True, "endpoint": "https://openrouter.ai/api/alpha/decisions",
         "model": "fixture", "api_key_env": "DAFJEV_CASCADE_FIXTURE_KEY"},
    ]
    path = _config(tmp_path, backends=profiles)
    config = json.loads(path.read_text())
    config.update({"execution_selection": {"phase": "quality"}, "local_time_limit_s": local_limit})
    path.write_text(json.dumps(config))
    base = plan_run(path, tmp_path / "base-runs")
    manifest = json.loads(json.dumps(base.manifest))
    calibration = GateCalibration("insufficient_evidence", None, .05, None, 0, 0, 0)
    manifest["backends"].append({"id": "cascade", "kind": "cascade", "hosted": True,
        "weak": "weak", "strong": "strong", "gate_evidence": {
            "format": "dafjev.policy-gates/1", "source_manifest_hash": base.manifest_hash,
            "gates": [{"backend": "weak", "dataset_sha256": manifest["datasets"][0]["manifest"]["sha256"],
                       "validation_identity": _gate_identity(manifest, "weak", 0),
                       "calibration": calibration.to_dict()}]}})
    weak_cells = [cell for cell in manifest["cells"] if cell["backend"] == "weak"]
    cascade_cells = [{**cell, "backend": "cascade", "id": content_hash([
        cell["dataset"], cell["example_id"], "cascade", cell["repeat"]])} for cell in weak_cells]
    manifest["cells"] = (weak_cells if direct_weak else []) + cascade_cells
    store = RunStore.create(tmp_path.resolve() / "cascade-runs", manifest)
    (store.directory / "inputs").mkdir()
    shutil.copyfile(base.directory / "inputs/dataset-0.json", store.directory / "inputs/dataset-0.json")
    return store


def test_cascade_strong_admission_stop_retains_completed_weak_as_failed_workflow(tmp_path, stub, monkeypatch):
    store = _http_cascade_store(tmp_path, stub, monkeypatch)
    for _ in store.manifest["cells"]:
        stub.enqueue(body=_native())
    report = execute_run(store.directory)
    assert report["denominators"] == {"failed": len(store.manifest["cells"])}
    events = store.events()
    receipts = [event["receipt"] for event in events if event["event"] == "attempt_finished"]
    assert len(stub.hits) == len(receipts) == len(store.manifest["cells"])
    assert all(not event["hosted"] for event in events if event["event"] == "attempt_started")
    for event in events:
        if event["event"] == "cell_finished":
            assert event["error"] == "BudgetStopped"
            assert event["workflow"]["weak_status"] == "completed"
            assert event["workflow"]["strong_status"] == "unattempted"
            assert len(event["workflow"]["observed_receipts"]) == 1
    assert report["resources"][0]["backend"] == "weak"
    assert "hosted interleaving" in report["resources"][0]["execution_scope"]
    assert report["accounting"]["reported_cost_usd"] == "0"
    assert report["accounting"]["unresolved_attempts"] == []
    assert execute_run(store.directory)["denominators"] == report["denominators"]
    assert len(stub.hits) == len(receipts)


@pytest.mark.parametrize("local_limit", [.02, .2])
def test_cascade_weak_deadline_cancels_without_strong_call_or_implicit_retry(tmp_path, stub, monkeypatch, local_limit):
    store = _http_cascade_store(tmp_path, stub, monkeypatch, local_limit=local_limit)
    stub.enqueue(body=_native(), delay=1)
    began = time.perf_counter()
    report = execute_run(store.directory)
    assert time.perf_counter() - began < .9
    events = store.events()
    receipts = [event["receipt"] for event in events if event["event"] == "attempt_finished"]
    assert len(stub.hits) == len(receipts) <= 1
    if local_limit == .2:
        assert len(receipts) == 1  # the .02 budget can validly expire during setup
    if receipts:
        assert receipts[0]["error"] == "CancelledError"
        failed = next(event for event in events if event["event"] == "cell_finished" and event["status"] == "failed")
        assert failed["error"] == "TimeoutError"
        assert failed["workflow"]["weak_status"] == "unresolved"
        assert failed["workflow"]["strong_status"] == "unattempted"
        assert failed["workflow"]["observed_receipts"] == receipts
    assert all(not event["hosted"] for event in events if event["event"] == "attempt_started")
    resources = [event for event in events if event["event"] == "resources_observed"]
    assert resources[0]["backend"] == "weak" and resources[0]["resources"]["wall_s"] >= local_limit
    repeated = execute_run(store.directory)
    assert repeated["denominators"] == report["denominators"]
    assert len(stub.hits) == len(receipts)


def test_cascade_resume_carries_prior_local_time_and_unknown_windows(tmp_path, stub, monkeypatch):
    store = _http_cascade_store(tmp_path, stub, monkeypatch, local_limit=.2)
    store.append({"event": "local_profile_started", "backend": "weak", "profile_execution_id": "prior"})
    store.append({"event": "resources_observed", "backend": "weak", "profile_execution_id": "prior",
                  "resources": {"wall_s": .3}})
    report = execute_run(store.directory)
    assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
    assert all(cell["reason"] == "local_execution_deadline" for cell in report["cells"])
    assert stub.hits == []
    newest = [event for event in store.events() if event["event"] == "local_profile_started"][-1]
    assert newest["consumed_wall_s"] == .3
    store.append({"event": "local_profile_started", "backend": "weak", "profile_execution_id": "unclosed"})
    report = execute_run(store.directory)
    assert all(cell["reason"] == "local_execution_time_unknown" for cell in report["cells"])
    assert stub.hits == []
    assert not any(event["event"] == "attempt_started" for event in store.events())


def test_cascade_carries_same_execution_direct_weak_time_before_hosted_phase(tmp_path, stub, monkeypatch):
    store = _http_cascade_store(tmp_path, stub, monkeypatch, local_limit=.2, direct_weak=True)
    stub.enqueue(body=_native(), delay=1)
    report = execute_run(store.directory)
    assert len(stub.hits) == 1
    assert all(cell["status"] == "unattempted" and cell["reason"] == "local_execution_deadline"
               for cell in report["cells"] if cell["backend"] == "cascade")
    events = store.events()
    started = [event for event in events if event["event"] == "local_profile_started"]
    resources = [event for event in events if event["event"] == "resources_observed"]
    assert len(started) == len(resources) == 2
    assert started[1]["consumed_wall_s"] == resources[0]["resources"]["wall_s"] >= .2
    assert all(event["backend"] == "weak" for event in started + resources)
    assert not any(event["hosted"] for event in events if event["event"] == "attempt_started")
