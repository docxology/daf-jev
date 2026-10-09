"""Reviewed legacy liability holds over real journals; no provider calls."""
from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import CallReceipt, content_hash, utc_now

ENDPOINT = "https://fixture.invalid/decisions"


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes(path):
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


def _receipt(attempt, *, status="unknown", cost=None):
    return CallReceipt(attempt, utc_now(), ENDPOINT, "native-fixture", None, None,
                       None, "request", .01, 404, None, None, cost, status)


def _legacy(path, *, bounds=("0",), run_limit="25", pending=False, rejected=False):
    store = RunStore.create_at(path, {"budget_usd": run_limit, "fixture": str(path)})
    ledger = SpendLedger(store)
    attempts = [ledger.reserve("cell", "request", "native-fixture", ENDPOINT, True, b) for b in bounds]
    if not pending:
        for a in attempts:
            ledger.finish("cell", _receipt(a))
    if rejected:
        store.append({"event": "accounting_rejected", "reason": "retained-structural-stop"})
    return store, attempts, LegacyRunBinding.capture(path)


def _case(tmp_path, *, bound="0", run_limit="25", limit="25", rejected=False, bounds=None):
    old, attempts, binding = _legacy(tmp_path / "old", bounds=bounds or (bound,), run_limit=run_limit, rejected=rejected)
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="same-25",
                                         limit=limit, required_imports=(binding,))
    allocation.import_run(binding)
    return allocation, old, attempts, binding


def _proofs(tmp_path, allocation, attempt, binding, *, bound="0", reduction=False, suffix="", reference=None):
    target = allocation.reconciliation_target(binding.manifest_hash, attempt)
    reference = reference or "contract-" + attempt
    document = {"format": "dafjev.exact-request-tariff-bound/1", "scope": "exact_finished_attempt_upper_bound",
                "authority": "fixture-contract", "reference": reference, "request": target["attempt"],
                "currency": "USD", "upper_bound_usd": bound,
                "rationale": "Independent fixture contract establishes the exact complete request liability."}
    doc = tmp_path / f"document{suffix}.json"
    doc_hash = _write(doc, document)
    evidence = {"format": "dafjev.bounded-unknown-evidence/1", "scope": "exact_finished_attempt_upper_bound",
                "target": target, "source_kind": "reviewed_request_tariff_contract",
                "authority": "fixture-contract", "reference": reference, "collected_by": "fixture-collector",
                "currency": "USD", "upper_bound_usd": bound,
                "document": {"path": str(doc), "sha256": doc_hash, "bytes": doc.stat().st_size}}
    proof = tmp_path / f"evidence{suffix}.json"
    evidence_hash = _write(proof, evidence)
    review = {"format": "dafjev.bounded-unknown-review/1", "decision": "approve_bounded_unknown_continuation",
              "reviewer": "independent-fixture-reviewer", "evidence_sha256": evidence_hash,
              "document_sha256": doc_hash, "allocation_tip": target["allocation"]["journal_tip"],
              "target_sha256": content_hash(target), "contract_origin_verified": True,
              "unique_exact_attempt_verified": True, "upper_bound_verified": True,
              "original_reservation_reduction_verified": reduction,
              "rationale": "The exact request and source contract support this liability bound; charge stays UNKNOWN."}
    reviewed = tmp_path / f"review{suffix}.json"
    review_hash = _write(reviewed, review)
    return {"evidence": proof, "evidence_sha256": evidence_hash, "review": reviewed, "review_sha256": review_hash}


def _change(kwargs, file, update):
    value = json.loads(kwargs[file].read_text())
    update(value)
    kwargs[file + "_sha256"] = _write(kwargs[file], value)
    if file == "evidence":
        _change(kwargs, "review", lambda r: r.update(evidence_sha256=kwargs["evidence_sha256"]))


