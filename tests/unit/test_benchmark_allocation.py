"""One immutable allocation, real files/processes, and no network or provider keys."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import ROUND_DOWN, Inexact, localcontext

import pytest

from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import CallReceipt, utc_now

ENDPOINT = "https://fixture.invalid/decision"


def _allocation(tmp_path, *, required=(), limit="25"):
    return AllocationLedger.create(tmp_path.resolve() / "allocation", allocation_id="same-original-25", limit=limit, required_imports=required)


def _run(tmp_path, allocation, name="run", **extra):
    return RunStore.create_at(tmp_path.resolve() / name, {"budget_usd": "25", "shared_allocation": allocation.identity(), **extra})


def _receipt(attempt, *, cost="1", status="reported", **kwargs):
    value = CallReceipt(attempt, utc_now(), ENDPOINT, "fixture", "resolved", "provider", "response", "request", .01, 200, 1, 1, cost, status)
    return replace(value, **kwargs)


def _reserve(ledger, *, bound="1", cell="cell", hosted=True):
    return ledger.reserve(cell, "request", "fixture", ENDPOINT, hosted, bound)


def _bytes(directory):
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def _legacy(tmp_path, name="legacy", *, cost="1", status="reported", pending=False, bound="10"):
    store = RunStore.create_at(tmp_path.resolve() / name, {"budget_usd": "25", "fixture": name})
    ledger = SpendLedger(store)
    attempt = _reserve(ledger, bound=bound)
    if not pending:
        ledger.finish("cell", _receipt(attempt, cost=cost, status=status))
    return store, attempt, LegacyRunBinding.capture(store.directory)


def test_exact_currency_and_cumulative_shared_runs_no_budget_reset(tmp_path):
    allocation = _allocation(tmp_path)
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        for index, cost in enumerate(("11.000000000000000001", "12.999999999999999998")):
            store = _run(tmp_path, allocation, f"run{index}")
            with allocation.execution(store):
                ledger = SpendLedger(store, allocation=allocation)
                attempt = _reserve(ledger, bound="13")
                ledger.finish("cell", _receipt(attempt, cost=cost))
                assert set(ledger.snapshot()) == {"limit_usd", "reported_cost_usd", "reserved_usd", "unresolved_attempts", "admission_stopped"}
        final = _run(tmp_path, allocation, "run2")
        with allocation.execution(final):
            ledger = SpendLedger(final, allocation=allocation)
            with pytest.raises(BudgetStopped, match="shared USD"):
                _reserve(ledger, bound="1.000000000000000002")
            assert not ledger.admissions
        snapshot = AllocationLedger(allocation.directory, read_only=True).snapshot()
        assert snapshot["reported_cost_usd"] == "23.999999999999999999"
        assert snapshot["bound_runs"] == 3 and snapshot["reserved_usd"] == "0"
        assert snapshot["journal_tip"] == allocation.store.events()[-1]["hash"]


def test_readonly_identity_snapshot_create_at_are_explicit_and_exclusive(tmp_path):
    allocation = _allocation(tmp_path)
    before = _bytes(allocation.directory)
    readonly = AllocationLedger(allocation.directory, read_only=True)
    assert readonly.identity() == allocation.identity()
    assert not readonly.snapshot()["admission_stopped"]
    with pytest.raises(FileExistsError):
        AllocationLedger.create(allocation.directory, allocation_id="reset")
    with pytest.raises(FileExistsError):
        RunStore.create_at(allocation.directory, {})
    with pytest.raises(ValueError, match="read-only"), readonly.execution(_run(tmp_path, allocation)):
        pass
    with pytest.raises(ValueError, match="writable"):
        readonly.import_run(_legacy(tmp_path)[2])
    assert _bytes(allocation.directory) == before
    missing = tmp_path.resolve() / "missing"
    with pytest.raises(FileNotFoundError):
        AllocationLedger(missing, read_only=True)
    assert not missing.exists()


@pytest.mark.parametrize("limit", ["25.000000000000000001", True, "NaN", "Infinity", "-1"])
def test_invalid_allowance_refuses_before_create(tmp_path, limit):
    with pytest.raises(ValueError):
        _allocation(tmp_path, limit=limit)
    assert not (tmp_path / "allocation").exists()


@pytest.mark.parametrize("name", ["", "../25", "space id", "\n", "a" * 129])
def test_invalid_allocation_id_refuses_before_create(tmp_path, name):
    with pytest.raises(ValueError):
        AllocationLedger.create(tmp_path.resolve() / "allocation", allocation_id=name)
    assert not (tmp_path / "allocation").exists()


def test_missing_import_never_admits_and_unknown_import_keeps_old_bytes(tmp_path):
    old, attempt, binding = _legacy(tmp_path, cost=None, status="unknown")
    original = _bytes(old.directory)
    allocation = _allocation(tmp_path, required=(binding,))
    assert allocation.snapshot()["stop_reasons"] == ["required_legacy_imports_missing"]
    run = _run(tmp_path, allocation)
    with pytest.raises(BudgetStopped), allocation.execution(run):
        pytest.fail("missing import must not execute")
    assert run.events() == []
    allocation.import_run(LegacyRunBinding.from_dict(binding.to_dict()))
    snapshot = AllocationLedger(allocation.directory, read_only=True).snapshot()
    assert snapshot["reported_cost_usd"] == "0" and snapshot["reserved_usd"] == "10"
    assert snapshot["unknown_attempts"] == [attempt]
    assert snapshot["required_imports_complete"] and snapshot["admission_stopped"]
    with pytest.raises(BudgetStopped), allocation.execution(run):
        _reserve(SpendLedger(run, allocation=allocation), bound="0")
    with pytest.raises(ValueError, match="duplicate"):
        allocation.import_run(binding)
    assert _bytes(old.directory) == original


def test_reported_import_charges_once_and_pending_import_holds(tmp_path):
    old, _, binding = _legacy(tmp_path, cost="17", bound="17")
    allocation = _allocation(tmp_path, required=(binding,))
    allocation.import_run(binding)
    run = _run(tmp_path, allocation)
    with allocation.execution(run):
        ledger = SpendLedger(run, allocation=allocation)
        with pytest.raises(BudgetStopped):
            _reserve(ledger, bound="9")
        attempt = _reserve(ledger, bound="8")
        ledger.finish("cell", _receipt(attempt, cost="8"))
    assert allocation.snapshot()["reported_cost_usd"] == "25"
    pending, attempt, binding2 = _legacy(tmp_path, "pending", pending=True)
    allocation.import_run(binding2)
    assert allocation.snapshot()["reserved_usd"] == "10"
    assert allocation.snapshot()["unknown_attempts"] == []
    assert allocation.snapshot()["pending_attempts"] == [attempt]
    assert allocation.snapshot()["admission_stopped"]
    assert pending.events()[0]["attempt_id"] == attempt
    assert len(old.events()) == 2


def test_concurrent_attempts_share_one_atomic_total(tmp_path):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        def reserve(index):
            try:
                return _reserve(ledger, bound="10", cell=f"cell{index}")
            except BudgetStopped:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            attempts = list(pool.map(reserve, range(4)))
        assert sum(x is not None for x in attempts) == 2
        assert allocation.snapshot()["reserved_usd"] == "20"
        # Separate already-created ledger observers remain within one lease.
        ledger = SpendLedger(store, allocation=allocation)
        for index, attempt in enumerate(attempts):
            if attempt is not None:
                ledger.finish(f"cell{index}", _receipt(attempt, cost="10"))
    assert allocation.snapshot()["reported_cost_usd"] == "20"


@pytest.mark.parametrize("unknown_bound", ["0", "1"])
def test_unknown_even_free_attempt_stops_same_and_future_execution(tmp_path, unknown_bound):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        attempt = _reserve(ledger, bound=unknown_bound)
        ledger.finish("cell", _receipt(attempt, cost=None, status="unknown", status_code=404))
        with pytest.raises(BudgetStopped):
            _reserve(ledger, bound="0")
    fresh = _run(tmp_path, allocation, "future")
    with pytest.raises(BudgetStopped), AllocationLedger(allocation.directory).execution(fresh):
        pass
    assert fresh.events() == []
    assert allocation.snapshot()["unknown_attempts"] == [attempt]


def test_finished_actual_cost_breach_is_retained_without_clamp(tmp_path):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        attempt = _reserve(ledger, bound="1")
        ledger.finish("cell", _receipt(attempt, cost="30"))
    assert allocation.snapshot()["reported_cost_usd"] == "30"
    assert allocation.snapshot()["admission_stopped"]
    assert store.events()[-1]["receipt"]["cost_usd"] == "30"


@pytest.mark.parametrize("change", [{"requested_model": "other"}, {"endpoint": "https://other.invalid"}, {"request_hash": "other"}, {"cost_status": "local", "cost_usd": None}, {"cost_usd": "NaN"}, {"elapsed_s": float("inf")}, {"input_tokens": True}])
def test_malformed_receipt_keeps_global_original_reservation(tmp_path, change):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        attempt = _reserve(ledger, bound="10")
        with pytest.raises(ValueError):
            ledger.finish("cell", _receipt(attempt, **change))
        with pytest.raises(BudgetStopped):
            _reserve(ledger, bound="0")
    snapshot = allocation.snapshot()
    assert snapshot["reserved_usd"] == "10" and snapshot["reported_cost_usd"] == "0"
    assert snapshot["pending_attempts"] == [attempt] and snapshot["admission_stopped"]


def test_binding_limit_and_execution_identity_refuse_without_attempts(tmp_path):
    allocation = _allocation(tmp_path)
    with pytest.raises(ValueError, match="lease"):
        SpendLedger(_run(tmp_path, allocation), allocation=allocation)
    for index, metadata in enumerate(({"shared_allocation": {}}, {"budget_usd": "26"}, {"shared_allocation": {**allocation.identity(), "allocation_id": "other"}})):
        run = _run(tmp_path, allocation, f"wrong{index}", **metadata)
        with pytest.raises(ValueError), allocation.execution(run):
            pass
        assert run.events() == []
    run = _run(tmp_path, allocation, "valid")
    with allocation.execution(run):
        with pytest.raises(ValueError, match="frozen"):
            SpendLedger(run, limit="24", allocation=allocation)
        with pytest.raises(ValueError, match="nest"), allocation.execution(run):
            pass


@pytest.mark.parametrize("name", [".run.lock", ".journal.lock"])
def test_allocation_lock_replacement_even_same_bytes_refuses(tmp_path, name):
    allocation = _allocation(tmp_path)
    path = allocation.directory / name
    replacement = allocation.directory / "replacement"
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    with pytest.raises(ValueError, match="lock identity"):
        allocation.snapshot()
    with pytest.raises(ValueError, match="lock identity"):
        AllocationLedger(allocation.directory, read_only=True)


def test_symlink_lineage_and_parent_escape_do_not_create(tmp_path):
    target = tmp_path.resolve() / "real"
    target.mkdir()
    link = tmp_path.resolve() / "link"
    link.symlink_to(target, target_is_directory=True)
    for path in (link / "allocation", target / ".." / "escape"):
        with pytest.raises(ValueError, match="escape"):
            AllocationLedger.create(path, allocation_id="original")
    assert list(target.iterdir()) == []


def test_legacy_binding_schema_and_mutation_refuse_original_cut(tmp_path):
    old, _, binding = _legacy(tmp_path)
    allocation = _allocation(tmp_path, required=(binding,))
    for value in ({**binding.to_dict(), "extra": 1}, {**binding.to_dict(), "head_sha256": "0"}, {**binding.to_dict(), "directory": True}):
        with pytest.raises(ValueError):
            LegacyRunBinding.from_dict(value)
    with pytest.raises(ValueError, match="differs"):
        allocation.import_run(replace(binding, journal_tip="0" * 64))
    path = old.directory / "events.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        allocation.import_run(binding)
    assert allocation.store.events() == []


def test_duplicate_legacy_attempt_ids_and_malformed_journal_are_not_imported(tmp_path):
    first, attempt, binding = _legacy(tmp_path)
    allocation = _allocation(tmp_path)
    allocation.import_run(binding)
    second = RunStore.create_at(tmp_path.resolve() / "second", {"budget_usd": "25", "fixture": "other"})
    row = {k: v for k, v in first.events()[0].items() if k not in ("hash", "sequence", "previous", "timestamp")}
    second.append(row)
    assert row["attempt_id"] == attempt
    with pytest.raises(ValueError, match="collision"):
        allocation.import_run(LegacyRunBinding.capture(second.directory))
    malformed = second.directory / "events.jsonl"
    data = malformed.read_text()
    assert '"hosted":true' in data
    malformed.write_text(data.replace('"hosted":true', '"hosted":true,"hosted":false'))
    with pytest.raises(ValueError, match="duplicate"):
        LegacyRunBinding.capture(second.directory)


_CHILD = '''
import json, os, sys, time
from pathlib import Path
from daf_jev.benchmark_allocation import AllocationLedger
from daf_jev.benchmark_store import SpendLedger,RunStore
shared=AllocationLedger(Path(sys.argv[1]))
run=RunStore(Path(sys.argv[2]))
with shared.execution(run):
    if sys.argv[3]=='crash':
        ledger=SpendLedger(run,allocation=shared)
        ledger.reserve('cell','request','fixture','https://fixture.invalid/decision',True,'10')
        print('READY',flush=True)
        os._exit(23)
    print('READY',flush=True)
    time.sleep(30)
'''


def _child(allocation, store, mode):
    # Existing interpreter/current imported source, no optional deps/inference.
    return subprocess.Popen([sys.executable, "-c", _CHILD, str(allocation.directory), str(store.directory), mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_real_process_execution_lease_excludes_different_run_and_releases_os_lock(tmp_path):
    allocation = _allocation(tmp_path)
    first = _run(tmp_path, allocation, "first")
    second = _run(tmp_path, allocation, "second")
    child = _child(allocation, first, "hold")
    try:
        assert child.stdout.readline().strip() == "READY"
        with pytest.raises(BlockingIOError), AllocationLedger(allocation.directory).execution(second):
            pass
        assert second.events() == []
    finally:
        child.terminate()
        child.wait(timeout=10)
    with AllocationLedger(allocation.directory).execution(second):
        ledger = SpendLedger(second)
        assert not ledger.admissions
    assert allocation.snapshot()["bound_runs"] == 2


def test_real_crash_pending_start_is_never_reclaimed_by_new_object(tmp_path):
    allocation = _allocation(tmp_path)
    first = _run(tmp_path, allocation, "first")
    child = _child(allocation, first, "crash")
    assert child.communicate(timeout=10)[0].strip() == "READY"
    assert child.returncode == 23
    fresh = AllocationLedger(allocation.directory)
    snapshot = fresh.snapshot()
    assert snapshot["reserved_usd"] == "10" and snapshot["admission_stopped"]
    second = _run(tmp_path, allocation, "second")
    with pytest.raises(BudgetStopped), fresh.execution(second):
        pass
    assert second.events() == []


def test_global_finish_requires_actual_per_run_finish_first(tmp_path):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        attempt = _reserve(ledger, bound="10")
        with pytest.raises(ValueError, match="durable per-run"):
            allocation.finish(store, "cell", _receipt(attempt))
    assert allocation.snapshot()["reserved_usd"] == "10"


def test_global_receipt_field_forgery_and_unbacked_hosted_intent_refuse(tmp_path):
    allocation = _allocation(tmp_path)
    store = _run(tmp_path, allocation)
    with allocation.execution(store):
        ledger = SpendLedger(store, allocation=allocation)
        attempt = _reserve(ledger, bound="10")
        ledger.finish("cell", _receipt(attempt))
    # Real valid hash chain, but a fabricated accounting payload cannot override
    # the immutable per-run receipt. Constructing another ledger is not a repair.
    directory = tmp_path.resolve() / "forged"
    forged = AllocationLedger.create(directory, allocation_id="other")
    run = _run(tmp_path, forged, "forged-run")
    with forged.execution(run):
        SpendLedger(run).reserve("cell", "request", "fixture", ENDPOINT, True, "1")
    with pytest.raises(ValueError, match="global reservation"):
        forged.snapshot()
    assert allocation.snapshot()["reported_cost_usd"] == "1"


_DURABILITY = '''
import json, os, sys
from pathlib import Path
from daf_jev.benchmark_allocation import AllocationLedger
from daf_jev.benchmark_store import RunStore, SpendLedger
from daf_jev.decision_backends import CallReceipt,utc_now
shared=AllocationLedger(Path(sys.argv[1]))
run=RunStore(Path(sys.argv[2]))
try:
    with shared.execution(run):
        spend=SpendLedger(run,allocation=shared)
        if sys.argv[3]=='start':
            os.chmod(run.directory,0o500)
            spend.reserve('cell','request','fixture','https://fixture.invalid/decision',True,'10')
        else:
            attempt=spend.reserve('cell','request','fixture','https://fixture.invalid/decision',True,'10')
            os.chmod(shared.directory,0o500)
            spend.finish('cell',CallReceipt(attempt,utc_now(),'https://fixture.invalid/decision','fixture',None,None,None,'request',.1,200,None,None,'1','reported'))
except (OSError,ValueError) as error:
    print(json.dumps({'error':type(error).__name__}),flush=True)
else:
    raise SystemExit('expected real filesystem failure')
finally:
    os.chmod(run.directory,0o700)
    os.chmod(shared.directory,0o700)
'''


@pytest.mark.parametrize("stage", ["start", "finish"])
def test_actual_head_write_failure_never_releases_global_reservation(tmp_path, stage):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    if stage == "start":
        run.append({"event": "fixture_padding", "padding": "x" * 6000})
    result = subprocess.run([sys.executable, "-c", _DURABILITY, str(allocation.directory), str(run.directory), stage], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert '"error"' in result.stdout
    if stage == "start":
        observed = AllocationLedger(allocation.directory)
        starts = [r for r in observed.store.events() if r["event"] == "allocation_attempt_started"]
        assert len(starts) == 1
        assert observed._reservations[starts[0]["attempt_id"]] == 10
        with pytest.raises(ValueError):
            observed.snapshot()  # the per-run partial write remains invalid
        with pytest.raises(ValueError):
            RunStore(run.directory, read_only=True)
    else:
        # Local finish committed FIRST; the torn global finish is not repaired
        # or retried, and no new AllocationLedger can admit an attempt.
        local = SpendLedger(RunStore(run.directory, read_only=True))
        assert len(local.finished) == 1 and local.snapshot()["reported_cost_usd"] == "1"
        with pytest.raises(ValueError):
            AllocationLedger(allocation.directory)
        raw = (allocation.directory / "events.jsonl").read_bytes()
        assert b'"allocation_attempt_started"' in raw
        assert b'"allocation_attempt_finished"' in raw
        assert raw.endswith(b"\n")  # journal append completed but tip publication failed


def test_existing_unaccounted_hosted_run_cannot_be_rebound_as_fresh(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    SpendLedger(run).reserve("cell", "request", "fixture", ENDPOINT, True, "1")
    with pytest.raises(ValueError, match="global"), allocation.execution(run):
        pytest.fail("an existing unbacked intent is not a fresh shared run")


def test_legacy_zero_bound_unknown_is_still_required_blocking_evidence(tmp_path):
    old, attempt, binding = _legacy(tmp_path, cost=None, status="unknown", bound="0")
    allocation = _allocation(tmp_path, required=(binding,))
    allocation.import_run(binding)
    snapshot = allocation.snapshot()
    assert snapshot["reserved_usd"] == "0" and snapshot["unknown_attempts"] == [attempt]
    assert snapshot["admission_stopped"]
    assert old.events()[1]["receipt"]["cost_usd"] is None


def test_global_finished_payload_cannot_forge_cost_from_valid_run_receipt(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with pytest.raises(ValueError, match="receipt changed"), allocation.execution(run):
        spend = SpendLedger(run, allocation=allocation)
        attempt = _reserve(spend, bound="10")
        # Durable per-run completion without the shared observer, to test the
        # global reducer independently from the normal production finish path.
        SpendLedger(run).finish("cell", _receipt(attempt, cost="5"))
        row = run.events()[-1]
        from daf_jev.decision_backends import content_hash
        allocation.store.append({"event": "allocation_attempt_finished", "run_manifest_hash": run.manifest_hash,
            "attempt_id": attempt, "cell_id": "cell", "receipt_sha256": content_hash(row["receipt"]),
            "run_event_hash": row["hash"], "cost_status": "reported", "cost_usd": "0"})
        with pytest.raises(ValueError, match="receipt changed"):
            _reserve(spend, bound="25")
        assert len(spend.admissions) == 1
        assert allocation._reservations[attempt] == 10
    with pytest.raises(ValueError, match="receipt changed"):
        AllocationLedger(allocation.directory, read_only=True).snapshot()


@pytest.mark.parametrize("event", [
    {"event": "foreign"},
    {"event": "allocation_stopped", "reason": "refunded"},
    {"event": "allocation_stopped", "reason": "invalid_receipt", "cost_usd": "0"},
    {"event": "allocation_run_bound", "binding": {"manifest_hash": "0" * 64}},
    {"event": "allocation_run_bound", "binding": True},
    {"event": "allocation_attempt_started", "attempt_id": "unbound"},
])
def test_malformed_but_hash_valid_allocation_events_refuse(tmp_path, event):
    allocation = _allocation(tmp_path)
    allocation.store.append(event)
    with pytest.raises(ValueError):
        AllocationLedger(allocation.directory, read_only=True)


def test_shared_observer_reconstruction_with_current_pending_is_not_old_crash(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with allocation.execution(run):
        first = SpendLedger(run, allocation=allocation)
        attempt1 = _reserve(first, bound="10", cell="first")
        second = SpendLedger(run, allocation=allocation)
        attempt2 = _reserve(second, bound="10", cell="second")
        second.finish("second", _receipt(attempt2, cost="10"))
        first.finish("first", _receipt(attempt1, cost="10"))
    assert allocation.snapshot()["reported_cost_usd"] == "20"


def test_run_manifest_or_lock_changes_cannot_release_global_pending(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with allocation.execution(run):
        ledger = SpendLedger(run, allocation=allocation)
        attempt = _reserve(ledger, bound="10")
        replacement = run.directory / "replacement"
        lock = run.directory / ".journal.lock"
        replacement.write_bytes(lock.read_bytes())
        os.replace(replacement, lock)
        with pytest.raises(ValueError, match="lock identity"):
            ledger.finish("cell", _receipt(attempt))
    assert allocation._reservations[attempt] == 10
    with pytest.raises(ValueError, match="lock identity"):
        allocation.snapshot()


def test_replayed_reservation_cannot_violate_cap_or_required_imports(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with pytest.raises(ValueError, match="violates"), allocation.execution(run):
        ledger = SpendLedger(run, allocation=allocation)
        _reserve(ledger, bound="20")
        allocation.store.append({"event": "allocation_attempt_started", "run_manifest_hash": run.manifest_hash,
            "attempt_id": "forged-extra", "cell_id": "cell", "request_hash": "request", "model": "fixture", "endpoint": ENDPOINT, "liability_usd": "10"})
        with pytest.raises(ValueError, match="violates"):
            allocation.snapshot()
        # End-of-lease rereads the same malformed retained row and fails closed.
        with pytest.raises(ValueError, match="violates"):
            allocation._sync()


@pytest.mark.parametrize("change", [
    {"liability_usd": "0"}, {"model": "other"}, {"endpoint": "https://other.invalid"},
    {"request_hash": "other"}, {"cell_id": "other"}, {"hosted": False},
])
def test_active_forged_start_cannot_admit_next_attempt_or_release_cost(tmp_path, change):
    allocation = _allocation(tmp_path)
    prior = _run(tmp_path, allocation, "prior")
    prior_cost = "19" if "liability_usd" in change else "0"
    with allocation.execution(prior):
        spend = SpendLedger(prior, allocation=allocation)
        attempt = _reserve(spend, bound=prior_cost)
        spend.finish("cell", _receipt(attempt, cost=prior_cost))
    current = _run(tmp_path, allocation, "current")
    with allocation.execution(current):
        local = SpendLedger(current)
        attempt = _reserve(local, bound="20", hosted=change.get("hosted", True))
        actual = local.admissions[attempt]
        allocation.store.append({"event": "allocation_attempt_started", "run_manifest_hash": current.manifest_hash,
            "attempt_id": attempt, "cell_id": change.get("cell_id", "cell"), "request_hash": change.get("request_hash", "request"),
            "model": change.get("model", "fixture"), "endpoint": change.get("endpoint", ENDPOINT),
            "liability_usd": change.get("liability_usd", actual["liability_usd"])})
        spend = SpendLedger(current, allocation=allocation)
        with pytest.raises(ValueError, match="pair mismatch"):
            _reserve(spend, bound="5", cell="next")
        assert len(current.events()) == 1
        assert len(spend.admissions) == 1 and str(allocation._charged) == prior_cost
        # Per-run finish is durable first, but this invalid global pairing must
        # still not release/reconcile the disputed reservation.
        value = _receipt(attempt, cost=None, status="local") if not actual["hosted"] else _receipt(attempt)
        local.finish("cell", value)
        with pytest.raises(ValueError, match="pair mismatch"):
            allocation.finish(current, "cell", value)
    with pytest.raises(ValueError, match="admission mismatch"):
        AllocationLedger(allocation.directory, read_only=True).snapshot()


def test_only_current_atomic_global_first_intent_may_be_transiently_unpaired(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with allocation.execution(run):
        allocation.reserve(run, "original", "cell", "request", "fixture", ENDPOINT, "10")
        assert allocation._reservations == {"original": 10}
        before = run.events()
        spend = SpendLedger(run, allocation=allocation)
        with pytest.raises(ValueError, match="pair mismatch"):
            _reserve(spend, bound="1")
        assert run.events() == before == []
    assert allocation.snapshot()["pending_attempts"] == ["original"]
    assert allocation.snapshot()["admission_stopped"]


def test_active_unbacked_hosted_intent_blocks_next_admission(tmp_path):
    allocation = _allocation(tmp_path)
    run = _run(tmp_path, allocation)
    with allocation.execution(run):
        local = SpendLedger(run)
        original = _reserve(local, bound="20")
        shared = SpendLedger(run, allocation=allocation)
        with pytest.raises(ValueError, match="global reservation"):
            _reserve(shared, bound="5", cell="next")
        assert list(shared.admissions) == [original]
        assert len(run.events()) == 1
        assert not any(r["event"] == "allocation_attempt_started" for r in allocation.store.events())
    with pytest.raises(ValueError, match="global reservation"):
        allocation.snapshot()


@pytest.mark.parametrize("inject_global", [False, True])
def test_new_foreign_run_intent_cannot_escape_current_executor_pair_guard(tmp_path, inject_global):
    allocation = _allocation(tmp_path)
    prior = _run(tmp_path, allocation, "prior")
    with allocation.execution(prior):
        spend = SpendLedger(prior, allocation=allocation)
        original = _reserve(spend, bound="19")
        spend.finish("cell", _receipt(original, cost="19"))
    current = _run(tmp_path, allocation, "current")
    failure = "another executor" if inject_global else "global reservation"
    outer = pytest.raises(ValueError, match="another executor") if inject_global else contextlib.nullcontext()
    with outer, allocation.execution(current):
        # A valid hash-linked new intent in another retained run is untrusted
        # evidence even when the foreign OS run lease is not currently held.
        foreign = SpendLedger(prior)
        attempt = _reserve(foreign, bound="4", cell="foreign")
        if inject_global:
            allocation.store.append({"event": "allocation_attempt_started", "run_manifest_hash": prior.manifest_hash,
                "attempt_id": attempt, "cell_id": "foreign", "request_hash": "request", "model": "fixture", "endpoint": ENDPOINT, "liability_usd": "0"})
        current_spend = SpendLedger(current, allocation=allocation)
        with pytest.raises(ValueError, match=failure):
            _reserve(current_spend, bound="5")
        assert current.events() == [] and allocation._charged == 19
    with pytest.raises(ValueError):
        AllocationLedger(allocation.directory, read_only=True).snapshot()
