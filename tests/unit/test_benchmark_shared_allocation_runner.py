"""Shared admission integration without provider requests or implicit funding."""

import hashlib
import importlib.metadata
import json
from contextlib import closing
from dataclasses import replace

import pytest

from daf_jev import choice
from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import (
    _reporter_environment,
    execute_run,
    plan_run,
    report_run,
    source_identity,
)
from daf_jev.benchmark_store import BudgetStopped, SpendLedger
from daf_jev.cli import main
from daf_jev.decision_backends import (
    CallReceipt,
    DecisionRequest,
    HTTPDecisionBackend,
    content_hash,
    utc_now,
)


def _config(path, *, binding=None, hosted=False, budget="25"):
    path.mkdir()
    dataset = path / "dataset.json"
    save_dataset(make_synthetic_dataset("categorical", seed=13, n=6), dataset)
    profile = {"id": "uniform", "kind": "uniform"}
    if hosted:
        profile = {"id": "hosted", "kind": "http", "hosted": True, "mode": "chat",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": "public-fixture",
            "api_key_env": "DAFJEV_SHARED_ALLOCATION_TEST_KEY", "context_length": 100,
            "pricing": {"source": "synthetic fixture tariff", "snapshot_at": "2026-10-08T00:00:00Z",
                        "rates": {"prompt": "0.001", "completion": "0"}}}
    value = {"format": "dafjev.benchmark-run/1", "seed": 13, "budget_usd": budget,
        "sampling": "all", "timing_samples": 1, "timing_repetitions": 1,
        "capability_probes": False, "datasets": [{"path": dataset.name}], "backends": [profile]}
    if binding is not None:
        value["shared_allocation"] = binding
    config = path / "config.json"
    config.write_text(json.dumps(value))
    return config


def _hashes(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def test_bound_plan_and_report_only_inspect_existing_allocation(tmp_path):
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap", limit="25")
    binding = allocation.identity()
    binding["directory"] = "../allocation"
    path = _config(tmp_path / "inputs", binding=binding, hosted=True)
    with pytest.raises(ValueError, match="parent traversal"):
        plan_run(path, tmp_path / "runs")
    # A legal relative name is frozen to its absolute existing identity.
    path = _config(tmp_path / "legal", hosted=True)
    allocation = AllocationLedger.create(path.parent / "bound-allocation", allocation_id="relative-cap")
    relative = allocation.identity()
    relative["directory"] = "bound-allocation"
    config = json.loads(path.read_text())
    config["shared_allocation"] = relative
    path.write_text(json.dumps(config))
    before = _hashes(allocation.directory)
    store = plan_run(path, tmp_path / "runs")
    run_before = _hashes(store.directory)
    assert store.manifest["shared_allocation"] == allocation.identity()
    report = report_run(store.directory)
    assert report["shared_accounting"]["status"] == "observed"
    assert report["accounting"]["reported_cost_usd"] == "0"
    assert _hashes(store.directory) == run_before
    assert _hashes(allocation.directory) == before


@pytest.mark.parametrize("defect", ["extra", "missing", "id", "hash", "bool", "path"])
def test_invalid_shared_binding_fails_before_run_creation(tmp_path, defect):
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap", limit="1")
    binding = allocation.identity()
    if defect == "extra":
        binding["new_limit"] = "25"
    elif defect == "missing":
        del binding["manifest_hash"]
    elif defect == "id":
        binding["allocation_id"] = "another-cap"
    elif defect == "hash":
        binding["manifest_hash"] = "0" * 64
    elif defect == "bool":
        binding["allocation_id"] = True
    else:
        binding["directory"] = str(tmp_path / "absent")
    before = _hashes(allocation.directory)
    with pytest.raises((ValueError, OSError)):
        plan_run(_config(tmp_path / "input", binding=binding, budget="1"), tmp_path / "runs")
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "absent").exists()
    assert _hashes(allocation.directory) == before