def _exact_proofs(tmp_path, allocation, attempt, binding, *, cost="0", suffix="-exact"):
    kwargs = _proofs(tmp_path, allocation, attempt, binding, suffix=suffix)
    evidence = json.loads(kwargs["evidence"].read_text())
    doc = Path(evidence["document"]["path"])
    document = json.loads(doc.read_text())
    document.update(format="dafjev.exact-provider-charge-statement/1", scope="exact_attempt_account_charge", cost_usd=cost)
    del document["upper_bound_usd"], document["rationale"]
    doc_hash = _write(doc, document)
    evidence.update(format="dafjev.external-billing-evidence/1", scope="exact_attempt_account_charge", source_kind="provider_statement", cost_usd=cost)
    del evidence["upper_bound_usd"]
    evidence["document"].update(sha256=doc_hash, bytes=doc.stat().st_size)
    kwargs["evidence_sha256"] = _write(kwargs["evidence"], evidence)
    kwargs["review_sha256"] = _write(kwargs["review"], {
        "format": "dafjev.external-billing-review/1", "decision": "approve_exact_attempt_charge",
        "reviewer": "independent-fixture-reviewer", "evidence_sha256": kwargs["evidence_sha256"],
        "document_sha256": doc_hash, "allocation_tip": evidence["target"]["allocation"]["journal_tip"],
        "provider_origin_verified": True, "unique_exact_attempt_verified": True, "usd_account_charge_verified": True})
    return kwargs


def _run(tmp_path, allocation, name="next"):
    return RunStore.create_at(tmp_path / name, {"budget_usd": str(allocation.limit), "shared_allocation": allocation.identity()})


def test_default_strict_preview_and_zero_hold_preserve_unknown_with_idempotent_restart(tmp_path):
    allocation, old, (attempt,), binding = _case(tmp_path)
    original = _bytes(old.directory)
    assert allocation.snapshot()["admission_stopped"]
    assert allocation.bounded_unknown_target(binding.manifest_hash, attempt) == allocation.reconciliation_target(binding.manifest_hash, attempt)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    before = _bytes(allocation.directory)
    preview = AllocationLedger(allocation.directory, read_only=True).preview_bounded_unknown(**kwargs)
    assert preview["total_liability_after_usd"] == "0"
    assert _bytes(allocation.directory) == before
    result = allocation.accept_bounded_unknown(**kwargs)
    snapshot = result["accounting"]
    assert snapshot["unknown_attempts"] == snapshot["historical_unknown_attempts"] == [attempt]
    assert snapshot["bounded_unknown_attempts"] == snapshot["historical_bounded_unknown_attempts"] == [attempt]
    assert snapshot["pending_attempts"] == snapshot["externally_reconciled_attempts"] == []
    assert snapshot["reported_cost_usd"] == snapshot["externally_verified_cost_usd"] == snapshot["effective_cost_usd"] == "0"
    assert snapshot["held_upper_bound_usd"] == snapshot["reserved_usd"] == "0"
    assert not snapshot["admission_stopped"]
    fresh = AllocationLedger(allocation.directory)
    run = _run(tmp_path, fresh)
    with fresh.execution(run):
        ledger = SpendLedger(run, allocation=fresh)
        paid = ledger.reserve("cell", "request", "native-fixture", ENDPOINT, True, "1")
        ledger.finish("cell", _receipt(paid, status="reported", cost="0.01"))
    before_duplicate = _bytes(allocation.directory)
    assert fresh.accept_bounded_unknown(**kwargs)["already_recorded"]
    assert fresh.preview_bounded_unknown(**kwargs)["already_recorded"]
    assert _bytes(allocation.directory) == before_duplicate
    assert _bytes(old.directory) == original and old.events()[-1]["receipt"]["cost_status"] == "unknown"


def test_positive_hold_counts_exactly_once_against_shared_cap_with_hostile_decimal_context(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path, bound="10")
    kwargs = _proofs(tmp_path, allocation, attempt, binding, bound="10.000000000000000001")
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        allocation.accept_bounded_unknown(**kwargs)
        s = allocation.snapshot()
        assert s["total_liability_usd"] == s["held_upper_bound_usd"] == "10.000000000000000001"
        run = _run(tmp_path, allocation)
        with allocation.execution(run):
            ledger = SpendLedger(run, allocation=allocation)
            with pytest.raises(BudgetStopped, match="shared USD"):
                ledger.reserve("cell", "request", "native-fixture", ENDPOINT, True, "15")
            a = ledger.reserve("cell", "request", "native-fixture", ENDPOINT, True, "14.999999999999999999")
            ledger.finish("cell", _receipt(a, status="reported", cost="14.999999999999999999"))
        assert allocation.snapshot()["total_liability_usd"] == "25.000000000000000000"


