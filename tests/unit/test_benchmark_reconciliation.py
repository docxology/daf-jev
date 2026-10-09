"""Synthetic exact billing evidence, real files/processes; no provider calls."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from decimal import ROUND_DOWN, Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import CallReceipt, utc_now


def _write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes(path):
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


def _legacy(
    path, *, bound="10", response_id="generation-fixture", pending=False, rejected=False
):
    store = RunStore.create_at(path, {"budget_usd": "25", "fixture": str(path)})
    ledger = SpendLedger(store)
    attempt = ledger.reserve(
        "cell",
        "request",
        "fixture-model",
        "https://fixture.invalid/endpoint",
        True,
        bound,
    )
    if not pending:
        receipt = CallReceipt(
            attempt,
            utc_now(),
            "https://fixture.invalid/endpoint",
            "fixture-model",
            None,
            None,
            response_id,
            "request",
            0.01,
            404,
            None,
            None,
            None,
            "unknown",
        )
        ledger.finish("cell", receipt)
    if rejected:
        store.append({"event": "accounting_rejected", "reason": "fixture-rejected"})
    return store, attempt, LegacyRunBinding.capture(store.directory)


def _case(tmp_path, *, bound="10", response_id="generation-fixture", rejected=False):
    old, attempt, binding = _legacy(
        tmp_path / "old", bound=bound, response_id=response_id, rejected=rejected
    )
    allocation = AllocationLedger.create(
        tmp_path / "allocation",
        allocation_id="one-existing-allowance",
        required_imports=(binding,),
    )
    allocation.import_run(binding)
    return allocation, old, attempt, binding


def _proofs(
    tmp_path,
    allocation,
    attempt,
    binding,
    *,
    cost="0",
    kind="provider_statement",
    suffix="",
):
    target = allocation.reconciliation_target(binding.manifest_hash, attempt)
    request = dict(target["attempt"])
    if kind == "generation_metadata":
        document = {
            "data": {
                "id": target["attempt"]["original_response_id"]
                or "gen-unrelated-modern",
                "model": request["model"],
                "total_cost": cost,
            }
        }
    else:
        document = {
            "format": "dafjev.exact-provider-charge-statement/1",
            "scope": "exact_attempt_account_charge",
            "authority": "synthetic-provider",
            "reference": "synthetic-ticket-" + attempt,
            "request": request,
            "currency": "USD",
            "cost_usd": cost,
        }
    doc = tmp_path / f"document{suffix}.json"
    document_hash = _write(doc, document)
    evidence = {
        "format": "dafjev.external-billing-evidence/1",
        "scope": "exact_attempt_account_charge",
        "target": target,
        "source_kind": kind,
        "authority": "synthetic-provider",
        "reference": (
            target["attempt"]["original_response_id"] or "gen-unrelated-modern"
        )
        if kind == "generation_metadata"
        else "synthetic-ticket-" + attempt,
        "collected_by": "fixture-collector",
        "currency": "USD",
        "cost_usd": cost,
        "document": {
            "path": str(doc),
            "sha256": document_hash,
            "bytes": doc.stat().st_size,
        },
    }
    proof = tmp_path / f"evidence{suffix}.json"
    evidence_hash = _write(proof, evidence)
    review = {
        "format": "dafjev.external-billing-review/1",
        "decision": "approve_exact_attempt_charge",
        "reviewer": "fixture-independent-reviewer",
        "evidence_sha256": evidence_hash,
        "document_sha256": document_hash,
        "allocation_tip": target["allocation"]["journal_tip"],
        "provider_origin_verified": True,
        "unique_exact_attempt_verified": True,
        "usd_account_charge_verified": True,
    }
    reviewed = tmp_path / f"review{suffix}.json"
    review_hash = _write(reviewed, review)
    return {
        "evidence": proof,
        "evidence_sha256": evidence_hash,
        "review": reviewed,
        "review_sha256": review_hash,
    }


def _rebind_review(kwargs):
    value = json.loads(kwargs["review"].read_text())
    value["evidence_sha256"] = kwargs["evidence_sha256"]
    kwargs["review_sha256"] = _write(kwargs["review"], value)


def test_preview_zero_reconciliation_preserves_unknown_original_and_idempotent_restart(
    tmp_path,
):
    allocation, old, attempt, binding = _case(tmp_path, bound="0", response_id=None)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    original = _bytes(old.directory)
    before = _bytes(allocation.directory)
    preview = AllocationLedger(
        allocation.directory, read_only=True
    ).preview_reconciliation(**kwargs)
    assert (
        preview["effective_cost_after_usd"] == "0"
        and not preview["would_exceed_original_bound"]
    )
    assert _bytes(allocation.directory) == before
    allocation.reconcile(**kwargs)
    after = _bytes(allocation.directory)
    fresh = AllocationLedger(allocation.directory)
    assert fresh.reconcile(**kwargs)["already_recorded"]
    assert _bytes(allocation.directory) == after
    snapshot = fresh.snapshot()
    assert (
        snapshot["reported_cost_usd"]
        == snapshot["externally_verified_cost_usd"]
        == snapshot["effective_cost_usd"]
        == "0"
    )
    assert (
        snapshot["historical_unknown_attempts"] == [attempt]
        and snapshot["unknown_attempts"] == []
    )
    assert not snapshot["admission_stopped"] and snapshot[
        "externally_reconciled_attempts"
    ] == [attempt]
    run = RunStore.create_at(
        tmp_path / "next", {"budget_usd": "25", "shared_allocation": fresh.identity()}
    )
    with fresh.execution(run):
        ledger = SpendLedger(run, allocation=fresh)
        assert not ledger.admissions
    assert _bytes(old.directory) == original
    assert old.events()[-1]["receipt"]["cost_status"] == "unknown"
    assert allocation.store.events()[0] == json.loads(before["events.jsonl"])


@pytest.mark.parametrize(
    "cost,bound,stopped",
    [
        ("5.000000000000000001", "10", False),
        ("0.000000000000000001", "0", True),
        ("30", "0", True),
    ],
)
def test_decimal_effective_total_and_original_bound_breach(
    tmp_path, cost, bound, stopped
):
    allocation, old, attempt, binding = _case(tmp_path, bound=bound)
    kwargs = _proofs(tmp_path, allocation, attempt, binding, cost=cost)
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        allocation.reconcile(**kwargs)
        snapshot = allocation.snapshot()
    assert (
        snapshot["reported_cost_usd"] == "0"
        and Decimal(snapshot["externally_verified_cost_usd"]) == Decimal(cost)
        and Decimal(snapshot["effective_cost_usd"]) == Decimal(cost)
    )
    assert snapshot["admission_stopped"] is stopped
    if stopped:
        assert (
            "externally_verified_cost_exceeds_reservation" in snapshot["stop_reasons"]
        )
    else:
        run = RunStore.create_at(
            tmp_path / "next",
            {"budget_usd": "25", "shared_allocation": allocation.identity()},
        )
        with allocation.execution(run):
            ledger = SpendLedger(run, allocation=allocation)
            with pytest.raises(BudgetStopped, match="exhausted"):
                ledger.reserve(
                    "next",
                    "request",
                    "fixture-model",
                    "https://fixture.invalid/endpoint",
                    True,
                    "20",
                )
            assert not ledger.admissions
    assert old.events()[-1]["receipt"]["cost_usd"] is None


@pytest.mark.parametrize("other", ["unknown", "pending", "rejected"])
def test_only_one_finished_unknown_resolves_other_holds_remain(tmp_path, other):
    allocation, _, attempt, binding = _case(tmp_path, rejected=other == "rejected")
    if other != "rejected":
        second, _, binding2 = _legacy(tmp_path / "second", pending=other == "pending")
        allocation.import_run(binding2)
        assert second.events()
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    allocation.reconcile(**kwargs)
    assert allocation.snapshot()["admission_stopped"]
    run = RunStore.create_at(
        tmp_path / "next",
        {"budget_usd": "25", "shared_allocation": allocation.identity()},
    )
    with pytest.raises(BudgetStopped), allocation.execution(run):
        pytest.fail("another stop must not clear")
    assert run.events() == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "account_aggregate"),
        ("source_kind", "absence"),
        ("source_kind", "free_tariff"),
        ("currency", "EUR"),
        ("cost_usd", "NaN"),
        ("cost_usd", "Infinity"),
        ("cost_usd", "-1"),
        ("cost_usd", True),
        ("format", "unknown"),
    ],
)
def test_unsupported_and_malformed_evidence_no_writes(tmp_path, field, value):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    evidence = json.loads(kwargs["evidence"].read_text())
    evidence[field] = value
    kwargs["evidence_sha256"] = _write(kwargs["evidence"], evidence)
    _rebind_review(kwargs)
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.preview_reconciliation(**kwargs)
    with pytest.raises(ValueError):
        allocation.reconcile(**kwargs)
    assert _bytes(allocation.directory) == before


@pytest.mark.parametrize(
    "field",
    [
        "attempt_id",
        "cell_id",
        "request_hash",
        "model",
        "endpoint",
        "timestamp",
        "liability_usd",
        "start_event_hash",
        "finish_event_hash",
        "receipt_sha256",
        "original_provider",
        "original_response_id",
    ],
)
def test_every_original_attempt_binding_is_exact(tmp_path, field):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    evidence = json.loads(kwargs["evidence"].read_text())
    evidence["target"]["attempt"][field] = "other"
    kwargs["evidence_sha256"] = _write(kwargs["evidence"], evidence)
    _rebind_review(kwargs)
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.reconcile(**kwargs)
    assert _bytes(allocation.directory) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewer", "fixture-collector"),
        ("decision", "approve_aggregate"),
        ("provider_origin_verified", False),
        ("unique_exact_attempt_verified", 1),
        ("usd_account_charge_verified", False),
        ("allocation_tip", "0" * 64),
        ("evidence_sha256", "0" * 64),
        ("document_sha256", "0" * 64),
    ],
)
def test_review_is_exact_independent_attestation_not_general_permission(
    tmp_path, field, value
):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    review = json.loads(kwargs["review"].read_text())
    review[field] = value
    kwargs["review_sha256"] = _write(kwargs["review"], review)
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.reconcile(**kwargs)
    assert _bytes(allocation.directory) == before


def test_generation_requires_retained_id_and_native_decimal_document(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path, response_id="gen-owned-exact")
    kwargs = _proofs(
        tmp_path,
        allocation,
        attempt,
        binding,
        cost="0.123456789012345678",
        kind="generation_metadata",
    )
    evidence = json.loads(kwargs["evidence"].read_text())
    doc = Path(evidence["document"]["path"])
    raw = doc.read_text().replace(
        '"total_cost":"0.123456789012345678"', '"total_cost":0.123456789012345678'
    )
    doc.write_text(raw)
    evidence["document"]["sha256"] = hashlib.sha256(doc.read_bytes()).hexdigest()
    evidence["document"]["bytes"] = doc.stat().st_size
    kwargs["evidence_sha256"] = _write(kwargs["evidence"], evidence)
    review = json.loads(kwargs["review"].read_text())
    review["document_sha256"] = evidence["document"]["sha256"]
    review["evidence_sha256"] = kwargs["evidence_sha256"]
    kwargs["review_sha256"] = _write(kwargs["review"], review)
    allocation.reconcile(**kwargs)
    assert allocation.snapshot()["effective_cost_usd"] == "0.123456789012345678"
    other_dir = tmp_path / "missing-id"
    other_dir.mkdir()
    missing, _, attempt2, binding2 = _case(other_dir, response_id=None)
    with pytest.raises(ValueError, match="original response"):
        missing.reconcile(
            **_proofs(
                other_dir, missing, attempt2, binding2, kind="generation_metadata"
            )
        )


def test_stale_cut_conflicting_proof_and_proof_replacement_refuse(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path)
    stale = _proofs(tmp_path, allocation, attempt, binding)
    other, _, other_binding = _legacy(tmp_path / "other")
    allocation.import_run(other_binding)
    with pytest.raises(ValueError, match="exact allocation"):
        allocation.reconcile(**stale)
    current = _proofs(tmp_path, allocation, attempt, binding, suffix="-current")
    allocation.reconcile(**current)
    different = _proofs(tmp_path, allocation, attempt, binding, suffix="-different")
    with pytest.raises(ValueError, match="conflicting"):
        allocation.reconcile(**different)
    current["review"].write_bytes(current["review"].read_bytes())
    with pytest.raises(ValueError, match="identity"):
        allocation.snapshot()
    with pytest.raises(ValueError, match="identity"):
        AllocationLedger(allocation.directory, read_only=True)
    assert other.events()


def test_copied_allocation_with_hardlinked_locks_cannot_reuse_proof(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    copied = tmp_path / "copied"
    shutil.copytree(allocation.directory, copied)
    for name in (".journal.lock", ".run.lock"):
        (copied / name).unlink()
        os.link(allocation.directory / name, copied / name)
    clone = AllocationLedger(copied)
    before = _bytes(copied)
    with pytest.raises(ValueError, match="exact allocation"):
        clone.reconcile(**kwargs)
    assert _bytes(copied) == before


def test_missing_mutated_duplicate_nonfinite_or_symlink_proof_fails_closed(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    for raw in ('{"a":0,"a":1}', '{"a":NaN}', '{"a":Infinity}', "null", "[]"):
        kwargs["evidence"].write_text(raw)
        kwargs["evidence_sha256"] = hashlib.sha256(
            kwargs["evidence"].read_bytes()
        ).hexdigest()
        with pytest.raises(ValueError):
            allocation.preview_reconciliation(**kwargs)
    path = kwargs["evidence"]
    original = tmp_path / "original-proof"
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(ValueError):
        allocation.preview_reconciliation(**kwargs)


_CHILD = """
import json,sys
from pathlib import Path
from daf_jev.benchmark_allocation import AllocationLedger
kw=json.loads(Path(sys.argv[2]).read_text());kw['evidence']=Path(kw['evidence']);kw['review']=Path(kw['review'])
try:
 print(json.dumps(AllocationLedger(Path(sys.argv[1])).reconcile(**kw)),flush=True)
