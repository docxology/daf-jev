"""Adversarial custody and budget checks using real files and processes."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from daf_jev.benchmark_store import (
    BudgetStopped,
    RunStore,
    SpendLedger,
    currency_context,
    usd,
)
from daf_jev.decision_backends import CallReceipt, canonical_json, content_hash, utc_now

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def _store(tmp_path: Path) -> RunStore:
    # macOS's default temporary-directory ancestors have system-owned aliases.
    # Resolve the fixture input before exercising the store's no-symlink contract.
    return RunStore.create(tmp_path.resolve(), {"budget_usd": "25", "fixture": True})


def _admit(ledger: SpendLedger, *, bound: str = "25", hosted: bool = True) -> str:
    return ledger.reserve("cell", "request-hash", "fixture", ENDPOINT, hosted, bound)


def _receipt(attempt: str, *, cost: str | None = "1", status: str = "reported") -> CallReceipt:
    return CallReceipt(attempt, utc_now(), ENDPOINT, "fixture", "fixture", "fixture-provider",
                       "fixture-response", "request-hash", .01, 200, 1, 1, cost, status)


@pytest.mark.parametrize("value", [True, -1, "NaN", "Infinity", "-Infinity", "1E1000000"])
def test_unsupported_usd_rejects_before_accounting(value):
    with pytest.raises(ValueError):
        usd(value)


def test_supported_usd_preserves_exact_decimal():
    assert usd("0.00000001") == Decimal("0.00000001")
    assert usd("25.00") == Decimal("25.00")


def test_currency_policy_uses_fresh_context_independent_of_ambient_state():
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 1
        ambient.traps[Inexact] = True
        with localcontext(currency_context()) as currency:
            assert currency.prec == 50 and currency.Emax == 999999 and currency.Emin == -999999
            assert not currency.traps[Inexact] and not any(currency.flags.values())
            assert Decimal("100000000") + Decimal(".1") == Decimal("100000000.1")
            assert str(Decimal(1) / Decimal(3)) == "0." + "3" * 50
        assert ambient.prec == 2 and ambient.traps[Inexact]
    first, second = currency_context(), currency_context()
    first.prec = 1
    assert second.prec == 50


def test_exact_ledger_budget_and_rebuild_ignore_hostile_decimal_context(tmp_path):
    store = _store(tmp_path)
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.Emax = 1
        ambient.traps[Inexact] = True
        ledger = SpendLedger(store, limit="0.300000000000000003")
        first = _admit(ledger, bound="0.100000000000000001")
        ledger.finish("cell", _receipt(first, cost="0.100000000000000001"))
        second = _admit(ledger, bound="0.200000000000000002")
        assert ledger.snapshot()["reserved_usd"] == "0.200000000000000002"
        ledger.finish("cell", _receipt(second, cost="0.200000000000000002"))
        assert ledger.snapshot()["reported_cost_usd"] == "0.300000000000000003"
        with pytest.raises(BudgetStopped, match="exhausted"):
            _admit(ledger, bound="0.000000000000000001")
        rebuilt = SpendLedger(RunStore(store.directory), limit="0.300000000000000003")
        assert rebuilt.snapshot()["reported_cost_usd"] == "0.300000000000000003"
        assert rebuilt.snapshot()["reserved_usd"] == "0"


def test_independent_ledgers_share_atomic_admission(tmp_path):
    store = _store(tmp_path)
    first = SpendLedger(store)
    second = SpendLedger(RunStore(store.directory))
    _admit(first)
    with pytest.raises(BudgetStopped):
        second.reserve("second", "different", "fixture", ENDPOINT, True, "25")
    assert len(store.events()) == 1
    assert second.snapshot()["reserved_usd"] == "25"


def test_real_processes_cannot_each_admit_the_whole_budget(tmp_path):
    store = _store(tmp_path)
    code = """
import json, sys, time
from pathlib import Path
from daf_jev.benchmark_store import RunStore, SpendLedger, BudgetStopped
directory, ready = Path(sys.argv[1]), Path(sys.argv[2])
ledger = SpendLedger(RunStore(directory))
ready.touch()
deadline = time.monotonic() + 5
while not (directory / 'release').exists():
    if time.monotonic() > deadline:
        raise RuntimeError('fixture barrier timeout')
    time.sleep(.005)