@pytest.mark.parametrize("limit,run_limit,message", [("25", "5", "original run"), ("5", "25", "shared USD")])
def test_hold_refuses_original_and_shared_cap_without_writes(tmp_path, limit, run_limit, message):
    allocation, _, (attempt,), binding = _case(tmp_path, limit=limit, run_limit=run_limit)
    kwargs = _proofs(tmp_path, allocation, attempt, binding, bound="6")
    before = _bytes(allocation.directory)
    for method in (allocation.preview_bounded_unknown, allocation.accept_bounded_unknown):
        with pytest.raises(BudgetStopped, match=message):
            method(**kwargs)
    assert _bytes(allocation.directory) == before


def test_multiple_holds_and_remaining_pending_aggregate_original_run_cap(tmp_path):
    allocation, _, attempts, binding = _case(tmp_path, bounds=("0", "0"), run_limit="15")
    allocation.accept_bounded_unknown(**_proofs(tmp_path, allocation, attempts[0], binding, bound="8"))
    kwargs = _proofs(tmp_path, allocation, attempts[1], binding, bound="8", suffix="-second")
    with pytest.raises(BudgetStopped, match="original run"):
        allocation.accept_bounded_unknown(**kwargs)
    s = allocation.snapshot()
    assert s["held_upper_bound_usd"] == "8" and s["pending_attempts"] == [attempts[1]]
    assert s["admission_stopped"] and set(s["unknown_attempts"]) == set(attempts)


def test_lower_original_reservation_requires_independent_exact_contract_reduction_attestation(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path, bound="10")
    kwargs = _proofs(tmp_path, allocation, attempt, binding, bound="5")
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError, match="independent exact-contract"):
        allocation.accept_bounded_unknown(**kwargs)
    assert _bytes(allocation.directory) == before
    _change(kwargs, "review", lambda r: r.update(original_reservation_reduction_verified=True))
    allocation.accept_bounded_unknown(**kwargs)
    assert allocation.snapshot()["held_upper_bound_usd"] == "5"


@pytest.mark.parametrize("cost,original,held,stopped", [("3", "10", "5", False), ("6", "10", "5", True), ("1", "0", "5", True)])
def test_later_exact_charge_transfers_hold_preserves_history_and_all_bound_breaches(tmp_path, cost, original, held, stopped):
    allocation, old, (attempt,), binding = _case(tmp_path, bound=original)
    kwargs = _proofs(tmp_path, allocation, attempt, binding, bound=held, reduction=True)
    allocation.accept_bounded_unknown(**kwargs)
    allocation.reconcile(**_exact_proofs(tmp_path, allocation, attempt, binding, cost=cost))
    s = AllocationLedger(allocation.directory, read_only=True).snapshot()
    assert s["unknown_attempts"] == s["bounded_unknown_attempts"] == s["pending_attempts"] == []
    assert s["historical_unknown_attempts"] == s["historical_bounded_unknown_attempts"] == [attempt]
    assert s["externally_reconciled_attempts"] == [attempt]
    assert s["held_upper_bound_usd"] == "0" and s["effective_cost_usd"] == cost and s["reported_cost_usd"] == "0"
    assert s["admission_stopped"] is stopped
    if stopped:
        assert "externally_verified_cost_exceeds_reservation" in s["stop_reasons"]
    with pytest.raises(ValueError, match="reconciled"):
        allocation.accept_bounded_unknown(**kwargs)
    assert old.events()[-1]["receipt"]["cost_usd"] is None


def test_unfinished_and_reported_attempts_are_not_eligible_targets(tmp_path):
    old, (attempt,), binding = _legacy(tmp_path / "pending", pending=True)
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="pending")
    allocation.import_run(binding)
    with pytest.raises(ValueError, match="finished hosted"):
        allocation.bounded_unknown_target(binding.manifest_hash, attempt)
    ledger = SpendLedger(old)
    ledger.finish("cell", _receipt(attempt, status="reported", cost="0"))
    new_binding = LegacyRunBinding.capture(old.directory)
    second = AllocationLedger.create(tmp_path / "second", allocation_id="reported")
    second.import_run(new_binding)
    with pytest.raises(ValueError, match="UNKNOWN"):
        second.bounded_unknown_target(new_binding.manifest_hash, attempt)