except BlockingIOError:
 print('LEASE_BUSY',flush=True)
"""


def test_real_process_duplicate_race_charges_once_and_restart_proof_stays_valid(
    tmp_path,
):
    allocation, old, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding, cost="4")
    args = tmp_path / "arguments.json"
    _write(args, {k: str(v) for k, v in kwargs.items()})
    command = [sys.executable, "-c", _CHILD, str(allocation.directory), str(args)]
    children = [
        subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    outputs = [child.communicate(timeout=20) for child in children]
    assert all(child.returncode == 0 for child in children), outputs
    assert any('"operation": "reconcile"' in output[0] for output in outputs)
    fresh = AllocationLedger(allocation.directory)
    assert (
        fresh.snapshot()["externally_verified_cost_usd"] == "4"
        and fresh.snapshot()["journal_sequence"] == 2
    )
    assert fresh.reconcile(**kwargs)["already_recorded"]
    assert old.events()[-1]["receipt"]["cost_status"] == "unknown"


def test_real_file_limit_partial_journal_write_never_reopens_admission(tmp_path):
    allocation, old, attempt, binding = _case(tmp_path)
    journal = allocation.directory / "events.jsonl"
    original_journal = journal.read_bytes()
    original_head = (allocation.directory / "head.json").read_bytes()
    size = len(original_journal)
    file_limit = size + 100
    # Darwin's raw O_APPEND limit can use the descriptor's initial offset,
    # rather than the existing file length. Ensure even that first append is
    # larger than the limit using a lower bound from its three retained paths.
    proof_dir = tmp_path
    while (
        sum(
            len(str(proof_dir / name).encode())
            for name in ("evidence.json", "review.json", "document.json")
        )
        <= file_limit
    ):
        proof_dir /= "owned-proof-padding-" + "p" * 100
    proof_dir.mkdir(parents=True, exist_ok=True)
    kwargs = _proofs(proof_dir, allocation, attempt, binding)
    assert (
        sum(
            len(str(proof_dir / name).encode())
            for name in ("evidence.json", "review.json", "document.json")
        )
        > file_limit
    )
    args = tmp_path / "arguments.json"
    _write(args, {k: str(v) for k, v in kwargs.items()})
    old_bytes = _bytes(old.directory)
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import resource,signal,sys
signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE,(int(sys.argv[3])+100,int(sys.argv[3])+100))
"""
            + _CHILD,
            str(allocation.directory),
            str(args),
            str(size),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode != 0, (child.stdout, child.stderr)
    assert "OSError" in child.stderr
    partial = journal.read_bytes()
    assert partial.startswith(original_journal) and len(partial) > size
    assert not partial.endswith(b"\n")
    assert (allocation.directory / "head.json").read_bytes() == original_head
    with pytest.raises(ValueError):
        AllocationLedger(allocation.directory)
    assert _bytes(old.directory) == old_bytes


