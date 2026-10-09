"""Explicit, hash-bound USD allocation shared by serial experiment executors.

Creating/importing/binding is an explicit write operation. Read-only inspection
never creates or repairs state. One OS execution lease covers an entire run;
within that lease concurrent attempts reserve against the same exact total.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from daf_jev._json import strict_json_loads
from daf_jev.benchmark_store import (
    BudgetStopped,
    RunStore,
    SpendLedger,
    _regular,
    currency_context,
    usd,
    usd_total,
)
from daf_jev.decision_backends import CallReceipt, content_hash

_FORMAT = "dafjev.shared-allocation/1"
_BINDING_FORMAT = "dafjev.shared-allocation-legacy-binding/1"
_MAX_LIMIT = Decimal("25")
_STOP_REASONS = {
    "reservation_split_write", "finish_split_write", "invalid_receipt",
    "allocation_durability_failure", "open_reservations_at_execution_end",
    "run_binding_changed", "legacy_binding_changed",
    "admission_pair_mismatch",
    "reconciliation_durability_failure",
    "bounded_unknown_durability_failure", "native_input_contract_breach",
}
_EVENT_FIELDS = {
    "allocation_run_bound": {"binding"},
    "allocation_run_imported": {"binding", "accounting"},
    "allocation_attempt_started": {"run_manifest_hash", "attempt_id", "cell_id", "request_hash", "model", "endpoint", "liability_usd"},
    "allocation_attempt_finished": {"run_manifest_hash", "attempt_id", "cell_id", "receipt_sha256", "run_event_hash", "cost_status", "cost_usd"},
    "allocation_stopped": {"reason"},
    "allocation_legacy_billing_reconciled": {"evidence", "review", "document"},
    "allocation_legacy_unknown_bounded": {"evidence", "review", "document"},
}

_PROOF_LIMIT = 1024 * 1024


def _object(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"invalid {name} schema")
    return value


def _proof(path: Path, sha256: str, retained: Mapping[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    """Bounded strict file ingest; byte custody does not authenticate its author."""
    path = Path(path).absolute()
    _directory(path.parent)
    if ".." in path.parts:
        raise ValueError("proof path must not escape")
    expected = _digest(sha256)
    before = _stat(path)
    if before[2] > _PROOF_LIMIT:
        raise ValueError("billing proof exceeds byte limit")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks = []
        size = 0
        while chunk := os.read(descriptor, 65536):
            size += len(chunk)
            if size > _PROOF_LIMIT:
                raise ValueError("billing proof exceeds byte limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
        observed = os.fstat(descriptor)
        physical = (observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns)
        if before != physical or before != _stat(path) or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("billing proof bytes/custody changed")
    finally:
        os.close(descriptor)
    reference = {"path": str(path), "sha256": expected, "bytes": len(raw), "identity": list(before)}
    if retained is not None and dict(retained) != reference:
        raise ValueError("retained billing proof identity changed")
    return strict_json_loads(raw, parse_float=Decimal), reference


def _retained_proof(value: Any) -> Mapping[str, Any]:
    reference = _object(value, {"path", "sha256", "bytes", "identity"}, "retained proof")
    if isinstance(reference["bytes"], bool) or not isinstance(reference["bytes"], int) or not 0 <= reference["bytes"] <= _PROOF_LIMIT:
        raise ValueError("invalid proof byte count")
    identity = reference["identity"]
    if not isinstance(identity, (list, tuple)) or len(identity) != 5 or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in identity):
        raise ValueError("invalid proof physical identity")
    _text(reference["path"], "proof path")
    _digest(reference["sha256"])
    return reference


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid SHA256 binding")
    return value


def _directory(value: Any) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("invalid allocation/run directory")
    path = Path(value).absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("allocation/run directory must not escape or traverse symlinks")
    if path.exists() and not path.is_dir():
        raise ValueError("allocation/run directory is not a directory")
    return path


def _stat(path: Path) -> tuple[int, ...]:
    _regular(path)
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _file_hash(path: Path) -> str:
    _regular(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 524288):
            digest.update(chunk)
        after = os.fstat(descriptor)
        current = path.stat()
        def fields(s: os.stat_result) -> tuple[int, ...]:
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if fields(before) != fields(after) or fields(after) != fields(current):
            raise ValueError("allocation input changed during consumption")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _locks(store: RunStore) -> None:
    identities = store.manifest.get("lock_identities")
    if not isinstance(identities, Mapping) or set(identities) != {".run.lock", ".journal.lock"}:
        raise ValueError("invalid allocation/run lock inventory")
    for name, expected in identities.items():
        stat = _stat(store.directory / name)
        if not isinstance(expected, (list, tuple)) or len(expected) != 2 or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in expected) or stat[:2] != tuple(expected):
            raise ValueError("allocation/run lock identity changed")


@dataclass(frozen=True)
class LegacyRunBinding:
    """Exact immutable original run cut, without altering its source files."""
    directory: Path
    manifest_hash: str
    manifest_sha256: str
    journal_sha256: str
    head_sha256: str
    journal_tip: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", _directory(self.directory))
        for name in ("manifest_hash", "manifest_sha256", "journal_sha256", "head_sha256", "journal_tip"):
            _digest(getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {"format": _BINDING_FORMAT, "directory": str(self.directory),
                **{n: getattr(self, n) for n in ("manifest_hash", "manifest_sha256", "journal_sha256", "head_sha256", "journal_tip")}}

    @classmethod
    def from_dict(cls, value: Any) -> LegacyRunBinding:
        names = {"directory", "manifest_hash", "manifest_sha256", "journal_sha256", "head_sha256", "journal_tip"}
        if not isinstance(value, Mapping) or set(value) != names | {"format"} or value["format"] != _BINDING_FORMAT:
            raise ValueError("invalid legacy run binding schema")
        return cls(**{n: value[n] for n in names})

    @classmethod
    def capture(cls, directory: Path) -> LegacyRunBinding:
        """Read-only capture of a validated journal and its exact byte identities."""
        directory = _directory(directory)
        paths = [directory / n for n in ("manifest.json", "events.jsonl", "head.json")]
        before = [_stat(p) for p in paths]
        store = RunStore(directory, read_only=True)
        _locks(store)
        rows = store.events()
        hashes = [_file_hash(p) for p in paths]
        if before != [_stat(p) for p in paths]:
            raise ValueError("legacy run changed during capture")
        _locks(store)
        return cls(directory, store.manifest_hash, hashes[0], hashes[1], hashes[2],
                   rows[-1]["hash"] if rows else store.manifest_hash)


def _legacy_summary(binding: LegacyRunBinding) -> dict[str, Any]:
    if LegacyRunBinding.capture(binding.directory) != binding:
        raise ValueError("legacy original binding changed")
    store = RunStore(binding.directory, read_only=True)
    for row in store.events():
        if row.get("event") == "attempt_started":
            for name in ("attempt_id", "cell_id", "request_hash", "model", "endpoint"):
                _text(row.get(name), name)
            if not isinstance(row.get("hosted"), bool):
                raise ValueError("legacy hosted flag must be boolean")
            if not row["hosted"] and usd(row["liability_usd"]) != 0:
                raise ValueError("legacy local liability must be zero")
    ledger = SpendLedger(store, limit=str(store.manifest.get("budget_usd", "25")))
    summary = ledger.snapshot()
    if LegacyRunBinding.capture(binding.directory) != binding:
        raise ValueError("legacy original binding changed during import")
    return {"reported_cost_usd": summary["reported_cost_usd"],
            "reservations": {a: str(b) for a, b in sorted(ledger.reservations.items())},
            "attempt_ids": sorted(ledger.admissions),
            "unknown_attempt_ids": sorted(a for a in ledger.finished if a in ledger.reservations),
            "admission_stopped": summary["admission_stopped"]}


class AllocationLedger:
    """A single immutable allowance; shared accounting never resets on new runs."""
    def __init__(self, directory: Path, *, read_only: bool = False) -> None:
        self.directory = _directory(directory)
        self.read_only = read_only
        self.store = RunStore(self.directory, read_only=read_only)
        manifest = self.store.manifest
        if set(manifest) != {"format", "allocation_id", "limit_usd", "required_imports", "lock_identities"} or manifest["format"] != _FORMAT:
            raise ValueError("invalid allocation manifest schema")
        self.allocation_id = _text(manifest["allocation_id"], "allocation_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.allocation_id) is None:
            raise ValueError("invalid allocation ID")
        self.limit = usd(manifest["limit_usd"])
        if self.limit > _MAX_LIMIT:
            raise ValueError("shared allowance exceeds USD25")
        required = manifest["required_imports"]
        if not isinstance(required, (list, tuple)):
            raise ValueError("required imports must be an array")
        self.required_imports = tuple(LegacyRunBinding.from_dict(x) for x in required)
        if len({b.manifest_hash for b in self.required_imports}) != len(self.required_imports) or len({b.directory for b in self.required_imports}) != len(self.required_imports):
            raise ValueError("duplicate required legacy imports")
        self._mutex = threading.RLock()
        self._active_store: RunStore | None = None
        self._sequence = 0
        self._stopped = False
        self._reasons: set[str] = set()
        self._runs: dict[str, dict[str, Any]] = {}
        self._imports: dict[str, dict[str, Any]] = {}
        self._import_events: dict[str, str] = {}
        self._admissions: dict[str, dict[str, Any]] = {}
        self._reservations: dict[str, Decimal] = {}
        self._finished: set[str] = set()
        self._finished_rows: dict[str, dict[str, Any]] = {}
        self._run_ledgers: dict[str, SpendLedger] = {}
        self._unpaired: set[str] = set()
        self._pair_sequences: dict[str, int] = {}
        self._all_attempts: set[str] = set()
        self._unknown: set[str] = set()
        self._historical_unknown: set[str] = set()
        self._reconciliations: dict[str, dict[str, Any]] = {}
        self._bounded_unknown: dict[str, dict[str, Any]] = {}
        self._held_bounds: dict[str, Decimal] = {}
        self._held_by_run: dict[str, Decimal] = {}
        self._proof_claims: dict[tuple[str, str], str] = {}
        self._proof_documents: dict[str, str] = {}
        self._externally_verified = Decimal(0)
        self._external_by_run: dict[str, Decimal] = {}
        self._charged = Decimal(0)
        self._check_locks()
        with self.transaction():
            self._sync()

    @classmethod
    def create(cls, directory: Path, *, allocation_id: str, limit: str = "25",
               required_imports: tuple[LegacyRunBinding, ...] = ()) -> AllocationLedger:
        """Explicit exclusive initialization; never implicitly called by a run."""
        directory = _directory(directory)
        _text(allocation_id, "allocation_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", allocation_id) is None:
            raise ValueError("invalid allocation ID")
        amount = usd(limit)
        if amount > _MAX_LIMIT:
            raise ValueError("shared allowance exceeds USD25")
        if not isinstance(required_imports, tuple) or any(not isinstance(b, LegacyRunBinding) for b in required_imports):
            raise ValueError("required imports must be a tuple of exact bindings")
        if len({b.manifest_hash for b in required_imports}) != len(required_imports) or len({b.directory for b in required_imports}) != len(required_imports):
            raise ValueError("duplicate required legacy imports")
        RunStore.create_at(directory, {"format": _FORMAT, "allocation_id": allocation_id,
                                     "limit_usd": str(amount), "required_imports": [b.to_dict() for b in required_imports]})
        return cls(directory)

    def identity(self) -> dict[str, str]:
        with self.transaction():
            self._sync()
            return {"directory": str(self.directory), "allocation_id": self.allocation_id,
                    "manifest_hash": self.store.manifest_hash}

    def _check_locks(self) -> None:
        _locks(self.store)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        with self._mutex, self.store.transaction():
            self._check_locks()
            yield
            self._check_locks()

    def _sync(self) -> None:
        rows = self.store._read()
        with localcontext(currency_context()):
            for row in rows[self._sequence:]:
                kind = row.get("event")
                if not isinstance(kind, str) or kind not in _EVENT_FIELDS or set(row) != _EVENT_FIELDS[kind] | {"event", "sequence", "previous", "timestamp", "hash"}:
                    raise ValueError("invalid allocation event schema")
                if kind == "allocation_run_bound":
                    binding = row["binding"]
                    if not isinstance(binding, Mapping) or set(binding) != {"directory", "manifest_hash", "manifest_sha256", "manifest_identity"}:
                        raise ValueError("invalid run binding schema")
                    key = _digest(binding["manifest_hash"])
                    if key in self._runs or key in self._imports or any(x["directory"] == binding["directory"] for x in self._runs.values()) or any(x["binding"]["directory"] == binding["directory"] for x in self._imports.values()):
                        raise ValueError("duplicate allocation run binding")
                    _directory(binding["directory"])
                    _digest(binding["manifest_sha256"])
                    ident = binding["manifest_identity"]
                    if not isinstance(ident, (list, tuple)) or len(ident) != 5 or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in ident):
                        raise ValueError("invalid run manifest identity")
                    self._runs[key] = dict(binding)
                elif kind == "allocation_run_imported":
                    binding = LegacyRunBinding.from_dict(row["binding"])
                    key = binding.manifest_hash
                    if key in self._imports or key in self._runs or any(x["directory"] == str(binding.directory) for x in self._runs.values()) or any(x["binding"]["directory"] == str(binding.directory) for x in self._imports.values()):
                        raise ValueError("duplicate allocation legacy import")
                    actual = _legacy_summary(binding)
                    if actual != row["accounting"] or self._all_attempts.intersection(actual["attempt_ids"]):
                        raise ValueError("legacy accounting/collision mismatch")
                    self._imports[key] = {"binding": binding.to_dict(), "accounting": actual}
                    self._import_events[key] = row["hash"]
                    self._all_attempts.update(actual["attempt_ids"])
                    self._charged += usd_total(actual["reported_cost_usd"])
                    self._reservations.update({a: usd(b) for a, b in actual["reservations"].items()})
                    self._unknown.update(actual["unknown_attempt_ids"])
                    self._historical_unknown.update(actual["unknown_attempt_ids"])
                    # The legacy aggregate stop is lossy. Billing uncertainty
                    # can be resolved separately; structural rejection and
                    # original reported-cost breaches cannot be administratively
                    # cleared by an external document.
                    if self._legacy_structural_stop(binding):
                        self._stopped = True
                        self._reasons.add("legacy_accounting_stopped")
                elif kind == "allocation_legacy_billing_reconciled":
                    proposal = self._validate_reconciliation(row, expected_tip=row["previous"])
                    attempt = proposal["attempt_id"]
                    if attempt in self._reconciliations:
                        raise ValueError("duplicate legacy billing reconciliation")
                    self._check_proof_reuse(proposal)
                    original_bound = usd(proposal["original_liability_usd"])
                    bound = self._held_bounds.get(attempt, original_bound)
                    cost = usd(proposal["cost_usd"])
                    self._reconciliations[attempt] = row
                    self._proof_claims[(proposal["authority"], proposal["reference"])] = attempt
                    self._proof_documents[proposal["document_sha256"]] = attempt
                    self._externally_verified += cost
                    key = proposal["legacy_manifest_hash"]
                    self._external_by_run[key] = self._external_by_run.get(key, Decimal(0)) + cost
                    self._reservations.pop(attempt, None)
                    held = self._held_bounds.pop(attempt, Decimal(0))
                    self._held_by_run[key] = self._held_by_run.get(key, Decimal(0)) - held
                    self._unknown.remove(attempt)
                    if cost > bound or cost > original_bound:
                        self._stopped = True
                        self._reasons.add("externally_verified_cost_exceeds_reservation")
                    binding = LegacyRunBinding.from_dict(self._imports[key]["binding"])
                    original = RunStore(binding.directory, read_only=True)
                    if self._legacy_liability(key) > usd(original.manifest.get("budget_usd", "25")):
                        self._stopped = True
                        self._reasons.add("externally_verified_cost_exceeds_run_limit")
                elif kind == "allocation_legacy_unknown_bounded":
                    proposal = self._validate_bounded_unknown(row, expected_tip=row["previous"])
                    attempt = proposal["attempt_id"]
                    if attempt in self._bounded_unknown or attempt in self._reconciliations:
                        raise ValueError("duplicate or reconciled bounded UNKNOWN")
                    self._check_proof_reuse(proposal)
                    self._check_bound_limits(proposal)
                    bound = usd(proposal["upper_bound_usd"])
                    key = proposal["legacy_manifest_hash"]
                    self._bounded_unknown[attempt] = row
                    self._held_bounds[attempt] = bound
                    self._held_by_run[key] = self._held_by_run.get(key, Decimal(0)) + bound
                    self._proof_claims[(proposal["authority"], proposal["reference"])] = attempt
                    self._proof_documents[proposal["document_sha256"]] = attempt
                    del self._reservations[attempt]
                elif kind == "allocation_attempt_started":
                    attempt = _text(row["attempt_id"], "attempt_id")
                    key = _digest(row["run_manifest_hash"])
                    if attempt in self._all_attempts or key not in self._runs:
                        raise ValueError("duplicate or unbound global attempt")
                    if self._active_store is not None and key != self._active_store.manifest_hash:
                        raise ValueError("new global admission belongs to another executor")
                    for name in ("cell_id", "request_hash", "model", "endpoint"):
                        _text(row[name], name)
                    bound = usd(row["liability_usd"])
                    if self._stopped or self._blocking_unknown() or not self._required_complete() or self._total_liability() + bound > self.limit:
                        raise ValueError("global attempt violates shared admission")
                    self._all_attempts.add(attempt)
                    self._admissions[attempt] = row
                    self._unpaired.add(attempt)
                    self._reservations[attempt] = bound
                elif kind == "allocation_attempt_finished":
                    attempt = _text(row["attempt_id"], "attempt_id")
                    admission = self._admissions.get(attempt)
                    if admission is None or attempt in self._finished or row["run_manifest_hash"] != admission["run_manifest_hash"] or row["cell_id"] != admission["cell_id"]:
                        raise ValueError("invalid global finish identity")
                    _digest(row["receipt_sha256"])
                    _digest(row["run_event_hash"])
                    # The global journal is untrusted input too. A valid hash
                    # chain alone cannot release a reservation using a forged
                    # zero charge; verify the exact durable per-run receipt
                    # before this reduction changes spend or admission state.
                    self._verify_finish(row)
                    bound = self._reservations[attempt]
                    self._finished.add(attempt)
                    self._finished_rows[attempt] = row
                    if row["cost_status"] == "reported":
                        cost = usd(row["cost_usd"])
                        self._charged += cost
                        del self._reservations[attempt]
                        if cost > bound:
                            self._stopped = True
                            self._reasons.add("reported_cost_exceeds_reservation")
                    elif row["cost_status"] == "unknown" and row["cost_usd"] is None:
                        self._unknown.add(attempt)
                        self._historical_unknown.add(attempt)
                        self._stopped = True
                        self._reasons.add("unknown_billing")
                    else:
                        raise ValueError("invalid global billing provenance")
                elif kind == "allocation_stopped":
                    if row.get("reason") not in _STOP_REASONS:
                        raise ValueError("invalid allocation stop reason")
                    self._stopped = True
                    self._reasons.add(row["reason"])
                else:
                    raise ValueError("invalid allocation event")
                # A later hold or exact charge cannot erase an earlier cap
                # breach on full replay that already stopped an incremental
                # reader. Enforce the same boundary after every durable event.
                if self._total_liability() > self.limit:
                    self._stopped = True
                    self._reasons.add("total_liability_exceeds_allocation")
            if self._charged > self.limit:
                self._stopped = True
                self._reasons.add("reported_cost_exceeds_allocation")
            if self._effective_cost() > self.limit:
                self._stopped = True
                self._reasons.add("effective_cost_exceeds_allocation")
        self._sequence = len(rows)
        # A long-lived object must not overlook removal/replacement of proof
        # after it released a reservation. Reopen and every admission recheck it.
        for reconciliation in self._reconciliations.values():
            self._validate_reconciliation(reconciliation, expected_tip=reconciliation["previous"])
        for bounded in self._bounded_unknown.values():
            self._validate_bounded_unknown(bounded, expected_tip=bounded["previous"])

    def _effective_cost(self) -> Decimal:
        with localcontext(currency_context()):
            return self._charged + self._externally_verified

    def _blocking_unknown(self) -> set[str]:
        return self._unknown.difference(self._held_bounds)

    def _held_total(self) -> Decimal:
        return sum(self._held_bounds.values(), Decimal(0))

    def _total_liability(self) -> Decimal:
        return self._effective_cost() + self._held_total() + sum(self._reservations.values(), Decimal(0))

    def _legacy_liability(self, key: str) -> Decimal:
        accounting = self._imports[key]["accounting"]
        pending = sum((self._reservations[a] for a in accounting["attempt_ids"] if a in self._reservations), Decimal(0))
        return usd_total(accounting["reported_cost_usd"]) + self._external_by_run.get(key, Decimal(0)) + self._held_by_run.get(key, Decimal(0)) + pending

    def _check_proof_reuse(self, proposal: dict[str, Any]) -> None:
        for existing in (self._proof_claims.get((proposal["authority"], proposal["reference"])),
                         self._proof_documents.get(proposal["document_sha256"])):
            if existing is not None and existing != proposal["attempt_id"]:
                raise ValueError("provider reference/document already attributed to another attempt")

    def _legacy_structural_stop(self, binding: LegacyRunBinding) -> bool:
        store = RunStore(binding.directory, read_only=True)
        rows = store.events()
        ledger = SpendLedger(store, limit=str(store.manifest.get("budget_usd", "25")))
        return (any(row.get("event") == "accounting_rejected" for row in rows)
                or ledger.charged > ledger.limit
                or any(row.get("event") == "attempt_finished"
                       and row["receipt"]["cost_status"] == "reported"
                       and usd(row["receipt"]["cost_usd"]) > usd(ledger.admissions[row["receipt"]["attempt_id"]]["liability_usd"])
                       for row in rows))

    def _required_complete(self) -> bool:
        return all(b.manifest_hash in self._imports and self._imports[b.manifest_hash]["binding"] == b.to_dict() for b in self.required_imports)

    def _reconciliation_target(self, manifest_hash: str, attempt_id: str, tip: str) -> dict[str, Any]:
        imported = self._imports.get(_digest(manifest_hash))
        if imported is None:
            raise ValueError("reconciliation requires an imported legacy run")
        binding = LegacyRunBinding.from_dict(imported["binding"])
        if LegacyRunBinding.capture(binding.directory) != binding:
            raise ValueError("legacy original changed")
        store = RunStore(binding.directory, read_only=True)
        rows = store.events()
        starts = [r for r in rows if r.get("event") == "attempt_started" and r.get("attempt_id") == attempt_id]
        finishes = [r for r in rows if r.get("event") == "attempt_finished" and r.get("receipt", {}).get("attempt_id") == attempt_id]
        if len(starts) != 1 or len(finishes) != 1 or starts[0]["hosted"] is not True:
            raise ValueError("reconciliation requires exactly one finished hosted legacy attempt")
        start, finish = starts[0], finishes[0]
        receipt = finish["receipt"]
        if receipt["cost_status"] != "unknown" or receipt["cost_usd"] is not None:
            raise ValueError("only original finished UNKNOWN billing is reconcilable")
        return {"allocation": {"directory": str(self.directory), "allocation_id": self.allocation_id,
                               "manifest_hash": self.store.manifest_hash, "journal_tip": _digest(tip)},
                "legacy_run": binding.to_dict(), "import_event_hash": self._import_events[manifest_hash],
                "attempt": {"attempt_id": attempt_id, "cell_id": start["cell_id"], "request_hash": start["request_hash"],
                            "model": start["model"], "endpoint": start["endpoint"], "liability_usd": start["liability_usd"],
                            "original_provider": receipt.get("provider"), "original_response_id": receipt.get("response_id"),
                            "timestamp": receipt["timestamp"], "start_event_hash": start["hash"],
                            "finish_event_hash": finish["hash"], "receipt_sha256": content_hash(receipt)}}

    def reconciliation_target(self, manifest_hash: str, attempt_id: str) -> dict[str, Any]:
        """Read an exact target; this supplies no provider evidence or approval."""
        with self.transaction():
            self._sync()
            rows = self.store._read()
            tip = rows[-1]["hash"] if rows else self.store.manifest_hash
            return self._reconciliation_target(manifest_hash, _text(attempt_id, "attempt_id"), tip)

    def _validate_reconciliation(self, row: Mapping[str, Any], *, expected_tip: str) -> dict[str, Any]:
        evidence_ref = _retained_proof(row["evidence"])
        review_ref = _retained_proof(row["review"])
        document_ref = _retained_proof(row["document"])
        evidence, _ = _proof(Path(evidence_ref["path"]), evidence_ref["sha256"], evidence_ref)
        review, _ = _proof(Path(review_ref["path"]), review_ref["sha256"], review_ref)
        document, _ = _proof(Path(document_ref["path"]), document_ref["sha256"], document_ref)
        evidence = _object(evidence, {"format", "scope", "target", "source_kind", "document", "authority", "reference", "collected_by", "currency", "cost_usd"}, "external billing evidence")
        if evidence["format"] != "dafjev.external-billing-evidence/1" or evidence["scope"] != "exact_attempt_account_charge" or evidence["currency"] != "USD":
            raise ValueError("billing evidence must establish an exact USD attempt charge")
        if not isinstance(evidence["cost_usd"], str):
            raise ValueError("external charge must be an exact decimal string")
        cost = usd(evidence["cost_usd"])
        for name in ("authority", "reference", "collected_by"):
            if len(_text(evidence[name], name)) > 512:
                raise ValueError("billing evidence text exceeds limit")
        target = _object(evidence["target"], {"allocation", "legacy_run", "import_event_hash", "attempt"}, "reconciliation target")
        legacy = LegacyRunBinding.from_dict(target["legacy_run"])
        attempt = target["attempt"]
        if not isinstance(attempt, Mapping):
            raise ValueError("invalid attempt target")
        expected = self._reconciliation_target(legacy.manifest_hash, _text(attempt.get("attempt_id"), "attempt_id"), expected_tip)
        if target != expected:
            raise ValueError("external billing target does not match exact allocation/import/attempt cut")
        declared_document = _object(evidence["document"], {"path", "sha256", "bytes"}, "provider document reference")
        if dict(declared_document) != {k: document_ref[k] for k in ("path", "sha256", "bytes")}:
            raise ValueError("provider document binding changed")
        review = _object(review, {"format", "decision", "reviewer", "evidence_sha256", "document_sha256", "allocation_tip", "provider_origin_verified", "unique_exact_attempt_verified", "usd_account_charge_verified"}, "independent billing review")
        if (review["format"] != "dafjev.external-billing-review/1" or review["decision"] != "approve_exact_attempt_charge"
                or _text(review["reviewer"], "reviewer") == evidence["collected_by"]
                or review["evidence_sha256"] != evidence_ref["sha256"] or review["document_sha256"] != document_ref["sha256"]
                or review["allocation_tip"] != expected_tip
                or any(review[name] is not True for name in ("provider_origin_verified", "unique_exact_attempt_verified", "usd_account_charge_verified"))):
            raise ValueError("independent exact-attempt operator review is required")
        if evidence["source_kind"] == "generation_metadata":
            if not isinstance(document, Mapping) or set(document) != {"data"} or not isinstance(document["data"], Mapping):
                raise ValueError("invalid generation metadata")
            data = document["data"]
            original_id = attempt["original_response_id"]
            if (not isinstance(original_id, str) or not original_id or data.get("id") != original_id
                    or data.get("id") != evidence["reference"] or data.get("model") != attempt["model"]
                    or isinstance(data.get("total_cost"), bool) or usd(data.get("total_cost")) != cost):
                raise ValueError("generation proof requires original response ID/model/exact charge")
        elif evidence["source_kind"] == "provider_statement":
            statement = _object(document, {"format", "scope", "authority", "reference", "request", "currency", "cost_usd"}, "exact provider statement")
            request = dict(attempt)
            if (statement["format"] != "dafjev.exact-provider-charge-statement/1" or statement["scope"] != "exact_attempt_account_charge"
                    or statement["authority"] != evidence["authority"] or statement["reference"] != evidence["reference"]
                    or statement["request"] != request or statement["currency"] != "USD"
                    or not isinstance(statement["cost_usd"], str) or usd(statement["cost_usd"]) != cost):
                raise ValueError("provider statement must uniquely attribute the exact attempt and USD charge")
        else:
            raise ValueError("unsupported billing evidence tier; aggregate/absence/tariff cannot reconcile")
        return {"attempt_id": attempt["attempt_id"], "legacy_manifest_hash": legacy.manifest_hash,
                "cost_usd": str(cost), "original_liability_usd": attempt["liability_usd"],
                "authority": evidence["authority"], "reference": evidence["reference"], "document_sha256": document_ref["sha256"],
                "provider_authentication": "trusted_independent_local_operator_attestation; not automatic authentication"}

    def _reconciliation_proposal(self, *, evidence: Path, evidence_sha256: str,
                                 review: Path, review_sha256: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
        value, evidence_ref = _proof(evidence, evidence_sha256)
        _, review_ref = _proof(review, review_sha256)
        if not isinstance(value, Mapping) or not isinstance(value.get("document"), Mapping):
            raise ValueError("invalid external billing evidence")
        declared = _object(value["document"], {"path", "sha256", "bytes"}, "provider document reference")
        _, document_ref = _proof(Path(_text(declared["path"], "document path")), declared["sha256"])
        candidate = {"event": "allocation_legacy_billing_reconciled", "evidence": evidence_ref,
                     "review": review_ref, "document": document_ref}
        existing = next((r for r in self._reconciliations.values() if all(r[n] == candidate[n] for n in ("evidence", "review", "document"))), None)
        rows = self.store._read()
        tip = existing["previous"] if existing is not None else rows[-1]["hash"] if rows else self.store.manifest_hash
        proposal = self._validate_reconciliation(candidate, expected_tip=tip)
        if proposal["attempt_id"] in self._reconciliations and existing is None:
            raise ValueError("conflicting duplicate billing reconciliation")
        self._check_proof_reuse(proposal)
        return candidate, proposal, existing is not None

    def preview_reconciliation(self, *, evidence: Path, evidence_sha256: str,
                               review: Path, review_sha256: str) -> dict[str, Any]:
        """Validate evidence offline without writes, leases, or admission changes."""
        with self.transaction(), localcontext(currency_context()):
            self._sync()
            self._validate_retained_runs()
            _, proposal, duplicate = self._reconciliation_proposal(evidence=evidence, evidence_sha256=evidence_sha256,
                                                                  review=review, review_sha256=review_sha256)
            return {"operation": "preview_reconciliation", "already_recorded": duplicate,
                    **{k: v for k, v in proposal.items() if k not in {"authority", "reference"}},
                    "would_exceed_original_bound": usd(proposal["cost_usd"]) > usd(proposal["original_liability_usd"]),
                    "effective_cost_after_usd": str(self._effective_cost() + (Decimal(0) if duplicate else usd(proposal["cost_usd"]))),
                    "evidence": "offline_local_attestation; no inference or provider lookup"}

    def reconcile(self, *, evidence: Path, evidence_sha256: str,
                  review: Path, review_sha256: str) -> dict[str, Any]:
        """Explicit append-only recovery of one finished UNKNOWN legacy charge."""
        if self.read_only or self._active_store is not None:
            raise ValueError("reconciliation requires a writable inactive allocation")
        with self.store.lease(), self.transaction():
            self._sync()
            self._validate_retained_runs()
            candidate, proposal, duplicate = self._reconciliation_proposal(evidence=evidence, evidence_sha256=evidence_sha256,
                                                                         review=review, review_sha256=review_sha256)
            if not duplicate:
                try:
                    self.store.append(candidate)
                    self._sync()
                except BaseException:
                    self.reject("reconciliation_durability_failure")
                    raise
            return {"operation": "reconcile", "already_recorded": duplicate,
                    **{k: v for k, v in proposal.items() if k not in {"authority", "reference"}}, "accounting": self.snapshot()}

    def bounded_unknown_target(self, manifest_hash: str, attempt_id: str) -> dict[str, Any]:
        """Read an eligible finished imported UNKNOWN; no charge is inferred."""
        with self.transaction():
            self._sync()
            rows = self.store._read()
            tip = rows[-1]["hash"] if rows else self.store.manifest_hash
            target = self._reconciliation_target(manifest_hash, _text(attempt_id, "attempt_id"), tip)
            if (self._stopped or attempt_id in self._bounded_unknown or attempt_id in self._reconciliations
                    or self._legacy_structural_stop(LegacyRunBinding.from_dict(target["legacy_run"]))):
                raise ValueError("bounded UNKNOWN requires an eligible unbounded legacy attempt without structural stops")
            return target

    def _validate_bounded_unknown(self, row: Mapping[str, Any], *, expected_tip: str) -> dict[str, Any]:
        evidence_ref = _retained_proof(row["evidence"])
        review_ref = _retained_proof(row["review"])
        document_ref = _retained_proof(row["document"])
        evidence, _ = _proof(Path(evidence_ref["path"]), evidence_ref["sha256"], evidence_ref)
        review, _ = _proof(Path(review_ref["path"]), review_ref["sha256"], review_ref)
        document, _ = _proof(Path(document_ref["path"]), document_ref["sha256"], document_ref)
        evidence = _object(evidence, {"format", "scope", "target", "source_kind", "document", "authority", "reference", "collected_by", "currency", "upper_bound_usd"}, "bounded UNKNOWN evidence")
        if (evidence["format"] != "dafjev.bounded-unknown-evidence/1"
                or evidence["scope"] != "exact_finished_attempt_upper_bound"
                or evidence["source_kind"] != "reviewed_request_tariff_contract" or evidence["currency"] != "USD"):
            raise ValueError("bounded UNKNOWN requires a reviewed exact-request USD tariff contract")
        if not isinstance(evidence["upper_bound_usd"], str):
            raise ValueError("upper bound must be an exact decimal string")
        bound = usd(evidence["upper_bound_usd"])
        for name in ("authority", "reference", "collected_by"):
            if len(_text(evidence[name], name)) > 512:
                raise ValueError("bounded UNKNOWN evidence text exceeds limit")
        target = _object(evidence["target"], {"allocation", "legacy_run", "import_event_hash", "attempt"}, "bounded UNKNOWN target")
        legacy = LegacyRunBinding.from_dict(target["legacy_run"])
        attempt = target["attempt"]
        if not isinstance(attempt, Mapping):
            raise ValueError("invalid bounded UNKNOWN attempt target")
        expected = self._reconciliation_target(legacy.manifest_hash, _text(attempt.get("attempt_id"), "attempt_id"), expected_tip)
        if target != expected or self._legacy_structural_stop(legacy):
            raise ValueError("bounded UNKNOWN target/cut changed or has a structural stop")
        declared = _object(evidence["document"], {"path", "sha256", "bytes"}, "tariff document reference")
        if dict(declared) != {k: document_ref[k] for k in ("path", "sha256", "bytes")}:
            raise ValueError("tariff document binding changed")
        review = _object(review, {"format", "decision", "reviewer", "evidence_sha256", "document_sha256", "allocation_tip", "target_sha256", "contract_origin_verified", "unique_exact_attempt_verified", "upper_bound_verified", "original_reservation_reduction_verified", "rationale"}, "independent bounded UNKNOWN review")
        if (review["format"] != "dafjev.bounded-unknown-review/1"
                or review["decision"] != "approve_bounded_unknown_continuation"
                or len(_text(review["reviewer"], "reviewer")) > 512 or review["reviewer"] == evidence["collected_by"]
                or review["evidence_sha256"] != evidence_ref["sha256"] or review["document_sha256"] != document_ref["sha256"]
                or review["allocation_tip"] != expected_tip or review["target_sha256"] != content_hash(expected)
                or any(review[name] is not True for name in ("contract_origin_verified", "unique_exact_attempt_verified", "upper_bound_verified"))
                or not isinstance(review["original_reservation_reduction_verified"], bool)
                or (bound < usd(attempt["liability_usd"]) and review["original_reservation_reduction_verified"] is not True)
                or len(_text(review["rationale"], "review rationale")) > 4096):
            raise ValueError("independent exact-contract upper-bound review is required")
        contract = _object(document, {"format", "scope", "authority", "reference", "request", "currency", "upper_bound_usd", "rationale"}, "exact request tariff bound")
        if (contract["format"] != "dafjev.exact-request-tariff-bound/1"
                or contract["scope"] != "exact_finished_attempt_upper_bound"
                or contract["authority"] != evidence["authority"] or contract["reference"] != evidence["reference"]
                or contract["request"] != dict(attempt) or contract["currency"] != "USD"
                or not isinstance(contract["upper_bound_usd"], str) or usd(contract["upper_bound_usd"]) != bound
                or len(_text(contract["rationale"], "contract rationale")) > 4096):
            raise ValueError("tariff document must bind the exact attempt and reviewed USD upper bound")
        return {"attempt_id": attempt["attempt_id"], "legacy_manifest_hash": legacy.manifest_hash,
                "upper_bound_usd": str(bound), "original_liability_usd": attempt["liability_usd"],
                "authority": evidence["authority"], "reference": evidence["reference"], "document_sha256": document_ref["sha256"],
                "billing_provenance": "reviewed_upper_bound_only; observed charge remains UNKNOWN",
                "provider_authentication": "trusted_independent_local_operator_attestation; not automatic authentication"}

    def _check_bound_limits(self, proposal: Mapping[str, Any]) -> None:
        attempt, key = proposal["attempt_id"], proposal["legacy_manifest_hash"]
        if self._stopped or attempt not in self._unknown or attempt not in self._reservations:
            raise ValueError("bounded UNKNOWN cannot override a stop or reuse a completed target")
        increase = usd(proposal["upper_bound_usd"]) - self._reservations[attempt]
        binding = LegacyRunBinding.from_dict(self._imports[key]["binding"])
        original = RunStore(binding.directory, read_only=True)
        if self._legacy_liability(key) + increase > usd(original.manifest.get("budget_usd", "25")):
            raise BudgetStopped("reviewed upper bounds exceed original run USD limit")
        if self._total_liability() + increase > self.limit:
            raise BudgetStopped("reviewed upper bounds exceed shared USD allocation")

    def _bounded_unknown_proposal(self, *, evidence: Path, evidence_sha256: str,
                                  review: Path, review_sha256: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
        value, evidence_ref = _proof(evidence, evidence_sha256)
        _, review_ref = _proof(review, review_sha256)
        if not isinstance(value, Mapping) or not isinstance(value.get("document"), Mapping):
            raise ValueError("invalid bounded UNKNOWN evidence")
        declared = _object(value["document"], {"path", "sha256", "bytes"}, "tariff document reference")
        _, document_ref = _proof(Path(_text(declared["path"], "document path")), declared["sha256"])
        candidate = {"event": "allocation_legacy_unknown_bounded", "evidence": evidence_ref,
                     "review": review_ref, "document": document_ref}
        existing = next((r for r in self._bounded_unknown.values() if all(r[n] == candidate[n] for n in ("evidence", "review", "document"))), None)
        rows = self.store._read()
        tip = existing["previous"] if existing is not None else rows[-1]["hash"] if rows else self.store.manifest_hash
        proposal = self._validate_bounded_unknown(candidate, expected_tip=tip)
        attempt = proposal["attempt_id"]
        if attempt in self._reconciliations:
            raise ValueError("reconciled billing cannot become bounded UNKNOWN")
        if existing is None:
            if attempt in self._bounded_unknown:
                raise ValueError("conflicting or reconciled bounded UNKNOWN target")
            self._check_bound_limits(proposal)
        self._check_proof_reuse(proposal)
        return candidate, proposal, existing is not None

    def preview_bounded_unknown(self, *, evidence: Path, evidence_sha256: str,
                                review: Path, review_sha256: str) -> dict[str, Any]:
        """Validate a reviewed hold offline; preserve all UNKNOWN and receipts."""
        with self.transaction(), localcontext(currency_context()):
            self._sync()
            self._validate_retained_runs()
            _, proposal, duplicate = self._bounded_unknown_proposal(evidence=evidence, evidence_sha256=evidence_sha256,
                                                                   review=review, review_sha256=review_sha256)
            increase = Decimal(0) if duplicate else usd(proposal["upper_bound_usd"]) - self._reservations[proposal["attempt_id"]]
            return {"operation": "preview_bounded_unknown", "already_recorded": duplicate,
                    **{k: v for k, v in proposal.items() if k not in {"authority", "reference"}},
                    "total_liability_after_usd": str(self._total_liability() + increase),
                    "evidence": "offline_local_attestation; no inference or provider lookup"}

    def accept_bounded_unknown(self, *, evidence: Path, evidence_sha256: str,
                               review: Path, review_sha256: str) -> dict[str, Any]:
        """Append a reviewed hold, never a measured charge or receipt rewrite."""
        if self.read_only or self._active_store is not None:
            raise ValueError("bounded UNKNOWN acceptance requires a writable inactive allocation")
        with self.store.lease(), self.transaction(), localcontext(currency_context()):
            self._sync()
            self._validate_retained_runs()
            candidate, proposal, duplicate = self._bounded_unknown_proposal(evidence=evidence, evidence_sha256=evidence_sha256,
                                                                           review=review, review_sha256=review_sha256)
            if not duplicate:
                try:
                    self.store.append(candidate)
                    self._sync()
                except BaseException:
                    self.reject("bounded_unknown_durability_failure")
                    raise
            return {"operation": "accept_bounded_unknown", "already_recorded": duplicate,
                    **{k: v for k, v in proposal.items() if k not in {"authority", "reference"}}, "accounting": self.snapshot()}

    def require_execution(self, store: RunStore) -> None:
        if self.read_only or self._active_store is not store or not self.store._lease_active or not store._lease_active:
            raise ValueError("shared accounting requires the current allocation execution lease")
        self._check_locks()
        _locks(store)

    def _run_binding(self, store: RunStore) -> dict[str, Any]:
        store._check_manifest()
        _locks(store)
        frozen = store.manifest.get("shared_allocation")
        expected = {"directory": str(self.directory), "allocation_id": self.allocation_id, "manifest_hash": self.store.manifest_hash}
        if not isinstance(frozen, Mapping) or dict(frozen) != expected:
            raise ValueError("run has no matching frozen shared allocation")
        if "budget_usd" not in store.manifest or usd(store.manifest["budget_usd"]) > self.limit:
            raise ValueError("frozen run budget exceeds or omits shared allowance")
        return {"directory": str(_directory(store.directory)), "manifest_hash": store.manifest_hash,
                "manifest_sha256": _file_hash(store.directory / "manifest.json"),
                "manifest_identity": list(_stat(store.directory / "manifest.json"))}

    def _check_run(self, store: RunStore) -> None:
        binding = self._run_binding(store)
        if self._runs.get(store.manifest_hash) != binding:
            raise ValueError("registered run identity changed")

    def _run_ledger(self, store: RunStore) -> SpendLedger:
        ledger = self._run_ledgers.get(store.manifest_hash)
        if ledger is None or ledger.store is not store:
            ledger = SpendLedger(store, limit=str(store.manifest["budget_usd"]))
            self._run_ledgers[store.manifest_hash] = ledger
        ledger._sync()
        return ledger

    def _verify_pair(self, admission: dict[str, Any], ledger: SpendLedger) -> None:
        attempt = admission["attempt_id"]
        start = ledger.admissions.get(attempt)
        if start is None or start.get("hosted") is not True or any(start.get(n) != admission.get(n) for n in ("cell_id", "request_hash", "model", "endpoint", "liability_usd")):
            raise ValueError("global/per-run admission pair mismatch")
        self._unpaired.discard(attempt)

    def _verify_prior_pairs(self, store: RunStore) -> None:
        # One allocation executor owns the whole cut. Also inspect newly added
        # intents in previously bound runs: filtering only the active run could
        # overlook a forged zero reservation or unbacked foreign-run attempt.
        for key, binding in self._runs.items():
            if key == store.manifest_hash:
                retained = store
            else:
                cached = self._run_ledgers.get(key)
                retained = cached.store if cached is not None else RunStore(Path(binding["directory"]), read_only=True)
            self._verify_run_pairs(retained)
        if self._unpaired:
            raise ValueError("global/per-run admission pair mismatch")

    def _verify_run_pairs(self, store: RunStore) -> None:
        ledger = self._run_ledger(store)
        rows = store._read()
        for row in rows[self._pair_sequences.get(store.manifest_hash, 0):]:
            if row.get("event") != "attempt_started":
                continue
            if row.get("hosted") is True:
                admission = self._admissions.get(row["attempt_id"])
                if admission is None or admission["run_manifest_hash"] != store.manifest_hash:
                    raise ValueError("hosted run intent has no matching global reservation")
                self._verify_pair(admission, ledger)
            elif row.get("hosted") is not False or usd(row["liability_usd"]) != 0:
                raise ValueError("invalid local admission accounting")
        self._pair_sequences[store.manifest_hash] = len(rows)
        for attempt in tuple(self._unpaired):
            admission = self._admissions[attempt]
            if admission["run_manifest_hash"] == store.manifest_hash:
                self._verify_pair(admission, ledger)

    def _verify_finish(self, row: dict[str, Any]) -> None:
        key = row["run_manifest_hash"]
        binding = self._runs[key]
        ledger = self._run_ledgers.get(key)
        if ledger is None:
            retained = RunStore(Path(binding["directory"]), read_only=True)
            ledger = SpendLedger(retained, limit=str(retained.manifest["budget_usd"]))
            self._run_ledgers[key] = ledger
        if self._run_binding(ledger.store) != binding:
            raise ValueError("retained run binding changed")
        ledger._sync()
        attempt = row["attempt_id"]
        self._verify_pair(self._admissions[attempt], ledger)
        if attempt not in ledger.finished:
            raise ValueError("global finish has no durable per-run receipt")
        finished = next(r for r in reversed(ledger.store._read()) if r.get("event") == "attempt_finished" and r["receipt"]["attempt_id"] == attempt)
        if finished["cell_id"] != row["cell_id"] or finished["hash"] != row["run_event_hash"] or content_hash(finished["receipt"]) != row["receipt_sha256"] or any(finished["receipt"].get(n) != row[n] for n in ("cost_status", "cost_usd")):
            raise ValueError("global/per-run finished receipt changed")

    def _validate_retained_runs(self) -> None:
        for key, binding in self._runs.items():
            store = RunStore(Path(binding["directory"]), read_only=True)
            if self._run_binding(store) != binding:
                raise ValueError("retained run manifest identity changed")
            rows = store.events()
            ledger = SpendLedger(store, limit=str(store.manifest["budget_usd"]))
            finishes = {r["receipt"]["attempt_id"]: r for r in rows if r.get("event") == "attempt_finished"}
            starts = {r["attempt_id"]: r for r in rows if r.get("event") == "attempt_started"}
            if len(finishes) != sum(r.get("event") == "attempt_finished" for r in rows) or len(starts) != sum(r.get("event") == "attempt_started" for r in rows):
                raise ValueError("duplicate retained run attempt")
            for attempt, run_start in starts.items():
                if run_start.get("hosted") is True and (attempt not in self._admissions or self._admissions[attempt]["run_manifest_hash"] != key):
                    raise ValueError("hosted run intent has no matching global reservation")
            for attempt, admission in self._admissions.items():
                if admission["run_manifest_hash"] != key:
                    continue
                start = starts.get(attempt)
                if start is not None and (start.get("hosted") is not True or any(start.get(n) != admission.get(n) for n in ("cell_id", "request_hash", "model", "endpoint", "liability_usd"))):
                    raise ValueError("retained per-run admission mismatch")
                if start is not None:
                    self._unpaired.discard(attempt)
                if attempt in self._finished:
                    finished_row = finishes.get(attempt)
                    global_row = self._finished_rows[attempt]
                    if start is None or finished_row is None or finished_row["hash"] != global_row["run_event_hash"] or content_hash(finished_row["receipt"]) != global_row["receipt_sha256"] or any(finished_row["receipt"].get(n) != global_row[n] for n in ("cost_status", "cost_usd")):
                        raise ValueError("retained per-run receipt changed")
            self._run_ledgers[key] = ledger
            self._pair_sequences[key] = len(rows)
        for value in self._imports.values():
            legacy_binding = LegacyRunBinding.from_dict(value["binding"])
            if LegacyRunBinding.capture(legacy_binding.directory) != legacy_binding:
                raise ValueError("retained legacy original changed")

    @contextlib.contextmanager
    def execution(self, store: RunStore) -> Iterator[None]:
        """One executor, global then run lease; never infer abandoned work is free."""
        if self.read_only or store.read_only or self._active_store is not None or store._lease_active:
            raise ValueError("shared execution cannot nest or use read-only stores")
        with self.store.lease(), store.lease():
            with self.transaction(), store.transaction():
                self._sync()
                self._validate_retained_runs()
                if self._stopped or self._reservations or not self._required_complete():
                    raise BudgetStopped("shared admission stopped: pending/unknown or incomplete legacy imports")
                self._active_store = store
                try:
                    self.bind_run(store)
                except BaseException:
                    self._active_store = None
                    raise
            try:
                yield
            finally:
                try:
                    with self.transaction():
                        self._sync()
                        if self._reservations:
                            self.reject("open_reservations_at_execution_end")
                finally:
                    self._active_store = None

    def bind_run(self, store: RunStore) -> None:
        self.require_execution(store)
        with self.transaction(), store.transaction():
            self._sync()
            binding = self._run_binding(store)
            key = store.manifest_hash
            if key in self._runs:
                if self._runs[key] != binding:
                    raise ValueError("run registration changed")
                return
            if any(row.get("event") == "attempt_started" and row.get("hosted") is not False for row in store._read()):
                raise ValueError("existing hosted intent has no global reservation; import the exact legacy cut")
            if key in self._imports or any(x["directory"] == binding["directory"] for x in self._runs.values()) or any(x["binding"]["directory"] == binding["directory"] for x in self._imports.values()):
                raise ValueError("allocation run registration collision")
            self.store.append({"event": "allocation_run_bound", "binding": binding})
            self._sync()

    def import_run(self, binding: LegacyRunBinding) -> None:
        """Explicitly charge a verifiable original cut; no backfill/reconciliation."""
        if self.read_only or self._active_store is not None or not isinstance(binding, LegacyRunBinding):
            raise ValueError("legacy import requires a writable inactive allocation")
        # Excludes import racing an active executor and serializes other imports.
        with self.store.lease(), self.transaction():
            self._sync()
            key = binding.manifest_hash
            if key in self._imports or key in self._runs or any(x["directory"] == str(binding.directory) for x in self._runs.values()) or any(x["binding"]["directory"] == str(binding.directory) for x in self._imports.values()):
                raise ValueError("duplicate legacy import or run collision")
            for required in self.required_imports:
                if (required.manifest_hash == key or required.directory == binding.directory) and required != binding:
                    raise ValueError("legacy import differs from required frozen cut")
            summary = _legacy_summary(binding)
            if self._all_attempts.intersection(summary["attempt_ids"]):
                raise ValueError("legacy attempt identity collision")
            self.store.append({"event": "allocation_run_imported", "binding": binding.to_dict(), "accounting": summary})
            self._sync()

    def reserve(self, store: RunStore, attempt_id: str, cell_id: str, request_hash: str,
                model: str, endpoint: str, liability: str | None) -> None:
        self.require_execution(store)
        with self.transaction(), store.transaction(), localcontext(currency_context()):
            self._sync()
            self._check_run(store)
            try:
                self._verify_prior_pairs(store)
            except (ValueError, OSError, TypeError):
                self.reject("admission_pair_mismatch")
                raise
            if self._stopped or self._blocking_unknown() or not self._required_complete() or liability is None:
                raise BudgetStopped("shared admission stopped: unknown or unbounded liability")
            bound = usd(liability)
            if self._total_liability() + bound > self.limit:
                raise BudgetStopped("shared USD allocation exhausted")
            if attempt_id in self._all_attempts:
                raise ValueError("duplicate global attempt identity")
            for name, value in (("attempt_id", attempt_id), ("cell_id", cell_id), ("request_hash", request_hash), ("model", model), ("endpoint", endpoint)):
                _text(value, name)
            try:
                self.store.append({"event": "allocation_attempt_started", "run_manifest_hash": store.manifest_hash,
                    "attempt_id": attempt_id, "cell_id": cell_id, "request_hash": request_hash,
                    "model": model, "endpoint": endpoint, "liability_usd": str(bound)})
                self._sync()
            except BaseException:
                self.reject("allocation_durability_failure")
                raise

    def reject(self, reason: str) -> None:
        """Latch a safe stop; never release reservations even when writing fails."""
        if reason not in _STOP_REASONS:
            raise ValueError("invalid allocation stop reason")
        self._stopped = True
        self._reasons.add(reason)
        if self.read_only:
            raise ValueError("read-only allocation cannot stop/write")
        try:
            with self.transaction():
                self.store.append({"event": "allocation_stopped", "reason": reason})
                self._sync()
        except (OSError, ValueError, TypeError):
            # A torn journal/tip cannot be reopened for admission; the original
            # intent/reservation is retained. Never synthesize a repaired cut.
            pass

    def finish(self, store: RunStore, cell_id: str, receipt: CallReceipt) -> None:
        self.require_execution(store)
        with self.transaction(), store.transaction():
            self._sync()
            try:
                self._check_run(store)
                self._verify_prior_pairs(store)
                admission = self._admissions.get(receipt.attempt_id)
                if admission is None or receipt.attempt_id in self._finished or admission["run_manifest_hash"] != store.manifest_hash or any(admission[n] != value for n, value in (("cell_id", cell_id), ("request_hash", receipt.request_hash), ("model", receipt.requested_model), ("endpoint", receipt.endpoint))):
                    raise ValueError("global receipt identity mismatch")
                # Validate exact per-run receipt/admission through the original
                # accounting reducer, then reference its durable finished row.
                ledger = self._run_ledger(store)
                if receipt.attempt_id not in ledger.finished:
                    raise ValueError("global finish requires durable per-run finish first")
                row = next(r for r in reversed(store._read()) if r.get("event") == "attempt_finished" and r["receipt"]["attempt_id"] == receipt.attempt_id)
                if row["cell_id"] != cell_id or content_hash(row["receipt"]) != content_hash(receipt.to_dict()):
                    raise ValueError("per-run finished receipt mismatch")
                self.store.append({"event": "allocation_attempt_finished", "run_manifest_hash": store.manifest_hash,
                    "attempt_id": receipt.attempt_id, "cell_id": cell_id, "receipt_sha256": content_hash(receipt.to_dict()),
                    "run_event_hash": row["hash"], "cost_status": receipt.cost_status, "cost_usd": receipt.cost_usd})
                self._sync()
            except BaseException:
                self.reject("finish_split_write")
                raise

    def snapshot(self) -> dict[str, Any]:
        """Read-only reduction of an exact global cut, including pending/UNKNOWN."""
        with self.transaction(), localcontext(currency_context()):
            self._sync()
            self._validate_retained_runs()
            complete = self._required_complete()
            reasons = set(self._reasons)
            if any(set(value["accounting"]["attempt_ids"]) & set(self._reservations) for value in self._imports.values()):
                reasons.add("legacy_accounting_stopped")
            if not complete:
                reasons.add("required_legacy_imports_missing")
            if self._reservations and self._active_store is None:
                reasons.add("open_reservations_require_original_executor")
            rows = self.store._read()
            return {"allocation_id": self.allocation_id, "manifest_hash": self.store.manifest_hash,
                "limit_usd": str(self.limit), "reported_cost_usd": str(self._charged),
                "externally_verified_cost_usd": str(self._externally_verified),
                "effective_cost_usd": str(self._effective_cost()),
                "reserved_usd": str(sum(self._reservations.values(), Decimal(0))),
                "held_upper_bound_usd": str(self._held_total()),
                "total_liability_usd": str(self._total_liability()),
                "pending_attempts": sorted(self._reservations), "unknown_attempts": sorted(self._unknown),
                "historical_unknown_attempts": sorted(self._historical_unknown),
                "bounded_unknown_attempts": sorted(self._held_bounds),
                "historical_bounded_unknown_attempts": sorted(self._bounded_unknown),
                "externally_reconciled_attempts": sorted(self._reconciliations),
                "required_imports_complete": complete,
                "admission_stopped": self._stopped or not complete or bool(self._reservations and self._active_store is None),
                "stop_reasons": sorted(reasons), "bound_runs": len(self._runs), "imported_runs": len(self._imports),
                "journal_sequence": len(rows), "journal_tip": rows[-1]["hash"] if rows else self.store.manifest_hash}