@pytest.mark.parametrize("other", ["pending", "unknown", "missing"])
def test_only_eligible_finished_import_is_unblocked_other_pending_and_missing_imports_remain(tmp_path, other):
    old, (attempt,), binding = _legacy(tmp_path / "old")
    _, _, second_binding = _legacy(tmp_path / "other", pending=other == "pending")
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="same-25", required_imports=(binding, second_binding))
    allocation.import_run(binding)
    if other != "missing":
        allocation.import_run(second_binding)
    allocation.accept_bounded_unknown(**_proofs(tmp_path, allocation, attempt, binding))
    assert allocation.snapshot()["admission_stopped"]
    run = _run(tmp_path, allocation)
    with pytest.raises(BudgetStopped), allocation.execution(run):
        pytest.fail("unrelated pending work must remain stopped")
    assert run.events() == [] and old.events()[-1]["receipt"]["cost_status"] == "unknown"


def test_structural_and_global_new_unknown_stops_cannot_be_overridden(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path, rejected=True)
    with pytest.raises(ValueError, match="structural"):
        allocation.bounded_unknown_target(binding.manifest_hash, attempt)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    with pytest.raises(ValueError, match="structural"):
        allocation.accept_bounded_unknown(**kwargs)
    other = tmp_path / "other"
    other.mkdir()
    allocation, _, (attempt,), binding = _case(other)
    allocation.accept_bounded_unknown(**_proofs(other, allocation, attempt, binding))
    run = _run(other, allocation)
    with allocation.execution(run):
        ledger = SpendLedger(run, allocation=allocation)
        a = ledger.reserve("cell", "request", "native-fixture", ENDPOINT, True, "0")
        ledger.finish("cell", _receipt(a))
    assert allocation.snapshot()["admission_stopped"]
    with pytest.raises(ValueError, match="imported legacy"):
        allocation.bounded_unknown_target(run.manifest_hash, a)


@pytest.mark.parametrize("field,value", [
    ("format", "unrecognized"), ("scope", "exact_attempt_account_charge"),
    ("source_kind", "free_tariff"), ("currency", "EUR"),
    ("upper_bound_usd", "NaN"), ("upper_bound_usd", "Infinity"),
    ("upper_bound_usd", "-1"), ("upper_bound_usd", "1e999"),
    ("upper_bound_usd", True), ("upper_bound_usd", 0), ("upper_bound_usd", 0.1),
    ("upper_bound_usd", "0.0000000000000000001"), ("extra", "not allowed"),
    ("authority", ""), ("reference", "bad\nreference"), ("collected_by", "a" * 513),
])
def test_malformed_or_wrong_tier_evidence_never_writes(tmp_path, field, value):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    _change(kwargs, "evidence", lambda e: e.update({field: value}))
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.preview_bounded_unknown(**kwargs)
    with pytest.raises(ValueError):
        allocation.accept_bounded_unknown(**kwargs)
    assert _bytes(allocation.directory) == before


@pytest.mark.parametrize("field,value", [
    ("reviewer", "fixture-collector"), ("decision", "approve_exact_attempt_charge"),
    ("contract_origin_verified", False), ("unique_exact_attempt_verified", 1),
    ("upper_bound_verified", "true"), ("original_reservation_reduction_verified", 1),
    ("target_sha256", "0" * 64), ("allocation_tip", "0" * 64),
    ("evidence_sha256", "0" * 64), ("document_sha256", "0" * 64),
    ("rationale", ""), ("rationale", "a" * 4097), ("extra", True),
])
def test_review_is_independent_specific_and_strict(tmp_path, field, value):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    _change(kwargs, "review", lambda r: r.update({field: value}))
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.accept_bounded_unknown(**kwargs)
    assert _bytes(allocation.directory) == before


@pytest.mark.parametrize("field", ["attempt_id", "cell_id", "request_hash", "model", "endpoint", "timestamp", "liability_usd", "start_event_hash", "finish_event_hash", "receipt_sha256", "original_provider", "original_response_id"])
def test_each_original_attempt_binding_is_exact(tmp_path, field):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    _change(kwargs, "evidence", lambda e: e["target"]["attempt"].update({field: "other"}))
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.accept_bounded_unknown(**kwargs)
    assert _bytes(allocation.directory) == before


