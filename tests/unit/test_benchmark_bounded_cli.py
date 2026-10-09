"""Real-file keyless CLI continuation, preserving unknown receipts and allowance."""
from __future__ import annotations

import hashlib
import json

from daf_jev.benchmark_allocation import AllocationLedger, LegacyRunBinding
from daf_jev.benchmark_store import RunStore, SpendLedger
from daf_jev.cli import main
from daf_jev.decision_backends import CallReceipt, canonical_json, content_hash, utc_now


def _write(path, value):
    path.write_text(canonical_json(value) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes(directory):
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def test_target_preview_apply_and_repeat_are_keyless_and_preserve_unknown(tmp_path, capsys):
    old = RunStore.create_at(tmp_path / "old", {"budget_usd": "25"})
    spend = SpendLedger(old)
    attempt = spend.reserve("cell", "request", "free-fixture", "https://fixture.invalid/decisions", True, "0")
    spend.finish("cell", CallReceipt(attempt, utc_now(), "https://fixture.invalid/decisions",
        "free-fixture", None, None, None, "request", .01, 404, None, None, None, "unknown"))
    binding = LegacyRunBinding.capture(old.directory)
    allocation = AllocationLedger.create(tmp_path / "allocation", allocation_id="existing-cap", required_imports=(binding,))
    allocation.import_run(binding)
    before_original = _bytes(old.directory)
    before_allocation = _bytes(allocation.directory)
    assert main(["benchmark", "allocation", "bounded-unknown-target", str(allocation.directory),
        "--legacy-manifest-hash", binding.manifest_hash, "--attempt-id", attempt]) == 0
    target = json.loads(capsys.readouterr().out)
    document = {"format": "dafjev.exact-request-tariff-bound/1", "scope": "exact_finished_attempt_upper_bound",
        "authority": "public-fixture-tariff", "reference": "fixture-reference", "request": target["attempt"],
        "currency": "USD", "upper_bound_usd": "0", "rationale": "Synthetic independent exact-request zero-tariff contract."}
    document_path = tmp_path / "document.json"
    document_sha = _write(document_path, document)
    evidence = {"format": "dafjev.bounded-unknown-evidence/1", "scope": "exact_finished_attempt_upper_bound",
        "target": target, "source_kind": "reviewed_request_tariff_contract", "authority": document["authority"],
        "reference": document["reference"], "collected_by": "fixture-collector", "currency": "USD", "upper_bound_usd": "0",
        "document": {"path": str(document_path), "sha256": document_sha, "bytes": document_path.stat().st_size}}
    evidence_path = tmp_path / "evidence.json"
    evidence_sha = _write(evidence_path, evidence)
    review = {"format": "dafjev.bounded-unknown-review/1", "decision": "approve_bounded_unknown_continuation",
        "reviewer": "independent-fixture-reviewer", "evidence_sha256": evidence_sha, "document_sha256": document_sha,
        "allocation_tip": target["allocation"]["journal_tip"], "target_sha256": content_hash(target),
        "contract_origin_verified": True, "unique_exact_attempt_verified": True, "upper_bound_verified": True,
        "original_reservation_reduction_verified": False, "rationale": "Independent synthetic fixture review."}
    review_path = tmp_path / "review.json"
    review_sha = _write(review_path, review)
    flags = [str(allocation.directory), "--evidence", str(evidence_path), "--evidence-sha256", evidence_sha,
             "--review", str(review_path), "--review-sha256", review_sha]
    assert main(["benchmark", "allocation", "preview-bounded-unknown", *flags]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["operation"] == "preview_bounded_unknown" and preview["total_liability_after_usd"] == "0"
    assert _bytes(allocation.directory) == before_allocation
    assert main(["benchmark", "allocation", "accept-bounded-unknown", *flags]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["accounting"]["unknown_attempts"] == [attempt]
    assert result["accounting"]["bounded_unknown_attempts"] == [attempt]
    assert result["accounting"]["held_upper_bound_usd"] == "0"
    assert not result["accounting"]["admission_stopped"]
    after_allocation = _bytes(allocation.directory)
    assert main(["benchmark", "allocation", "accept-bounded-unknown", *flags]) == 0
    assert json.loads(capsys.readouterr().out)["already_recorded"]
    assert _bytes(allocation.directory) == after_allocation
    assert _bytes(old.directory) == before_original
    assert old.events()[-1]["receipt"]["cost_status"] == "unknown"