def test_run_cap_cannot_exceed_allocation_cap(tmp_path):
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap", limit="1")
    with pytest.raises(ValueError, match="run budget exceeds"):
        plan_run(_config(tmp_path / "input", binding=allocation.identity(), budget="1.01"), tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_old_unbound_hosted_plan_is_readable_but_cannot_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("DAFJEV_SHARED_ALLOCATION_TEST_KEY", "public-fixture-placeholder")
    store = plan_run(_config(tmp_path / "input", hosted=True, budget="0"), tmp_path / "runs")
    before = _hashes(store.directory)
    for _ in range(2):
        with pytest.raises(BudgetStopped, match="frozen shared allocation"):
            execute_run(store.directory)
    report = report_run(store.directory)
    assert report["denominators"] == {"unattempted": len(store.manifest["cells"])}
    assert report["shared_accounting"]["status"] == "not_bound"
    assert store.events() == []
    assert _hashes(store.directory) == before


def test_required_import_blocks_execution_but_not_plan_or_report(tmp_path):
    legacy = plan_run(_config(tmp_path / "legacy"), tmp_path / "legacy-runs")
    binding = LegacyRunBinding.capture(legacy.directory)
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap",
                                         required_imports=(binding,))
    before = _hashes(allocation.directory)
    store = plan_run(_config(tmp_path / "new", binding=allocation.identity(), hosted=True, budget="0"),
                     tmp_path / "runs")
    with pytest.raises(BudgetStopped):
        execute_run(store.directory)
    assert store.events() == []
    assert report_run(store.directory)["shared_accounting"]["snapshot"]["required_imports_complete"] is False
    assert _hashes(allocation.directory) == before


def test_unknown_import_halts_even_free_shared_admission_without_repair(tmp_path):
    legacy = plan_run(_config(tmp_path / "legacy", hosted=True), tmp_path / "legacy-runs")
    cell = legacy.manifest["cells"][0]["id"]
    endpoint = legacy.manifest["backends"][0]["endpoint"]
    request_hash = content_hash({"public": "synthetic legacy admission, no HTTP"})
    ledger = SpendLedger(legacy, limit="25")
    attempt = ledger.reserve(cell, request_hash, "public-fixture", endpoint, True, "1")
    ledger.finish(cell, CallReceipt(attempt, utc_now(), endpoint, "public-fixture", None, None, None,
                                   request_hash, .01, 404, None, None, None, "unknown"))
    exact = LegacyRunBinding.capture(legacy.directory)
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap",
                                         required_imports=(exact,))
    allocation.import_run(exact)
    assert allocation.snapshot()["unknown_attempts"]
    before = _hashes(allocation.directory)
    store = plan_run(_config(tmp_path / "replacement", binding=allocation.identity(), hosted=True, budget="0"),
                     tmp_path / "replacement-runs")
    with pytest.raises(BudgetStopped):
        execute_run(store.directory)
    with pytest.raises(BudgetStopped), allocation.execution(store):
        SpendLedger(store, limit="0", allocation=allocation).reserve(
            store.manifest["cells"][0]["id"], request_hash, "public-fixture", endpoint, True, "0")
    assert store.events() == []
    report = report_run(legacy.directory)
    assert report["accounting"]["reserved_usd"] == "1"
    assert report["accounting"]["reported_cost_usd"] == "0"
    assert _hashes(allocation.directory) == before


def test_missing_shared_evidence_does_not_break_historical_run_report(tmp_path):
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap")
    store = plan_run(_config(tmp_path / "input", binding=allocation.identity(), hosted=True), tmp_path / "runs")
    allocation.directory.rename(tmp_path / "retained-allocation")
    before = _hashes(store.directory)
    result = report_run(store.directory)
    assert result["shared_accounting"]["status"] == "unavailable"
    assert result["accounting"]["reported_cost_usd"] == "0"
    assert result["denominators"] == {"unattempted": len(store.manifest["cells"])}
    assert _hashes(store.directory) == before
    assert not allocation.directory.exists()