@pytest.mark.parametrize("field,value", [("format", "bad"), ("scope", "exact_attempt_account_charge"), ("upper_bound_usd", "1"), ("rationale", ""), ("request", {}), ("authority", "other"), ("currency", "EUR"), ("extra", True)])
def test_tariff_document_itself_is_strict_and_exact(tmp_path, field, value):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    evidence = json.loads(kwargs["evidence"].read_text())
    doc = Path(evidence["document"]["path"])
    document = json.loads(doc.read_text())
    document[field] = value
    doc_hash = _write(doc, document)
    _change(kwargs, "evidence", lambda e: e["document"].update(sha256=doc_hash, bytes=doc.stat().st_size))
    _change(kwargs, "review", lambda r: r.update(document_sha256=doc_hash))
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.accept_bounded_unknown(**kwargs)
    assert _bytes(allocation.directory) == before


def test_stale_tip_conflicting_bound_and_cross_attempt_contract_reuse_are_rejected(tmp_path):
    allocation, _, attempts, binding = _case(tmp_path, bounds=("0", "0"))
    stale = _proofs(tmp_path, allocation, attempts[0], binding)
    _, _, other = _legacy(tmp_path / "other", pending=True)
    allocation.import_run(other)
    with pytest.raises(ValueError, match="target/cut"):
        allocation.accept_bounded_unknown(**stale)
    current = _proofs(tmp_path, allocation, attempts[0], binding, suffix="-current", reference="one-contract")
    allocation.accept_bounded_unknown(**current)
    changed = _proofs(tmp_path, allocation, attempts[0], binding, bound="1", suffix="-changed")
    with pytest.raises(ValueError, match="conflicting"):
        allocation.accept_bounded_unknown(**changed)
    reused = _proofs(tmp_path, allocation, attempts[1], binding, suffix="-reused", reference="one-contract")
    with pytest.raises(ValueError, match="attributed"):
        allocation.accept_bounded_unknown(**reused)


@pytest.mark.parametrize("file", ["evidence", "review", "document"])
def test_retained_proof_identity_is_rechecked_on_reopen_snapshot_and_execution(tmp_path, file):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    allocation.accept_bounded_unknown(**kwargs)
    run = _run(tmp_path, allocation)
    path = kwargs[file] if file != "document" else Path(json.loads(kwargs["evidence"].read_text())["document"]["path"])
    path.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="identity"):
        allocation.snapshot()
    with pytest.raises(ValueError, match="identity"):
        AllocationLedger(allocation.directory, read_only=True)
    with pytest.raises(ValueError, match="identity"), allocation.execution(run):
        pytest.fail("changed proof cannot admit")


