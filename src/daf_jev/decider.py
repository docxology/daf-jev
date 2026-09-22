"""Decision-point decider: the observe -> compose -> ask -> gate -> fail-open -> act
loop distilled as one reusable class. Pure orchestration over injected I/O.

The :class:`Decider` wraps the recurring shape of a long-running decision
loop: render the state, batch the questions into one ask, gate the
answers, map them to a typed action, and fall back to a deterministic
floor action whenever anything is missing or wrong. Every failure mode is
classified into a closed reason taxonomy and surfaced as a JSON-safe
:class:`DecisionEvent`; :meth:`Decider.decide` never raises (the fallback
hook itself is the floor and must not raise).

Fallback reason taxonomy (closed set):

- ``not_asked``     — the ``should_ask`` hook returned False
- ``no_key``        — the default-client path found no API key (latched for
  the Decider's lifetime)
- ``client_error``  — the client factory raised or returned None, or the
  default client construction raised (latched for the Decider's lifetime)
- ``latched``       — ``max_consecutive_failures`` consecutive failures
  reached; later decides short-circuit with this reason, except a cache
  hit (source ``cache``) or a ``should_ask`` veto (``not_asked``), which
  still take precedence
- ``budget``        — :class:`Budget.exceeded` reported a limit
- ``breaker``       — :class:`~daf_jev.resilience.CircuitOpenError` from an
  opt-in :class:`~daf_jev.resilience.CircuitBreaker`
- ``compose_error`` — the state render or questions hook raised
- ``ask_error``     — the client ask raised (counts toward the
  consecutive-failure latch)
- ``gate``          — the gate hook returned a rejection reason
- ``mapping_error`` — the answers-to-action hook raised (counts toward the
  consecutive-failure latch)
- ``error``         — any unexpected exception inside ``decide()`` that no
  earlier guard catches (e.g. a raising ``cache_key``, a raising cache
  mapping operation, or a raising ``should_ask``/gate hook)
 """

from __future__ import annotations

import contextlib
import dataclasses
import math
import time
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Generic, TypeVar

from daf_jev._errors import TypeSafeError
from daf_jev._retry import RetryPolicy
from daf_jev._types import (
    Answer,
    JSONContent,
    Question,
    SystemOneResponse,
    Usage,
)
from daf_jev.client import JevClient
from daf_jev.config import resolve_api_key
from daf_jev.ledger import UsageLedger, UsageSnapshot
from daf_jev.resilience import CircuitBreaker, CircuitOpenError

__all__ = ["Budget", "ConfidenceGate", "Decider", "DecisionEvent"]

S = TypeVar("S")
T = TypeVar("T")


def _error_text(exc: BaseException) -> str:
    """Rendered exception text for event receipts."""
    return str(exc) or type(exc).__name__


@dataclasses.dataclass(frozen=True)
class DecisionEvent:
    """One ``decide()`` outcome, emitted after every call.

    ``source`` is ``"model"`` (the client answered), ``"cache"`` (a cached
    action was reused) or ``"fallback"`` (the floor action was used; see
    the module docstring for the reason taxonomy). ``reason`` and ``error``
    are None exactly when ``source`` is ``"model"`` or ``"cache"``.
    ``latency_s`` is the wall time of the whole ``decide()`` call, measured
    with the injected clock.
    """

    source: str
    reason: str | None
    error: str | None
    latency_s: float
    usage: Usage | None
    request_id: str | None

    def to_dict(self) -> dict:
        """Return a JSON-safe dict; ``usage`` becomes a token pair or None."""
        return {
            "source": self.source,
            "reason": self.reason,
            "error": self.error,
            "latency_s": self.latency_s,
            "usage": (
                {
                    "input_tokens": self.usage.input_tokens,
                    "output_tokens": self.usage.output_tokens,
                }
                if self.usage is not None
                else None
            ),
            "request_id": self.request_id,
        }


