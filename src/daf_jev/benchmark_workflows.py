"""Executed cascades with explicit child admission and caller-owned backends."""
from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from daf_jev._cancellation import mark_cancellation
from daf_jev.benchmark_policies import GateCalibration
from daf_jev.benchmark_store import BudgetStopped
from daf_jev.decision_backends import (
    AsyncDecisionBackend,
    AttemptObserver,
    BackendCapabilities,
    CallReceipt,
    DecisionRequest,
    DecisionResult,
)


class _RecordingObserver:
    def __init__(self, owner: CascadeDecisionBackend, child: str) -> None:
        self.owner, self.child = owner, child
        self.delegate = owner.observers(child)

    def before(self, request_hash: str, model: str, endpoint: str) -> str:
        attempt = self.delegate.before(request_hash, model, endpoint) if self.delegate else str(uuid.uuid4())
        self.owner._attempt_ids[self.child].append(attempt)
        return attempt

    def after(self, receipt: CallReceipt) -> None:
        self.owner._receipts[receipt.attempt_id] = receipt
        if self.delegate:
            self.delegate.after(receipt)


def _validate(request: DecisionRequest, result: DecisionResult) -> None:
    from daf_jev._types import validate_probability_row
    if set(result.predictions) != set(request.questions):
        raise ValueError("workflow predictions must cover every requested question")
    for key, prediction in result.predictions.items():
        wire = request.questions[key].to_wire()
        kind = wire["type"]
        if prediction.type != kind:
            raise ValueError("workflow prediction type mismatch")
        value = prediction.value
        if kind == "choice":
            labels = list(wire["criteria"])
            if value not in labels:
                raise ValueError("workflow choice outside vocabulary")
        else:
            upper = 1 if kind == "noul" else len(wire["criteria"]) - 1
            labels = ["false", "true"] if kind == "noul" else [str(i) for i in range(upper + 1)]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= upper:
                raise ValueError("invalid workflow numeric prediction")
        if prediction.probabilities is not None:
            if set(prediction.probabilities) != set(labels):
                raise ValueError("workflow distribution vocabulary mismatch")
            validate_probability_row(prediction.probabilities, rounding_digits=prediction.probability_rounding_digits)
        confidence = prediction.confidence
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("invalid workflow confidence")


class CascadeDecisionBackend:
    """Local→hosted execution; gate is frozen validation evidence, never test fit.

    Each child gets its own billing observer. Supplied clients remain owned by
    their caller. End-to-end timing belongs to the enclosing runner cell.
    """
    def __init__(self, weak: AsyncDecisionBackend, strong: AsyncDecisionBackend, *,
                 gate: GateCalibration, observers: Callable[[str], AttemptObserver | None]) -> None:
        self.weak, self.strong, self.gate, self.observers = weak, strong, gate, observers
        self.model = f"cascade:{weak.model}->{strong.model}"
        self.capabilities = BackendCapabilities(probability_source="selected_child",
            confidence_semantics="selected_child", evidence="frozen_validation_gate")
        self._weak_attempted = False
        self._weak_result: DecisionResult | None = None
        self._reason = "confidence_gate"
        self._strong_attempts = 0
        self._pending_request: DecisionRequest | None = None
        self._attempt_ids: dict[str, list[str]] = {"weak": [], "strong": []}
        self._receipts: dict[str, CallReceipt] = {}
        self._weak_completed = False
        self._active_child = "weak"

    async def predict(self, request: DecisionRequest) -> DecisionResult:
        try:
            return await self._predict(request)
        except (BudgetStopped, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                mark_cancellation(exc)
            if self._attempt_ids["weak"] or self._weak_completed or self._attempt_ids["strong"]:
                # Keep evidence on the original failure. A Python 3.10 Task
                # can wrap cancellation in a fresh exception; readers follow
                # standard chaining instead of requiring copied attributes.
                record = {
                    "policy": "cascade", "executed": True, "status": "failed",
                    "failed_phase": self._active_child, "error": type(exc).__name__,
                    "strong_invoked": self._strong_attempts > 0,
                    "weak_status": "completed" if self._weak_completed else
                        "failed" if self._reason.startswith("weak_failure:") else "unresolved",
                    "strong_status": "unattempted" if not self._attempt_ids["strong"] else "unresolved",
                    "attempt_ids": {child: list(ids) for child, ids in self._attempt_ids.items()},
                    "observed_receipts": [r.to_dict() for r in self._receipts.values()],
                    "weak_predictions": {key: asdict(p) for key, p in self._weak_result.predictions.items()}
                        if self._weak_completed and self._weak_result else {},
                    "reason": self._reason, "gate": self.gate.to_dict(),
                }
                exc.__dict__["dafjev_workflow"] = record
            raise

    async def _predict(self, request: DecisionRequest) -> DecisionResult:
        if self._pending_request is not request:
            self._weak_attempted, self._weak_result = False, None
            self._reason, self._strong_attempts = "confidence_gate", 0
            self._pending_request = request
            self._attempt_ids, self._receipts = {"weak": [], "strong": []}, {}
            self._weak_completed = False
        if not self._weak_attempted:
            self._weak_attempted = True
            self._active_child = "weak"
            try:
                self._weak_result = await self.weak.predict(replace(request, observer=_RecordingObserver(self, "weak")))
                self._receipts.update({r.attempt_id: r for r in self._weak_result.receipts})
                _validate(request, self._weak_result)
                self._weak_completed = True
            except BudgetStopped:
                raise
            except Exception as exc:
                self._weak_result = None
                self._reason = "weak_failure:" + type(exc).__name__
        weak_result = self._weak_result
        threshold = self.gate.threshold if self.gate.status == "admitted" else None
        complete = weak_result is not None and set(weak_result.predictions) == set(request.questions) and all(
            p.type == request.questions[key].to_wire()["type"] for key, p in weak_result.predictions.items())
        accepted = complete and weak_result is not None and threshold is not None and all(
            not isinstance(p.confidence, bool) and isinstance(p.confidence, (int, float)) and math.isfinite(p.confidence) and 0 <= p.confidence <= 1 and p.confidence >= threshold
            for p in weak_result.predictions.values())
        if accepted:
            assert weak_result is not None
            self._weak_attempted = False
            self._pending_request = None
            return DecisionResult(weak_result.predictions, weak_result.receipts,
                {"policy": "cascade", "executed": True, "strong_invoked": False,
                 "selected_model": self.weak.model, "gate": self.gate.to_dict()})
        self._strong_attempts += 1
        self._active_child = "strong"
        strong = await self.strong.predict(replace(request, observer=_RecordingObserver(self, "strong")))
        self._receipts.update({r.attempt_id: r for r in strong.receipts})
        _validate(request, strong)
        result = DecisionResult(strong.predictions, tuple(self._receipts.values()),
            {"policy": "cascade", "executed": True, "strong_invoked": True,
             "selected_model": self.strong.model, "reason": self._reason,
             "strong_transport_attempts": self._strong_attempts, "gate": self.gate.to_dict()})
        self._weak_attempted, self._strong_attempts = False, 0
        self._pending_request = None
        return result

    async def close(self) -> None:
        """Caller retains ownership of both supplied clients."""


def gate_from_dict(value: dict[str, Any]) -> GateCalibration:
    from dataclasses import fields
    return GateCalibration(**{field.name: value[field.name] for field in fields(GateCalibration) if field.name in value})