def test_two_run_observers_share_one_cap_with_real_keyless_http(tmp_path, stub):
    """Billing is synthetic observer data; endpoint policy remains loopback/local."""
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="one-cap", limit="25")
    stores = [plan_run(_config(tmp_path / name, binding=allocation.identity()), tmp_path / "runs")
              for name in ("first", "replacement")]
    stub.enqueue(body={"model": "fixture", "answers": {"decision": {"type": "choice", "choice": "yes",
        "probabilities": {"yes": .75, "no": .25}, "confidence": .75}}, "usage": {}})
    for index, store in enumerate(stores):
        with allocation.execution(store):
            ledger = SpendLedger(store, limit="25", allocation=allocation)
            original = ledger.observer(cell_id=store.manifest["cells"][0]["id"], hosted=True,
                                       liability_usd="20" if index == 0 else "6")

            class SyntheticBilling:
                def __init__(self, observer):
                    self.observer = observer

                def before(self, *args):
                    return self.observer.before(*args)

                def after(self, receipt):
                    self.observer.after(replace(receipt, cost_status="reported", cost_usd="20"))

            with closing(HTTPDecisionBackend(endpoint=stub.base_url + "/decisions", model="fixture")) as backend:
                request = DecisionRequest("owned public input", {"decision": choice("Choose.", {"yes": None, "no": None})},
                                          observer=SyntheticBilling(original))
                if index == 0:
                    assert backend.predict(request).predictions["decision"].value == "yes"
                else:
                    with pytest.raises(BudgetStopped):
                        backend.predict(request)
    assert len(stub.hits) == 1
    assert allocation.snapshot()["reported_cost_usd"] == "20"
    assert SpendLedger(stores[1], limit="25").snapshot()["reported_cost_usd"] == "0"


def test_allocation_cli_explicit_init_inspect_import_and_no_implicit_creation(tmp_path, capsys):
    absent = tmp_path / "missing"
    assert main(["benchmark", "allocation", "inspect", str(absent)]) == 1
    capsys.readouterr()
    assert not absent.exists()
    legacy = plan_run(_config(tmp_path / "legacy"), tmp_path / "legacy-runs")
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps(LegacyRunBinding.capture(legacy.directory).to_dict()))
    directory = tmp_path / "allocation"
    assert main(["benchmark", "allocation", "init", str(directory), "--allocation-id", "one-cap",
                 "--required-import", str(binding)]) == 0
    assert json.loads(capsys.readouterr().out)["accounting"]["required_imports_complete"] is False
    before = _hashes(directory)
    assert main(["benchmark", "allocation", "inspect", str(directory)]) == 0
    capsys.readouterr()
    assert _hashes(directory) == before
    assert main(["benchmark", "allocation", "import-legacy", str(directory), "--binding", str(binding)]) == 0
    assert json.loads(capsys.readouterr().out)["accounting"]["required_imports_complete"] is True
    assert main(["benchmark", "allocation", "init", str(directory), "--allocation-id", "one-cap"]) == 1
    capsys.readouterr()


def test_duplicate_legacy_binding_json_is_refused_before_allocation_creation(tmp_path, capsys):
    binding = tmp_path / "binding.json"
    binding.write_text('{"format":"dafjev.shared-allocation-legacy-binding/1","directory":"a","directory":"b"}')
    directory = tmp_path / "allocation"
    assert main(["benchmark", "allocation", "init", str(directory), "--allocation-id", "one-cap",
                 "--required-import", str(binding)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"] == "ValueError"
    assert not directory.exists()


def test_source_and_reducer_runtime_inventories_bind_scipy_metadata():
    try:
        expected = importlib.metadata.version("scipy")
    except importlib.metadata.PackageNotFoundError:
        expected = None
    assert source_identity()["dependencies"]["scipy"] == expected
    assert _reporter_environment()["dependencies"]["scipy"] == expected