try:
    ledger.reserve(ready.name, 'fixture-hash', 'fixture', 'https://openrouter.ai/api/v1/chat/completions', True, '25')
    admitted = True
except BudgetStopped:
    admitted = False
print(json.dumps({'admitted': admitted}))
"""
    source = Path(__file__).resolve().parents[2] / "src"
    ready = [store.directory / f"ready-{i}" for i in range(2)]
    processes = [subprocess.Popen(
        [sys.executable, "-c", code, str(store.directory), str(path)],
        cwd=store.directory, env={"PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for path in ready]
    try:
        deadline = time.monotonic() + 5
        while not all(path.exists() for path in ready):
            if time.monotonic() > deadline:
                pytest.fail("fixture processes did not reach admission barrier")
            time.sleep(.005)
        (store.directory / "release").touch()
        outputs = [process.communicate(timeout=5) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
        assert sorted(json.loads(stdout)["admitted"] for stdout, _ in outputs) == [False, True]
        assert SpendLedger(RunStore(store.directory)).snapshot()["reserved_usd"] == "25"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


@pytest.mark.parametrize("change", [
    {"attempt_id": "unadmitted"}, {"request_hash": "unrelated"},
    {"requested_model": "other-model"}, {"endpoint": "http://127.0.0.1/other"},
    {"cost_status": "local", "cost_usd": None}, {"cost_status": "invented"},
    {"cost_status": "unknown", "cost_usd": "0"},
])
def test_receipt_cannot_release_an_unrelated_hosted_admission(tmp_path, change):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger)
    with pytest.raises(ValueError):
        ledger.finish("cell", replace(_receipt(attempt), **change))
    assert [event["event"] for event in store.events()] == ["attempt_started", "accounting_rejected"]
    assert ledger.snapshot()["reserved_usd"] == "25"
    assert ledger.snapshot()["admission_stopped"]


def test_receipt_must_match_the_admitted_cell(tmp_path):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger)
    with pytest.raises(ValueError, match="identity"):
        ledger.finish("other-cell", _receipt(attempt))
    assert [event["event"] for event in store.events()] == ["attempt_started", "accounting_rejected"]
    assert ledger.snapshot()["admission_stopped"]


def test_reported_charge_reconciles_shared_ledgers_and_cannot_finish_twice(tmp_path):
    store = _store(tmp_path)
    first, second = SpendLedger(store), SpendLedger(RunStore(store.directory))
    attempt = _admit(first)
    second.finish("cell", _receipt(attempt, cost="0.125"))
    snapshot = first.snapshot()
    assert snapshot["reported_cost_usd"] == "0.125"
    assert snapshot["reserved_usd"] == "0"
    assert snapshot["unresolved_attempts"] == []
    with pytest.raises(ValueError, match="unfinished"):
        first.finish("cell", _receipt(attempt))
    assert [event["event"] for event in store.events()] == ["attempt_started", "attempt_finished", "accounting_rejected"]
    assert first.snapshot()["admission_stopped"]


def test_overage_is_retained_and_stops_new_admission(tmp_path):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger, bound="2")
    ledger.finish("cell", _receipt(attempt, cost="3"))
    assert ledger.snapshot()["reported_cost_usd"] == "3"
    assert ledger.snapshot()["admission_stopped"]
    with pytest.raises(BudgetStopped):
        _admit(ledger, bound="0")
    assert SpendLedger(RunStore(store.directory)).snapshot()["admission_stopped"]


def test_extreme_finite_cost_never_leaves_paid_admission_open(tmp_path):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger, bound="0")
    with pytest.raises(ValueError):
        ledger.finish("cell", _receipt(attempt, cost="1E1000000"))
    assert ledger.snapshot()["admission_stopped"]
    with pytest.raises(BudgetStopped):
        _admit(ledger, bound="0")
    assert SpendLedger(RunStore(store.directory)).snapshot()["admission_stopped"]


@pytest.mark.parametrize("change", [
    {"elapsed_s": float("nan")}, {"elapsed_s": float("inf")}, {"elapsed_s": -1},
    {"elapsed_s": True}, {"elapsed_s": 10 ** 400}, {"input_tokens": -1}, {"output_tokens": True},
    {"output_tokens": .5}, {"status_code": True}, {"status_code": 99},
    {"status_code": 600},
])
def test_invalid_receipt_numbers_latch_stop_without_poisoning_the_journal(tmp_path, change):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger, bound="0")
    with pytest.raises(ValueError):
        ledger.finish("cell", replace(_receipt(attempt, cost="0"), **change))
    assert [event["event"] for event in store.events()] == ["attempt_started", "accounting_rejected"]
    assert ledger.snapshot()["admission_stopped"]
    with pytest.raises(BudgetStopped):
        _admit(ledger, bound="0")
    resumed = SpendLedger(RunStore(store.directory))
    assert resumed.snapshot()["admission_stopped"]
    assert resumed.snapshot()["unresolved_attempts"] == [attempt]


def test_unknown_billing_remains_reserved_and_stops_resume(tmp_path):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger, bound="2")
    ledger.finish("cell", _receipt(attempt, cost=None, status="unknown"))
    for value in (ledger, SpendLedger(RunStore(store.directory))):
        snapshot = value.snapshot()
        assert snapshot["reserved_usd"] == "2"
        assert snapshot["unresolved_attempts"] == [attempt]
        assert snapshot["admission_stopped"]
        with pytest.raises(BudgetStopped):
            _admit(value, bound="0")


def test_unfinished_admission_blocks_resume_even_at_zero_bound(tmp_path):
    store = _store(tmp_path)
    _admit(SpendLedger(store), bound="0")
    resumed = SpendLedger(RunStore(store.directory))
    assert resumed.snapshot()["admission_stopped"]
    with pytest.raises(BudgetStopped):
        _admit(resumed, bound="0")


def test_local_receipt_releases_only_local_hosted_usd_liability(tmp_path):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger, hosted=False)
    ledger.finish("cell", _receipt(attempt, cost=None, status="local"))
    assert ledger.snapshot()["reserved_usd"] == "0"
    assert not ledger.snapshot()["admission_stopped"]


@pytest.mark.parametrize("name", ["events.jsonl", "head.json", "manifest.json"])
def test_existing_store_rejects_files_replaced_with_outside_symlinks(tmp_path, name):
    store = _store(tmp_path)
    store.append({"event": "fixture"})
    target = store.directory / name
    outside = tmp_path.resolve() / f"outside-{name}"
    original = target.read_bytes()
    outside.write_bytes(original)
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        store.events()
    with pytest.raises(ValueError, match="symlink"):
        RunStore(store.directory)
    assert outside.read_bytes() == original


@pytest.mark.parametrize("in_memory", [False, True])
def test_manifest_mutation_invalidates_every_consumption(tmp_path, in_memory):
    store = _store(tmp_path)
    if in_memory:
        before = store.manifest_hash
        with pytest.raises(ValueError, match="immutable manifest"):
            store.manifest["budget_usd"] = "26"
        assert store.manifest_hash == before
        assert store.events() == []
        store.append({"event": "fixture"})
        assert store.events()[0]["event"] == "fixture"
        return
    else:
        (store.directory / "manifest.json").write_text('{"budget_usd":"26"}')
    with pytest.raises(ValueError, match="manifest changed"):
        store.events()
    with pytest.raises(ValueError, match="manifest changed"):
        store.append({"event": "fixture"})


@pytest.mark.parametrize("attribute", ["manifest", "manifest_hash"])
def test_manifest_attribute_replacement_cannot_bypass_constant_time_custody(tmp_path, attribute):
    store = _store(tmp_path)
    replacement = json.loads((store.directory / "manifest.json").read_text())
    replacement["budget_usd"] = "26"
    setattr(store, attribute, replacement if attribute == "manifest" else "replaced-hash")
    with pytest.raises(ValueError, match="manifest changed"):
        store.events()
    with pytest.raises(ValueError, match="manifest changed"):
        store.append({"event": "fixture"})


def test_nested_manifest_freeze_preserves_original_json_hash_and_rejects_edits(tmp_path):
    store = RunStore.create(tmp_path.resolve(), {"budget_usd": "25",
        "backends": [{"id": "fixture", "options": {"max_tokens": 8}}]})
    original = json.loads((store.directory / "manifest.json").read_text())
    assert content_hash(store.manifest) == content_hash(original) == store.manifest_hash
    with pytest.raises(ValueError, match="immutable manifest"):
        store.manifest["backends"][0]["options"]["max_tokens"] = 1000000
    with pytest.raises(TypeError):
        store.manifest["backends"][0] = {"id": "replacement"}
    store.append({"event": "fixture"})
    assert RunStore(store.directory).events() == store.events()


def test_truncated_journal_does_not_fall_back_to_last_parseable_record(tmp_path):
    store = _store(tmp_path)
    store.append({"event": "first"})
    store.append({"event": "second"})
    journal = store.directory / "events.jsonl"
    first = journal.read_text().splitlines()[0]
    journal.write_text(first + "\n")
    with pytest.raises(ValueError, match="tip mismatch"):
        store.events()
    with pytest.raises(ValueError, match="tip mismatch"):
        RunStore(store.directory)


def test_coherent_prefix_truncation_cannot_erase_consumed_history(tmp_path):
    store = _store(tmp_path)
    store.append({"event": "first"})
    store.append({"event": "second"})
    first = store.events()[0]
    (store.directory / "events.jsonl").write_text(canonical_json(first) + "\n")
    (store.directory / "head.json").write_text(canonical_json({"sequence": 1, "hash": first["hash"]}))
    with pytest.raises(ValueError, match="history changed"):
        store.events()


def test_returned_events_and_caller_event_data_cannot_mutate_retained_history(tmp_path):
    store = _store(tmp_path)
    event = {"event": "fixture", "payload": {"value": "original"}}
    store.append(event)
    event["payload"]["value"] = "caller-mutated"
    returned = store.events()
    returned[0]["payload"]["value"] = "result-mutated"
    actual = store.events()[0]
    assert actual["payload"]["value"] == "original"
    digest = actual.pop("hash")
    assert content_hash(actual) == digest


def test_external_append_after_frozen_backend_profile_preserves_ledger_reconciliation(tmp_path):
    store = RunStore.create(tmp_path.resolve(), {"budget_usd": "25", "backends": [
        {"id": "fixture", "artifact": {"launch_args": ["public-fixture-runtime", "--layers", [1, 2]],
                                        "capabilities": {"primitives": ["noul", "choice"]}}}
    ]})
    profile = store.manifest["backends"][0]["artifact"]
    assert isinstance(profile["launch_args"], tuple)
    ledger = SpendLedger(store)
    store.append({"event": "backend_ready", "backend": "fixture", "profile": profile})
    attempt = _admit(ledger, bound="1")

    external = RunStore(store.directory)
    prefix = external.events()
    external.append({"event": "source_snapshot_retained", "files": [
        {"path": "src/public-fixture.py", "sha256": "public-fixture-source-hash"}
    ]})
    ledger.finish("cell", _receipt(attempt, cost="0.25"))

    events = store.events()
    assert events[:len(prefix)] == prefix
    assert events == external.events() == RunStore(store.directory).events()
    assert [row["event"] for row in events] == [
        "backend_ready", "attempt_started", "source_snapshot_retained", "attempt_finished"
    ]
    assert events[0]["profile"] == json.loads(canonical_json(profile))
    assert isinstance(events[0]["profile"]["launch_args"], list)
    assert isinstance(events[0]["profile"]["launch_args"][2], list)
    assert ledger.snapshot() == {"limit_usd": "25", "reported_cost_usd": "0.25", "reserved_usd": "0",
                                "unresolved_attempts": [], "admission_stopped": False}


@pytest.mark.parametrize("field", ["sequence", "previous", "hash", "timestamp"])
def test_append_cannot_override_journal_custody_fields(tmp_path, field):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="custody"):
        store.append({"event": "fixture", field: "override"})
    assert store.events() == []


def test_executor_lease_is_exclusive_between_independent_stores(tmp_path):
    store = _store(tmp_path)
    other = RunStore(store.directory)
    with store.lease(), pytest.raises(BlockingIOError), other.lease():
        pytest.fail("second executor unexpectedly acquired the same run")


@pytest.mark.parametrize("name", [".run.lock", ".journal.lock"])
def test_unlinked_active_lock_cannot_be_recreated_to_bypass_ownership(tmp_path, name):
    store = _store(tmp_path)
    other = RunStore(store.directory)
    acquire = store.lease if name == ".run.lock" else store.transaction
    acquire_other = other.lease if name == ".run.lock" else other.transaction
    with acquire():
        (store.directory / name).unlink()
        with pytest.raises((ValueError, FileNotFoundError)), acquire_other():
            pytest.fail("replacement lock granted simultaneous ownership")


def test_copied_run_supports_read_only_audit_but_cannot_assume_executor_identity(tmp_path):
    original = _store(tmp_path)
    ledger = SpendLedger(original)
    attempt = _admit(ledger, bound="2")
    ledger.finish("cell", _receipt(attempt, cost="1"))
    copied = tmp_path.resolve() / "copied-run"
    shutil.copytree(original.directory, copied)
    with pytest.raises(ValueError, match="lock identity"):
        RunStore(copied)
    audit = RunStore(copied, read_only=True)
    assert audit.manifest_hash == original.manifest_hash
    assert audit.events() == original.events()
    before = {path.name: path.read_bytes() for path in copied.iterdir()}
    audited = SpendLedger(audit)
    assert audited.snapshot()["reported_cost_usd"] == "1"
    with pytest.raises(ValueError, match="read-only"):
        audit.append({"event": "forbidden"})
    with pytest.raises(ValueError, match="read-only"), audit.lease():
        pytest.fail("audit acquired executor ownership")
    with pytest.raises(ValueError, match="read-only"):
        _admit(audited, bound="0")
    assert {path.name: path.read_bytes() for path in copied.iterdir()} == before


@pytest.mark.parametrize("name", ["manifest.json", "events.jsonl", "head.json"])
def test_stored_duplicate_json_keys_reject_without_rewriting_evidence(tmp_path, name):
    store = _store(tmp_path)
    store.append({"event": "fixture"})
    path = store.directory / name
    original = path.read_text()
    if name == "manifest.json":
        malformed = original.replace('"budget_usd":"25"', '"budget_usd":"100","budget_usd":"25"')
    elif name == "events.jsonl":
        malformed = original.replace('"event":"fixture"', '"event":"attempt_finished","event":"fixture"')
    else:
        malformed = original.replace('"sequence":1', '"sequence":99,"sequence":1')
    assert malformed != original
    path.write_text(malformed)
    before = {file.name: file.read_bytes() for file in store.directory.iterdir()}
    with pytest.raises(ValueError, match="duplicate"):
        RunStore(store.directory, read_only=True)
    assert {file.name: file.read_bytes() for file in store.directory.iterdir()} == before


@pytest.mark.parametrize("key", ['"cost_usd"', '"cost_\\u0075sd"'])
def test_ambiguous_nested_reported_cost_cannot_release_paid_liability(tmp_path, key):
    store = _store(tmp_path)
    ledger = SpendLedger(store)
    attempt = _admit(ledger)
    ledger.finish("cell", _receipt(attempt, cost="0"))
    journal = store.directory / "events.jsonl"
    original = journal.read_text()
    # Last-key-wins would retain the original canonical row/hash/head and
    # report zero despite the conflicting over-budget charge in the same row.
    malformed = original.replace('"cost_usd":"0"', f'"cost_usd":"100",{key}:"0"')
    assert malformed != original
    journal.write_text(malformed)
    before = {file.name: file.read_bytes() for file in store.directory.iterdir()}
    with pytest.raises(ValueError, match="duplicate"):
        SpendLedger(RunStore(store.directory, read_only=True))
    assert {file.name: file.read_bytes() for file in store.directory.iterdir()} == before


@pytest.mark.parametrize("name", ["manifest.json", "events.jsonl", "head.json"])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_stored_nonstandard_json_constants_reject_without_rewriting(tmp_path, name, constant):
    store = _store(tmp_path)
    store.append({"event": "fixture"})
    path = store.directory / name
    raw = path.read_text().replace("{", f'{{"invalid":{constant},', 1)
    path.write_text(raw)
    before = {file.name: file.read_bytes() for file in store.directory.iterdir()}
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        RunStore(store.directory, read_only=True)
    assert {file.name: file.read_bytes() for file in store.directory.iterdir()} == before
