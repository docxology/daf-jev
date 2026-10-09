"""Hash-bound experiment custody and conservative per-attempt USD admission."""
from __future__ import annotations

import contextlib
import copy
import json
import math
import os
import threading
import uuid
from collections.abc import Iterator
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from daf_jev._json import strict_json_loads
from daf_jev.decision_backends import CallReceipt, canonical_json, content_hash, utc_now

if TYPE_CHECKING:
    from daf_jev.benchmark_allocation import AllocationLedger


class BudgetStopped(RuntimeError):
    """No further paid attempt can safely be admitted."""


class _FrozenJSON(dict):
    """JSON-serializable immutable manifest; recursive lists become tuples."""
    def _reject(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise ValueError("experiment manifest changed: immutable manifest")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _reject

    def __deepcopy__(self, memo: dict[int, Any]) -> _FrozenJSON:
        return self


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenJSON({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def currency_context() -> Context:
    """Return an isolated currency policy, independent of caller Decimal state.

    Charges remain bounded by :func:`usd`; derived ratios use 50 significant
    digits with half-even rounding. Each operation receives fresh flags and
    the standard invalid-operation, division-by-zero and overflow traps.
    """
    return Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   capitals=1, clamp=0, flags=[],
                   traps=[InvalidOperation, DivisionByZero, Overflow])


def usd(value: Any) -> Decimal:
    """Validate an individual admission bound or reported request charge."""
    return _amount(value, maximum_exponent=9)


def usd_total(value: Any) -> Decimal:
    """Validate a derived total without reapplying the per-request ceiling.

    Twenty integer and eighteen fractional digits fit exactly in the isolated
    50-digit context. This is a reduction domain, never an admission allowance.
    """
    return _amount(value, maximum_exponent=19)


def _amount(value: Any, *, maximum_exponent: int) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("USD amount must be a finite nonnegative decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid USD amount") from exc
    if not result.is_finite() or result < 0 or result.adjusted() > maximum_exponent or int(result.as_tuple().exponent) < -18:
        raise ValueError(f"USD amount must be nonnegative, below 1E{maximum_exponent + 1}, with at most 18 decimal places")
    return result


def _regular(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("experiment paths must not traverse symlinks")
    if path.exists() and not path.is_file():
        raise ValueError("expected a regular experiment file")


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class RunStore:
    """Manifest is immutable; events have a hash chain and independently saved tip.

    A crash between journal and tip publication fails closed on resume, rather
    than silently trusting a truncated or incompletely committed interval.
    """
    def __init__(self, directory: Path, *, read_only: bool = False) -> None:
        self.directory = Path(directory).absolute()
        self.read_only = read_only
        self._mutex = threading.RLock()
        self._transaction_depth = 0
        self._lease_active = False
        self._cache: list[dict[str, Any]] = []
        self._fingerprint: Any = None
        for name in ("manifest.json", "events.jsonl", "head.json", ".run.lock"):
            _regular(self.directory / name)
        self.manifest = _freeze(strict_json_loads(self._safe_read("manifest.json")))
        self.manifest_hash = content_hash(self.manifest)
        self._bound_manifest, self._bound_manifest_hash = self.manifest, self.manifest_hash
        self._manifest_stat = (self.directory / "manifest.json").stat()
        for name, identity in (() if read_only else self.manifest["lock_identities"].items()):
            stat = (self.directory / name).stat()
            if (stat.st_dev, stat.st_ino) != tuple(identity):
                raise ValueError("experiment lock identity changed")
        self._read()

    def _safe_read(self, name: str) -> str:
        path = self.directory / name
        _regular(path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(descriptor)
            with os.fdopen(os.dup(descriptor), "r") as handle:
                data = handle.read()
            after = os.fstat(descriptor)
            current = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError("experiment file changed during consumption")
            return data
        finally:
            os.close(descriptor)

    def _check_manifest(self) -> None:
        if self.manifest is not self._bound_manifest or self.manifest_hash != self._bound_manifest_hash:
            raise ValueError("experiment manifest changed during consumption")
        path = self.directory / "manifest.json"
        _regular(path)
        current, before = path.stat(), self._manifest_stat
        def identity(stat: os.stat_result) -> tuple[int, ...]:
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if identity(current) != identity(before):
            raise ValueError("experiment manifest changed during consumption")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize journal read/admission/write across threads and processes."""
        with self._mutex:
            if self.read_only:
                yield
                return
            import fcntl
            if self._transaction_depth:
                yield
                return
            path = self.directory / ".journal.lock"
            _regular(path)
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                self._check_lock(path, descriptor)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                self._check_lock(path, descriptor)
                self._transaction_depth += 1
                yield
            finally:
                self._transaction_depth = 0
                os.close(descriptor)

    def _check_lock(self, path: Path, descriptor: int) -> None:
        _regular(path)
        stat, current = os.fstat(descriptor), path.stat()
        expected = self.manifest["lock_identities"][path.name]
        if (stat.st_dev, stat.st_ino) != tuple(expected) or (current.st_dev, current.st_ino) != tuple(expected):
            raise ValueError("experiment lock identity changed")

    @classmethod
    def create(cls, root: Path, manifest: dict[str, Any]) -> RunStore:
        directory = Path(root).absolute() / str(uuid.uuid4())
        return cls.create_at(directory, manifest)

    @classmethod
    def create_at(cls, directory: Path, manifest: dict[str, Any]) -> RunStore:
        """Explicitly create an exclusively named store; never open/reset one."""
        directory = Path(directory).absolute()
        _regular(directory / "manifest.json")
        directory.mkdir(parents=True, exist_ok=False)
        manifest = copy.deepcopy(manifest)
        manifest["lock_identities"] = {}
        for name in (".run.lock", ".journal.lock"):
            descriptor = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                stat = os.fstat(descriptor)
                manifest["lock_identities"][name] = [stat.st_dev, stat.st_ino]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        with (directory / "manifest.json").open("x") as handle:
            handle.write(canonical_json(manifest) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        for name, data in (("events.jsonl", ""), ("head.json", canonical_json({"sequence": 0, "hash": content_hash(manifest)}))):
            with (directory / name).open("x") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        sync_directory(directory)
        sync_directory(directory.parent)
        return cls(directory)

    def _read(self) -> list[dict[str, Any]]:
        self._check_manifest()
        paths = [self.directory / name for name in ("events.jsonl", "head.json")]
        for path in paths:
            _regular(path)
        fingerprint = tuple((p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths)
        if fingerprint == self._fingerprint:
            return self._cache
        previous = self.manifest_hash
        rows: list[dict[str, Any]] = []
        for line in self._safe_read("events.jsonl").splitlines():
            row = strict_json_loads(line)
            digest = row.pop("hash")
            if row.get("sequence") != len(rows) + 1 or row.get("previous") != previous or content_hash(row) != digest:
                raise ValueError("experiment journal hash/sequence mismatch")
            row["hash"] = digest
            rows.append(row)
            previous = digest
        head = strict_json_loads(self._safe_read("head.json"))
        if head != {"sequence": len(rows), "hash": previous}:
            raise ValueError("experiment journal tip mismatch; retain evidence for review")
        if len(rows) < len(self._cache) or rows[:len(self._cache)] != self._cache:
            raise ValueError("previously consumed experiment history changed")
        self._cache, self._fingerprint = rows, fingerprint
        return rows

    @contextlib.contextmanager
    def lease(self) -> Iterator[None]:
        if self.read_only:
            raise ValueError("read-only audit cannot execute")
        import fcntl
        path = self.directory / ".run.lock"
        _regular(path)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        acquired = False
        try:
            self._check_lock(path, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._check_lock(path, descriptor)
            self._lease_active = acquired = True
            yield
        finally:
            if acquired:
                self._lease_active = False
            os.close(descriptor)

    def events(self) -> list[dict[str, Any]]:
        with self.transaction():
            return copy.deepcopy(self._read())

    def append(self, event: dict[str, Any]) -> None:
        if self.read_only:
            raise ValueError("read-only audit cannot append")
        with self.transaction():
            if set(event) & {"sequence", "previous", "hash", "timestamp"}:
                raise ValueError("event cannot override journal custody fields")
            rows = self._read()
            # Cache exactly the JSON representation retained on disk. Frozen
            # manifest arrays are tuples in memory; a subsequent reader sees
            # arrays as lists and must compare the same canonical history.
            owned_event = json.loads(canonical_json(event))
            row = {"sequence": len(rows) + 1, "previous": rows[-1]["hash"] if rows else self.manifest_hash,
                   "timestamp": utc_now(), **owned_event}
            row["hash"] = content_hash(row)
            descriptor = os.open(self.directory / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            try:
                data = (canonical_json(row) + "\n").encode()
                offset = 0
                while offset < len(data):
                    offset += os.write(descriptor, data[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            temporary = self.directory / f".head-{uuid.uuid4()}.tmp"
            with temporary.open("x") as handle:
                handle.write(canonical_json({"sequence": row["sequence"], "hash": row["hash"]}))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / "head.json")
            sync_directory(self.directory)
            self._cache.append(row)
            paths = [self.directory / name for name in ("events.jsonl", "head.json")]
            self._fingerprint = tuple((p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for p in paths)


class SpendLedger:
    """Reserve each transport attempt atomically and journal intent before I/O.

    Unknown billing remains reserved and stops admission. Reported charges are
    authoritative even if they exceed the configured bound; that breach halts
    admission and is never hidden by clamping.
    """
    def __init__(self, store: RunStore, *, limit: str = "25",
                 allocation: AllocationLedger | None = None) -> None:
        self.store = store
        self.limit = usd(limit)
        self.allocation = allocation
        if allocation is not None:
            allocation.require_execution(store)
            if self.limit > allocation.limit:
                raise ValueError("run limit exceeds shared allocation")
            if "budget_usd" in store.manifest and usd(store.manifest["budget_usd"]) != self.limit:
                raise ValueError("run limit differs from frozen budget")
        self._lock = threading.RLock()
        self.reservations: dict[str, Decimal] = {}
        self.admissions: dict[str, dict[str, Any]] = {}
        self.finished: set[str] = set()
        self.charged = Decimal(0)
        self.stopped = False
        self._sequence = 0
        with store.transaction():
            self._sync()
        # A shared execution entry already refuses all earlier global pending
        # work. Other observers inside this current lease may legitimately see
        # concurrently admitted attempts; they do not represent crash recovery.
        self._resume_blocked = bool(self.reservations) and allocation is None

    def _binding(self, cell: str, receipt: CallReceipt) -> dict[str, Any]:
        canonical_json(receipt.to_dict())
        if isinstance(receipt.elapsed_s, bool) or not isinstance(receipt.elapsed_s, (int, float)) or not math.isfinite(receipt.elapsed_s) or receipt.elapsed_s < 0:
            raise ValueError("receipt timing must be finite and nonnegative")
        for count in (receipt.input_tokens, receipt.output_tokens):
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                raise ValueError("receipt token counts must be nonnegative integers")
        if receipt.status_code is not None and (isinstance(receipt.status_code, bool) or not isinstance(receipt.status_code, int) or not 100 <= receipt.status_code <= 599):
            raise ValueError("invalid receipt HTTP status")
        admission = self.admissions.get(receipt.attempt_id)
        if admission is None or receipt.attempt_id in self.finished:
            raise ValueError("receipt has no matching unfinished admission")
        if any((admission["cell_id"] != cell,
                admission["request_hash"] != receipt.request_hash,
                admission["model"] != receipt.requested_model,
                admission["endpoint"] != receipt.endpoint)):
            raise ValueError("receipt identity does not match admitted request")
        if receipt.cost_status not in ("reported", "unknown", "local"):
            raise ValueError("invalid accounting provenance")
        if admission["hosted"] and receipt.cost_status == "local":
            raise ValueError("hosted attempt cannot be reconciled as local")
        if not admission["hosted"] and receipt.cost_status != "local":
            raise ValueError("local attempt cannot be reconciled as hosted")
        if receipt.cost_status == "reported":
            usd(receipt.cost_usd)
        elif receipt.cost_usd is not None:
            raise ValueError("unreported cost must remain unknown")
        return admission

    def _sync(self) -> None:
        rows = self.store._read()
        for row in rows[self._sequence:]:
            if row.get("event") == "attempt_started":
                attempt = row["attempt_id"]
                if attempt in self.admissions:
                    raise ValueError("duplicate attempt admission")
                self.admissions[attempt] = row
                self.reservations[attempt] = usd(row["liability_usd"])
            elif row.get("event") == "accounting_rejected":
                self.stopped = True
            elif row.get("event") == "attempt_finished":
                receipt = CallReceipt(**row["receipt"])
                self._binding(row["cell_id"], receipt)
                bound = self.reservations[receipt.attempt_id]
                self.finished.add(receipt.attempt_id)
                if receipt.cost_status == "reported":
                    cost = usd(receipt.cost_usd)
                    with localcontext(currency_context()):
                        self.charged += cost
                    del self.reservations[receipt.attempt_id]
                    self.stopped |= cost > bound or self.charged > self.limit
                elif receipt.cost_status == "local":
                    del self.reservations[receipt.attempt_id]
                else:
                    self.stopped = True
        self._sequence = len(rows)

    def observer(self, *, cell_id: str, hosted: bool, liability_usd: str | None) -> LedgerObserver:
        return LedgerObserver(self, cell_id, hosted, liability_usd)

    def reserve(self, cell_id: str, request_hash: str, model: str, endpoint: str,
                hosted: bool, liability: str | None) -> str:
        if not isinstance(hosted, bool):
            raise ValueError("hosted admission flag must be boolean")
        shared = self.allocation
        with self._lock, (shared.transaction() if shared is not None else contextlib.nullcontext()), self.store.transaction(), localcontext(currency_context()):
            self._sync()
            if hosted and (self.stopped or self._resume_blocked or liability is None):
                raise BudgetStopped("paid admission stopped: unresolved or unbounded liability")
            bound = usd(liability) if hosted else Decimal(0)
            if hosted and self.charged + sum(self.reservations.values(), Decimal(0)) + bound > self.limit:
                raise BudgetStopped("USD budget exhausted")
            attempt = str(uuid.uuid4())
            if shared is not None and hosted:
                shared.reserve(self.store, attempt, cell_id, request_hash, model, endpoint, str(bound))
            try:
                self.store.append({"event": "attempt_started", "cell_id": cell_id, "attempt_id": attempt,
                    "request_hash": request_hash, "model": model, "endpoint": endpoint,
                    "hosted": hosted, "liability_usd": str(bound)})
            except BaseException:
                self.stopped = True
                if shared is not None and hosted:
                    shared.reject("reservation_split_write")
                raise
            self._sync()
            return attempt

    def finish(self, cell_id: str, receipt: CallReceipt) -> None:
        shared = self.allocation
        with self._lock, (shared.transaction() if shared is not None else contextlib.nullcontext()), self.store.transaction():
            self._sync()
            try:
                self._binding(cell_id, receipt)
            except (ValueError, OverflowError, TypeError) as exc:
                self.stopped = True
                if shared is not None:
                    shared.reject("invalid_receipt")
                self.store.append({"event": "accounting_rejected", "cell_id": cell_id, "attempt_id": receipt.attempt_id})
                if isinstance(exc, ValueError):
                    raise
                raise ValueError("invalid accounting receipt") from exc
            try:
                self.store.append({"event": "attempt_finished", "cell_id": cell_id, "receipt": receipt.to_dict()})
            except BaseException:
                self.stopped = True
                if shared is not None:
                    shared.reject("finish_split_write")
                raise
            self._sync()
            if shared is not None and self.admissions[receipt.attempt_id]["hosted"]:
                shared.finish(self.store, cell_id, receipt)

    def snapshot(self) -> dict[str, Any]:
        with self._lock, self.store.transaction(), localcontext(currency_context()):
            self._sync()
            return {"limit_usd": str(self.limit), "reported_cost_usd": str(self.charged),
                "reserved_usd": str(sum(self.reservations.values(), Decimal(0))),
                "unresolved_attempts": sorted(self.reservations),
                "admission_stopped": self.stopped or self._resume_blocked}


class LedgerObserver:
    def __init__(self, ledger: SpendLedger, cell: str, hosted: bool, liability: str | None) -> None:
        self.ledger, self.cell, self.hosted, self.liability = ledger, cell, hosted, liability

    def before(self, request_hash: str, model: str, endpoint: str) -> str:
        return self.ledger.reserve(self.cell, request_hash, model, endpoint, self.hosted, self.liability)

    def after(self, receipt: CallReceipt) -> None:
        self.ledger.finish(self.cell, receipt)