@dataclasses.dataclass(frozen=True)
class ConfidenceGate:
    """Gate one named answer on its declared confidence.

    Returns None to accept the model's answers, or a human-readable
    rejection reason that the :class:`Decider` turns into a ``"gate"``
    fallback. Noul answers carry no confidence field, so they are not
    gated (None) — a gate must tolerate confidence-less answers rather
    than reject them.
    """

    answer_id: str
    threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {self.threshold}")

    def __call__(self, answers: Mapping[str, Answer]) -> str | None:
        answer = answers.get(self.answer_id)
        if answer is None:
            return f"missing answer '{self.answer_id}'"
        confidence = getattr(answer, "confidence", None)
        if confidence is None:
            return None
        if not math.isfinite(confidence):
            return (
                f"confidence {confidence!r} is not finite, "
                f"below threshold {self.threshold:.3f}"
            )
        if confidence < self.threshold:
            return f"confidence {confidence:.3f} < threshold {self.threshold:.3f}"
        return None


@dataclasses.dataclass
class Budget:
    """Mutable call/token budget over a :class:`Decider`'s ask attempts.

    At least one threshold is required, and every provided threshold must
    be >= 0 (``ValueError`` otherwise); ``max_calls=0`` is valid — a
    deliberate "no calls" budget. ``exceeded()`` returns a human-readable
    reason when any limit is met or passed, else None; the Decider checks
    it before every ask and charges ``attempts`` once per attempt (success
    or failure).
    """

    max_calls: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    attempts: int = 0

    def __post_init__(self) -> None:
        thresholds = {
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
        }
        if all(value is None for value in thresholds.values()):
            raise ValueError("Budget requires at least one threshold")
        for name, value in thresholds.items():
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")

    def charge(self) -> None:
        """Count one ask attempt (success or failure)."""
        self.attempts += 1

    def exceeded(self, usage: UsageSnapshot) -> str | None:
        """Return the first limit met/passed as a reason string, else None."""
        if self.max_calls is not None and self.attempts >= self.max_calls:
            return f"max_calls reached ({self.attempts}/{self.max_calls})"
        if (
            self.max_input_tokens is not None
            and usage.input_tokens >= self.max_input_tokens
        ):
            return (
                f"max_input_tokens reached "
                f"({usage.input_tokens}/{self.max_input_tokens})"
            )
        if (
            self.max_output_tokens is not None
            and usage.output_tokens >= self.max_output_tokens
        ):
            return (
                f"max_output_tokens reached "
                f"({usage.output_tokens}/{self.max_output_tokens})"
            )
        if (
            self.max_total_tokens is not None
            and usage.total_tokens >= self.max_total_tokens
        ):
            return (
                f"max_total_tokens reached "
                f"({usage.total_tokens}/{self.max_total_tokens})"
            )
        return None

    def to_dict(self) -> dict:
        """Return a JSON-safe dict of the thresholds and the attempt count."""
        return {
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
            "attempts": self.attempts,
        }


class _NoApiKey(TypeSafeError):
    """Raised by the default-client path when no API key can be resolved."""