def test_symlink_duplicate_json_and_oversize_proofs_fail_closed(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    link = tmp_path / "link.json"
    link.symlink_to(kwargs["evidence"])
    with pytest.raises(ValueError):
        allocation.accept_bounded_unknown(**{**kwargs, "evidence": link})
    raw = kwargs["evidence"].read_text().replace('"currency":"USD"', '"currency":"USD","currency":"USD"')
    kwargs["evidence"].write_text(raw)
    kwargs["evidence_sha256"] = hashlib.sha256(kwargs["evidence"].read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="duplicate"):
        allocation.preview_bounded_unknown(**kwargs)
    kwargs["evidence"].write_bytes(b"x" * (1024 * 1024 + 1))
    kwargs["evidence_sha256"] = hashlib.sha256(kwargs["evidence"].read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="byte limit"):
        allocation.preview_bounded_unknown(**kwargs)


def test_accept_requires_inactive_writable_exclusive_allocation(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    with pytest.raises(ValueError, match="writable inactive"):
        AllocationLedger(allocation.directory, read_only=True).accept_bounded_unknown(**kwargs)
    with allocation.store.lease(), pytest.raises(BlockingIOError):
        AllocationLedger(allocation.directory).accept_bounded_unknown(**kwargs)
    allocation.accept_bounded_unknown(**kwargs)
    with allocation.execution(_run(tmp_path, allocation)), pytest.raises(ValueError, match="writable inactive"):
        allocation.accept_bounded_unknown(**kwargs)


@pytest.mark.parametrize("torn", [False, True])
def test_failed_or_torn_bound_event_never_reopens_admission(tmp_path, monkeypatch, torn):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    append = allocation.store.append
    def failure(row):
        if row["event"] == "allocation_legacy_unknown_bounded":
            if torn:
                with (allocation.directory / "events.jsonl").open("ab") as handle:
                    handle.write(b'{"event":"allocation_legacy_unknown_bounded"')
            raise OSError("fixture durability failure")
        append(row)
    monkeypatch.setattr(allocation.store, "append", failure)
    with pytest.raises(OSError):
        allocation.accept_bounded_unknown(**kwargs)
    if torn:
        with pytest.raises(ValueError):
            AllocationLedger(allocation.directory, read_only=True)
    else:
        s = AllocationLedger(allocation.directory, read_only=True).snapshot()
        assert s["admission_stopped"] and s["pending_attempts"] == [attempt]
        assert "bounded_unknown_durability_failure" in s["stop_reasons"]


def test_native_input_contract_breach_is_a_durable_nonoverridable_stop(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    allocation.accept_bounded_unknown(**kwargs)
    allocation.reject("native_input_contract_breach")
    s = AllocationLedger(allocation.directory, read_only=True).snapshot()
    assert s["admission_stopped"] and "native_input_contract_breach" in s["stop_reasons"]
    assert s["unknown_attempts"] == s["bounded_unknown_attempts"] == [attempt]


def test_full_replay_cannot_erase_an_import_cap_breach_with_a_forged_later_bound(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path, bound="10", limit="5")
    kwargs = _proofs(tmp_path, allocation, attempt, binding, reduction=True)
    assert "total_liability_exceeds_allocation" in allocation.snapshot()["stop_reasons"]
    with pytest.raises(ValueError, match="override a stop"):
        allocation.accept_bounded_unknown(**kwargs)
    from daf_jev.benchmark_allocation import _proof
    evidence, evidence_ref = _proof(kwargs["evidence"], kwargs["evidence_sha256"])
    _, review_ref = _proof(kwargs["review"], kwargs["review_sha256"])
    _, document_ref = _proof(Path(evidence["document"]["path"]), evidence["document"]["sha256"])
    allocation.store.append({"event": "allocation_legacy_unknown_bounded", "evidence": evidence_ref,
                             "review": review_ref, "document": document_ref})
    with pytest.raises(ValueError, match="override a stop"):
        AllocationLedger(allocation.directory, read_only=True)


def test_new_event_schema_rejects_unreviewed_extra_fields(tmp_path):
    allocation, _, (attempt,), binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    allocation.accept_bounded_unknown(**kwargs)
    event = {k: v for k, v in allocation.store.events()[-1].items() if k not in {"sequence", "timestamp", "previous", "hash"}}
    event["charge_usd"] = "0"
    allocation.store.append(event)
    with pytest.raises(ValueError, match="event schema"):
        AllocationLedger(allocation.directory)


def test_hold_and_external_proof_reference_cannot_be_reused_for_another_attempt(tmp_path):
    allocation, _, attempts, binding = _case(tmp_path, bounds=("0", "0"))
    first = _proofs(tmp_path, allocation, attempts[0], binding, reference="one-contract")
    allocation.accept_bounded_unknown(**first)
    exact = _exact_proofs(tmp_path, allocation, attempts[1], binding)
    _change(exact, "evidence", lambda e: e.update(reference="one-contract"))
    evidence = json.loads(exact["evidence"].read_text())
    doc = Path(evidence["document"]["path"])
    document = json.loads(doc.read_text())
    document["reference"] = "one-contract"
    doc_hash = _write(doc, document)
    _change(exact, "evidence", lambda e: e["document"].update(sha256=doc_hash, bytes=doc.stat().st_size))
    _change(exact, "review", lambda r: r.update(document_sha256=doc_hash))
    with pytest.raises(ValueError, match="attributed"):
        allocation.reconcile(**exact)
    assert Decimal(allocation.snapshot()["held_upper_bound_usd"]) == 0