def test_cli_preview_is_keyless_no_write_and_explicit_apply(tmp_path, capsys):
    from daf_jev.cli import main

    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    flags = [
        str(allocation.directory),
        "--evidence",
        str(kwargs["evidence"]),
        "--evidence-sha256",
        kwargs["evidence_sha256"],
        "--review",
        str(kwargs["review"]),
        "--review-sha256",
        kwargs["review_sha256"],
    ]
    before = _bytes(allocation.directory)
    assert main(["benchmark", "allocation", "preview-reconciliation", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["operation"] == "preview_reconciliation"
    assert _bytes(allocation.directory) == before
    assert main(["benchmark", "allocation", "reconcile", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["accounting"][
        "historical_unknown_attempts"
    ] == [attempt]


def test_preview_target_pending_reported_or_readonly_apply_refuses(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    with pytest.raises(ValueError, match="writable inactive"):
        AllocationLedger(allocation.directory, read_only=True).reconcile(**kwargs)
    pending, pending_attempt, pending_binding = _legacy(
        tmp_path / "pending", pending=True
    )
    allocation.import_run(pending_binding)
    with pytest.raises(ValueError, match="finished hosted"):
        allocation.reconciliation_target(pending_binding.manifest_hash, pending_attempt)
    assert pending.events()
    with pytest.raises(ValueError, match="imported"):
        allocation.reconciliation_target("0" * 64, attempt)
    with pytest.raises(ValueError):
        allocation.preview_reconciliation(**{**kwargs, "review_sha256": "0" * 64})


def test_statement_reference_cannot_clear_two_identical_requests(tmp_path):
    allocation, _, first, first_binding = _case(tmp_path)
    old2, second, second_binding = _legacy(tmp_path / "second")
    allocation.import_run(second_binding)
    first_proof = _proofs(tmp_path, allocation, first, first_binding)
    allocation.reconcile(**first_proof)
    second_proof = _proofs(
        tmp_path, allocation, second, second_binding, suffix="-second"
    )
    evidence = json.loads(second_proof["evidence"].read_text())
    document_path = Path(evidence["document"]["path"])
    document = json.loads(document_path.read_text())
    # Deliberately contradictory exact-call attribution under the same provider
    # reference. Even a second local approval cannot reuse a statement identity.
    reference = json.loads(first_proof["evidence"].read_text())["reference"]
    evidence["reference"] = document["reference"] = reference
    evidence["document"]["sha256"] = _write(document_path, document)
    evidence["document"]["bytes"] = document_path.stat().st_size
    second_proof["evidence_sha256"] = _write(second_proof["evidence"], evidence)
    review = json.loads(second_proof["review"].read_text())
    review["document_sha256"] = evidence["document"]["sha256"]
    review["evidence_sha256"] = second_proof["evidence_sha256"]
    second_proof["review_sha256"] = _write(second_proof["review"], review)
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError, match="another attempt"):
        allocation.reconcile(**second_proof)
    assert _bytes(allocation.directory) == before
    assert allocation.snapshot()["unknown_attempts"] == [second]
    assert old2.events()[-1]["receipt"]["cost_status"] == "unknown"


@pytest.mark.parametrize(
    "field", ["directory", "allocation_id", "manifest_hash", "journal_tip"]
)
def test_allocation_cut_binding_rejects_wrong_identity(tmp_path, field):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    evidence = json.loads(kwargs["evidence"].read_text())
    evidence["target"]["allocation"][field] = "other"
    kwargs["evidence_sha256"] = _write(kwargs["evidence"], evidence)
    _rebind_review(kwargs)
    before = _bytes(allocation.directory)
    with pytest.raises(ValueError):
        allocation.reconcile(**kwargs)
    assert _bytes(allocation.directory) == before


def test_global_open_admission_and_durable_structural_stop_not_cleared(tmp_path):
    allocation = AllocationLedger.create(
        tmp_path / "allocation", allocation_id="same-existing-cap"
    )
    run = RunStore.create_at(
        tmp_path / "open",
        {"budget_usd": "25", "shared_allocation": allocation.identity()},
    )
    with allocation.execution(run):
        ledger = SpendLedger(run, allocation=allocation)
        pending = ledger.reserve(
            "pending",
            "request",
            "fixture-model",
            "https://fixture.invalid/endpoint",
            True,
            "2",
        )
    old, attempt, binding = _legacy(tmp_path / "old")
    allocation.import_run(binding)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    allocation.reconcile(**kwargs)
    snapshot = allocation.snapshot()
    assert snapshot["unknown_attempts"] == [] and snapshot["pending_attempts"] == [
        pending
    ]
    assert snapshot["reserved_usd"] == "2" and snapshot["admission_stopped"]
    assert "open_reservations_at_execution_end" in snapshot["stop_reasons"]
    assert old.events()[-1]["receipt"]["cost_status"] == "unknown"


def test_legacy_reported_bound_breach_survives_unrelated_unknown_resolution(tmp_path):
    old = RunStore.create_at(tmp_path / "old", {"budget_usd": "25"})
    ledger = SpendLedger(old)
    unknown = ledger.reserve(
        "cell",
        "request",
        "fixture-model",
        "https://fixture.invalid/endpoint",
        True,
        "10",
    )
    paid = ledger.reserve(
        "paid",
        "request",
        "fixture-model",
        "https://fixture.invalid/endpoint",
        True,
        "1",
    )
    receipt = CallReceipt(
        unknown,
        utc_now(),
        "https://fixture.invalid/endpoint",
        "fixture-model",
        None,
        None,
        None,
        "request",
        0.01,
        404,
        None,
        None,
        None,
        "unknown",
    )
    ledger.finish("cell", receipt)
    from dataclasses import replace

    ledger.finish(
        "paid", replace(receipt, attempt_id=paid, cost_status="reported", cost_usd="2")
    )
    binding = LegacyRunBinding.capture(old.directory)
    allocation = AllocationLedger.create(
        tmp_path / "allocation", allocation_id="same-cap", required_imports=(binding,)
    )
    allocation.import_run(binding)
    allocation.reconcile(**_proofs(tmp_path, allocation, unknown, binding))
    snapshot = allocation.snapshot()
    assert snapshot["reported_cost_usd"] == snapshot["effective_cost_usd"] == "2"
    assert snapshot["unknown_attempts"] == [] and snapshot["admission_stopped"]
    assert "legacy_accounting_stopped" in snapshot["stop_reasons"]


def test_reconciliation_lease_and_missing_proof_block_actual_next_reservation(tmp_path):
    allocation, _, attempt, binding = _case(tmp_path)
    kwargs = _proofs(tmp_path, allocation, attempt, binding)
    with allocation.store.lease(), pytest.raises(BlockingIOError):
        allocation.reconcile(**kwargs)
    allocation.reconcile(**kwargs)
    fresh = AllocationLedger(allocation.directory)
    run = RunStore.create_at(
        tmp_path / "next", {"budget_usd": "25", "shared_allocation": fresh.identity()}
    )
    with pytest.raises(FileNotFoundError), fresh.execution(run):
        ledger = SpendLedger(run, allocation=fresh)
        kwargs["review"].unlink()
        with pytest.raises(FileNotFoundError):
            ledger.reserve(
                "next",
                "request",
                "fixture-model",
                "https://fixture.invalid/endpoint",
                True,
                "1",
            )
        assert not ledger.admissions


def test_effective_external_cost_respects_original_frozen_run_limit(tmp_path):
    # The legacy per-run API allowed a caller-supplied limit; recovery must
    # still respect the immutable manifest's original limit, without rewriting it.
    old = RunStore.create_at(tmp_path / "old", {"budget_usd": "4"})
    ledger = SpendLedger(old, limit="25")
    attempt = ledger.reserve(
        "cell",
        "request",
        "fixture-model",
        "https://fixture.invalid/endpoint",
        True,
        "10",
    )
    ledger.finish(
        "cell",
        CallReceipt(
            attempt,
            utc_now(),
            "https://fixture.invalid/endpoint",
            "fixture-model",
            None,
            None,
            None,
            "request",
            0.01,
            404,
            None,
            None,
            None,
            "unknown",
        ),
    )
    binding = LegacyRunBinding.capture(old.directory)
    allocation = AllocationLedger.create(
        tmp_path / "allocation", allocation_id="same-cap", required_imports=(binding,)
    )
    allocation.import_run(binding)
    allocation.reconcile(**_proofs(tmp_path, allocation, attempt, binding, cost="5"))
    snapshot = allocation.snapshot()
    assert snapshot["effective_cost_usd"] == "5"
    assert snapshot["admission_stopped"]
    assert "externally_verified_cost_exceeds_run_limit" in snapshot["stop_reasons"]
    assert (
        "externally_verified_cost_exceeds_reservation" not in snapshot["stop_reasons"]
    )