class _ResolutionFailed(Exception):
    """Internal: client resolution failed with a taxonomy reason."""

    def __init__(self, reason: str, error: str | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error = error


class Decider(Generic[S, T]):
    """Observe -> compose -> ask -> gate -> fail-open -> act, once per call.

    All I/O is injected: the client (or a factory, or the environment for
    the default client), the state/questions/map hooks, the floor action,
    and optionally a cache, budget, ledger, breaker, and event observer.
    :meth:`decide` never raises — every failure falls back to the
    ``fallback`` hook with a classified reason (see the module docstring).
    The fallback hook itself is the floor and must not raise.

    The default client is ``JevClient(env=env, retry=RetryPolicy(
    max_attempts=1))`` — a single attempt per ask, so worst-case blocking
    is the per-call timeout, never timeout x retries. Consumers wanting
    retries pass ``client_factory`` with their own client.
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        render_state: Callable[[S], JSONContent],
        questions: Callable[[S], Mapping[str, Question]],
        map_answers: Callable[[S, SystemOneResponse], T],
        fallback: Callable[[S], T],
        gate: Callable[[Mapping[str, Answer]], str | None] | None = None,
        should_ask: Callable[[S], bool] | None = None,
        budget: Budget | None = None,
        cache: MutableMapping[Any, T] | None = None,
        cache_key: Callable[[S], Any] | None = None,
        ledger: UsageLedger | None = None,
        breaker: CircuitBreaker | None = None,
        timeout: float | None = None,
        max_consecutive_failures: int = 3,
        client_factory: Callable[[], Any] | None = None,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_event: Callable[[DecisionEvent], None] | None = None,
    ) -> None:
        if client is not None and client_factory is not None:
            raise ValueError("client and client_factory are mutually exclusive")
        if (cache is None) != (cache_key is None):
            raise ValueError("cache and cache_key must be given together")
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        self._client = client
        self._client_factory = client_factory
        self._render_state = render_state
        self._questions = questions
        self._map_answers = map_answers
        self._fallback_fn = fallback
        self._gate = gate
        self._should_ask = should_ask
        self._budget = budget
        # ``cache`` and ``cache_key`` are given together (validated above);
        # one pair attribute keeps that invariant visible to the type checker.
        pair = None if cache is None or cache_key is None else (cache, cache_key)
        self._cache_pair = pair
        self._ledger = ledger if ledger is not None else UsageLedger()
        self._breaker = breaker
        self._timeout = timeout
        self._max_consecutive_failures = max_consecutive_failures
        self._env = env
        self._clock = clock
        self._on_event = on_event
        self._resolved: Any | None = None
        self._consecutive_failures = 0
        self._latched = False
        self._latch_reason: str | None = None
        self._latch_error: str | None = None
        self.last_event: DecisionEvent | None = None
        self._calibration: list[tuple[float, bool]] = []

    # -- public surface ----------------------------------------------------

    def decide(self, state: S) -> T:
        """Decide once for ``state``; never raises (see class docstring)."""
        t0 = self._clock()
        try:
            return self._decide(state, t0)
        except Exception as exc:  # belt and suspenders — never raises
            return self._fallback(state, "error", _error_text(exc), t0)

    @property
    def dead(self) -> bool:
        """True once the decider has latched (no_key/client_error/latched)."""
        return self._latched

    def usage_snapshot(self) -> UsageSnapshot:
        """Current request/token totals from the (internal or injected) ledger."""
        return self._ledger.snapshot()

    def calibration_pairs(self) -> list[tuple[float, bool]]:
        """(declared confidence, gate-accepted) pairs, when the gate is a
        :class:`ConfidenceGate`.

        This is a self-consistency proxy, NOT correctness. Feed the pairs
        into :mod:`daf_jev.calibration` helpers to track drift. Empty list
        when no ConfidenceGate is configured.
        """
        return list(self._calibration)

    # -- pipeline ------------------------------------------------------------

    def _decide(self, state: S, t0: float) -> T:
        # 1. Cache hit: return the cached action without asking. The key is
        # computed once per decide and reused by the step-10 store.
        cache_pair = self._cache_pair
        key: Any = None
        if cache_pair is not None:
            cache, cache_key = cache_pair
            key = cache_key(state)
            if key in cache:
                self._emit("cache", None, None, t0, None, None)
                return cache[key]
        # 2. The should_ask hook may veto the ask entirely.
        if self._should_ask is not None and not self._should_ask(state):
            return self._fallback(state, "not_asked", None, t0)
        # 3. Client resolution (latching on failure for the Decider's lifetime).
        if self._latched:
            return self._fallback(state, self._latch_reason, self._latch_error, t0)
        try:
            client = self._resolve_client()
        except _ResolutionFailed as failure:
            self._latch(failure.reason, failure.error)
            return self._fallback(state, failure.reason, failure.error, t0)
        # 4. Budget gate.
        if self._budget is not None:
            budget_reason = self._budget.exceeded(self._ledger.snapshot())
            if budget_reason is not None:
                return self._fallback(state, "budget", budget_reason, t0)
        # 5. Compose the ask payload.
        try:
            state_text = self._render_state(state)
            questions = dict(self._questions(state))
        except Exception as exc:
            return self._fallback(state, "compose_error", _error_text(exc), t0)

        # 6. Ask once (behind the breaker when set), charging the budget.
        def _ask() -> SystemOneResponse:
            return client.ask(state_text, questions, timeout=self._timeout)

        if self._budget is not None:
            self._budget.charge()
        try:
            response = (
                self._breaker.call(_ask) if self._breaker is not None else _ask()
            )
        except CircuitOpenError as exc:
            return self._fallback(state, "breaker", _error_text(exc), t0)
        except Exception as exc:
            self._note_failure(_error_text(exc))
            return self._fallback(state, "ask_error", _error_text(exc), t0)
        # 7. Success: record usage and reset the consecutive-failure counter.
        self._ledger.record(response)
        self._consecutive_failures = 0
        # 8. Gate the answers.
        if self._gate is not None:
            gate_reason = self._gate(response.answers)
            if isinstance(self._gate, ConfidenceGate):
                answer = response.answers.get(self._gate.answer_id)
                confidence = getattr(answer, "confidence", None)
                if confidence is not None:
                    self._calibration.append((confidence, gate_reason is None))
            if gate_reason is not None:
                return self._fallback(state, "gate", gate_reason, t0)
        # 9. Map the answers to the typed action.
        try:
            action = self._map_answers(state, response)
        except Exception as exc:
            self._note_failure(_error_text(exc))
            return self._fallback(state, "mapping_error", _error_text(exc), t0)
        # 10. Cache the action and emit the model event. The key is the one
        # computed at step 1 (cache_key runs once per decide).
        if cache_pair is not None:
            cache, _ = cache_pair
            cache[key] = action
        self._emit("model", None, None, t0, response.usage, response.request_id)
        return action

    # -- internals -----------------------------------------------------------

    def _resolve_client(self) -> Any:
        """Return the ask client, resolving lazily on first use."""
        if self._client is not None:
            return self._client
        if self._resolved is not None:
            return self._resolved
        if self._client_factory is not None:
            factory = self._client_factory
            try:
                client = factory()
            except Exception as exc:
                raise _ResolutionFailed(
                    "client_error", _error_text(exc)
                ) from exc
            if client is None:
                # Resolution failed, not ask: latch on the first call so the
                # factory is never re-run and no decide ever sees a None
                # client.
                name = getattr(factory, "__name__", "<anonymous>")
                raise _ResolutionFailed(
                    "client_error", f"client_factory {name} returned None"
                )
            self._resolved = client
            return client
        try:
            client = self._default_client()
        except Exception as exc:
            reason = "no_key" if isinstance(exc, _NoApiKey) else "client_error"
            raise _ResolutionFailed(reason, _error_text(exc)) from exc
        self._resolved = client
        return client

    def _default_client(self) -> JevClient:
        """Build the default client: single attempt per ask, env-resolved."""
        if resolve_api_key(self._env) is None:
            raise _NoApiKey(
                "No API key found: set JEV_API_KEY (or TYPESAFE_API_KEY)."
            )
        return JevClient(env=self._env, retry=RetryPolicy(max_attempts=1))

    def _note_failure(self, error: str | None) -> None:
        """Count one pipeline failure; latch at the consecutive-failure limit."""
        self._consecutive_failures += 1
        if not self._latched and (
            self._consecutive_failures >= self._max_consecutive_failures
        ):
            self._latch("latched", error)

    def _latch(self, reason: str, error: str | None) -> None:
        """Latch the decider: later decides short-circuit with ``reason``.

        A cache hit (source ``cache``) or a ``should_ask`` veto
        (``not_asked``) still takes precedence — the latch check runs after
        both — so ``reason`` governs every other later decide.
        """
        self._latched = True
        self._latch_reason = reason
        self._latch_error = error

    def _fallback(
        self, state: S, reason: str | None, error: str | None, t0: float
    ) -> T:
        """Produce the floor action and emit a fallback event."""
        action = self._fallback_fn(state)
        self._emit("fallback", reason, error, t0, None, None)
        return action

    def _emit(
        self,
        source: str,
        reason: str | None,
        error: str | None,
        t0: float,
        usage: Usage | None,
        request_id: str | None,
    ) -> None:
        """Record and publish one DecisionEvent; observer errors are swallowed."""
        event = DecisionEvent(
            source=source,
            reason=reason,
            error=error,
            latency_s=self._clock() - t0,
            usage=usage,
            request_id=request_id,
        )
        self.last_event = event
        if self._on_event is not None:
            with contextlib.suppress(Exception):
                # diagnostics hooks must never break the decision loop
                self._on_event(event)
