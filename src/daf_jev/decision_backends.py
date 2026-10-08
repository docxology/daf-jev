"""Decision backend contracts and explicit, observable HTTP adapters.

Only the result *shape* is normalized. Missing beliefs remain missing.
Adapters make one transport attempt: the benchmark runner owns retry admission.
Optional training dependencies never enter the core import graph.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from daf_jev._json import strict_json_loads
from daf_jev._types import Question, parse_response

MAX_RESPONSE_BODY_BYTES = 1024 * 1024
RESPONSE_CHUNK_BYTES = 16 * 1024
_MEDIA_TYPES = frozenset({"application/json", "application/problem+json", "text/plain",
                          "text/html", "application/octet-stream"})
_BODY_CLASSES = frozenset({"json_object", "json_other", "invalid_json", "empty",
                          "incomplete", "body_limit_exceeded"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BackendCapabilities:
    primitives: tuple[str, ...] = ("noul", "choice", "score")
    modalities: tuple[str, ...] = ("text", "json")
    max_options: int | None = None
    max_questions: int | None = None
    max_context_chars: int | None = None
    batching: bool = True
    authentication: str = "none"
    probability_source: str | None = "native"
    confidence_semantics: str | None = "provider_defined"
    probability_rounding_digits: int | None = 2
    evidence: str = "declared_unverified"
    probability_semantics: str | None = None

    def __post_init__(self) -> None:
        if self.probability_semantics is not None and (
            not isinstance(self.probability_semantics, str) or not self.probability_semantics.strip()
        ):
            raise ValueError("probability_semantics must be a nonempty string or None")


@dataclass(frozen=True)
class DecisionRequest:
    state: Any
    questions: Mapping[str, Question]
    model: str | None = None
    timeout: float = 60.0
    settings: Mapping[str, Any] = field(default_factory=dict)
    observer: AttemptObserver | None = None


@dataclass(frozen=True)
class DecisionPrediction:
    type: str
    value: str | float
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    probability_source: str | None = None
    confidence_semantics: str | None = None
    probability_rounding_digits: int | None = None
    probability_semantics: str | None = None

    def __post_init__(self) -> None:
        if self.probability_semantics is not None and (
            not isinstance(self.probability_semantics, str) or not self.probability_semantics.strip()
        ):
            raise ValueError("probability_semantics must be a nonempty string or None")


@dataclass(frozen=True)
class HTTPResponseDiagnostics:
    """Bounded decoded-body observations, never raw provider text or headers."""
    body_sha256: str
    body_bytes_observed: int
    body_complete: bool
    digest_scope: str
    media_type: str | None
    classification: str
    body_limit_bytes: int = MAX_RESPONSE_BODY_BYTES

    def __post_init__(self) -> None:
        if (not isinstance(self.body_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.body_sha256) is None
                or isinstance(self.body_bytes_observed, bool)
                or not isinstance(self.body_bytes_observed, int)
                or not 0 <= self.body_bytes_observed <= MAX_RESPONSE_BODY_BYTES + RESPONSE_CHUNK_BYTES
                or not isinstance(self.body_complete, bool)
                or self.digest_scope != ("complete_decoded_body" if self.body_complete else "observed_decoded_prefix")
                or (self.media_type is not None and not isinstance(self.media_type, str))
                or self.media_type not in _MEDIA_TYPES | {None, "other"}
                or not isinstance(self.classification, str)
                or self.classification not in _BODY_CLASSES
                or self.body_limit_bytes != MAX_RESPONSE_BODY_BYTES
                or isinstance(self.body_limit_bytes, bool)
                or not isinstance(self.body_limit_bytes, int)):
            raise ValueError("invalid bounded HTTP response diagnostics")


class _ResponseCapture:
    """Retain at most the cap; hash/count each yielded decoded chunk once."""
    def __init__(self) -> None:
        self.content = bytearray()
        self.digest = hashlib.sha256()
        self.observed = 0
        self.complete = False
        self.exceeded = False

    def observe(self, chunk: bytes) -> None:
        self.digest.update(chunk)
        self.observed += len(chunk)
        self.content.extend(chunk[:max(0, MAX_RESPONSE_BODY_BYTES - len(self.content))])
        if self.observed > MAX_RESPONSE_BODY_BYTES:
            self.exceeded = True
            raise ValueError("response_body_limit_exceeded")


@dataclass(frozen=True)
class CallReceipt:
    attempt_id: str
    timestamp: str
    endpoint: str
    requested_model: str
    resolved_model: str | None
    provider: str | None
    response_id: str | None
    request_hash: str
    elapsed_s: float
    status_code: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: str | None
    cost_status: str
    error: str | None = None
    response_diagnostics: HTTPResponseDiagnostics | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionResult:
    predictions: dict[str, DecisionPrediction]
    receipts: tuple[CallReceipt, ...] = ()
    workflow: Mapping[str, Any] | None = None


@runtime_checkable
class DecisionBackend(Protocol):
    capabilities: BackendCapabilities
    model: str

    def predict(self, request: DecisionRequest) -> DecisionResult: ...
    def close(self) -> None: ...


@runtime_checkable
class AsyncDecisionBackend(Protocol):
    capabilities: BackendCapabilities
    model: str

    async def predict(self, request: DecisionRequest) -> DecisionResult: ...
    async def close(self) -> None: ...


class AttemptObserver(Protocol):
    def before(self, request_hash: str, model: str, endpoint: str) -> str: ...
    def after(self, receipt: CallReceipt) -> None: ...


class BackendHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"backend HTTP {status_code}")


def _tokens(usage: Mapping[str, Any], primary: str, alternate: str) -> int | None:
    value = usage.get(primary, usage.get(alternate))
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("token usage must be a nonnegative integer")
    return value


def _cost(usage: Mapping[str, Any]) -> str | None:
    value = usage.get("cost")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid reported cost")
    try:
        cost = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid reported cost") from exc
    if not cost.is_finite() or cost < 0 or cost.adjusted() > 9 or int(cost.as_tuple().exponent) < -18:
        raise ValueError("invalid reported cost")
    return str(cost)


def validate_endpoint(endpoint: str, *, hosted: bool) -> None:
    parts = urlsplit(endpoint)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("endpoint must not contain credentials, query, or fragment")
    if hosted:
        if parts.scheme != "https" or parts.hostname != "openrouter.ai" or parts.port not in (None, 443):
            raise ValueError("hosted benchmark endpoints must use https://openrouter.ai")
    elif parts.scheme not in ("http", "https") or parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("local benchmark endpoints must use loopback")
    if not parts.path:
        raise ValueError("endpoint requires an explicit API path")


class _HTTPAdapter:
    def __init__(
        self, *, endpoint: str, model: str, api_key: str | None = None,
        hosted: bool = False, mode: str = "systemone",
        capabilities: BackendCapabilities | None = None,
        observer: AttemptObserver | None = None, options: Mapping[str, Any] | None = None,
    ) -> None:
        validate_endpoint(endpoint, hosted=hosted)
        if mode not in ("systemone", "chat", "letter"):
            raise ValueError("mode must be systemone, chat, or letter")
        if not model or not model.strip():
            raise ValueError("model is required")
        if not hosted and api_key:
            raise ValueError("local decision adapters are keyless; hosted credentials cannot be sent to loopback")
        if hosted and not api_key:
            raise ValueError("OPENROUTER_API_KEY is required for hosted inference")
        self.endpoint, self.model, self.hosted, self.mode = endpoint, model, hosted, mode
        self.capabilities = capabilities or BackendCapabilities(
            probability_source="native" if mode == "systemone" else None,
            confidence_semantics="provider_defined" if mode == "systemone" else None,
        )
        self.capabilities = replace(self.capabilities, authentication="bearer" if hosted else "none")
        self.observer = observer
        self.options = copy.deepcopy(dict(options or {}))
        if hosted and set(self.options) - {"provider", "max_tokens", "temperature", "top_p", "seed", "response_format", "stop"}:
            raise ValueError("unsupported hosted execution settings; plugins and alternate routing are unbounded")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._credential_redactions = (api_key,) if api_key else ()

    def _body(self, request: DecisionRequest) -> dict[str, Any]:
        if not math.isfinite(request.timeout) or request.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        wire = {key: question.to_wire() for key, question in request.questions.items()}
        if not wire:
            raise ValueError("questions must be nonempty")
        caps = self.capabilities
        if caps.max_questions and len(wire) > caps.max_questions:
            raise ValueError("unsupported question count")
        if not caps.batching and len(wire) != 1:
            raise ValueError("backend does not support question batching")
        if caps.max_context_chars and len(canonical_json(request.state)) > caps.max_context_chars:
            raise ValueError("unsupported context length; state was not truncated")
        for question in wire.values():
            if question["type"] not in caps.primitives:
                raise ValueError(f"unsupported primitive {question['type']}")
            if caps.max_options and len(question.get("criteria", {})) > caps.max_options:
                raise ValueError("unsupported option count; vocabulary was not shortened")
        if self.hosted and (request.settings or (request.model and request.model != self.model)):
            raise ValueError("hosted settings/model are frozen in the backend profile")
        model = request.model or self.model
        options = self.options | dict(request.settings)
        if any(key in options for key in ("state", "questions", "model", "messages", "stream")):
            raise ValueError("execution settings cannot override semantic request fields")
        if self.mode == "systemone":
            return {"model": model, "state": request.state, "questions": wire, **options}
        if self.mode == "letter":
            if len(wire) != 1:
                raise ValueError("letter adapter requires one question")
            question = next(iter(wire.values()))
            criteria = question.get("criteria")
            if question["type"] != "choice" or not isinstance(criteria, dict) or len(criteria) > 24:
                raise ValueError("letter adapter supports choice with at most 24 options")
            prompt = {"state": request.state, "question": question["instructions"],
                      "options": {chr(65 + i): {"key": k, "description": v} for i, (k, v) in enumerate(criteria.items())}}
            instruction = "Return only the option letter. Do not generate reasoning."
        else:
            prompt = {"state": request.state, "questions": wire}
            instruction = ('Answer all questions as JSON {"answers":{"id":{"value":VALUE}}}. '
                           'Choice VALUE is an exact option key. Noul VALUE is a probability in [0,1]. '
                           'Score VALUE is a numeric level index. Return no confidence or invented probability vectors.')
            fields = {}
            for key, question in wire.items():
                kind = question["type"]
                value_schema = ({"type": "string", "enum": list(question["criteria"])} if kind == "choice"
                                else {"type": "number", "minimum": 0,
                                      "maximum": 1 if kind == "noul" else len(question["criteria"]) - 1})
                fields[key] = {"type": "object", "properties": {"value": value_schema},
                               "required": ["value"], "additionalProperties": False}
            answers_schema = {"type": "object", "properties": fields, "required": list(wire),
                              "additionalProperties": False}
            options.setdefault("response_format", {"type": "json_schema", "json_schema": {
                "name": "decision_answers", "strict": True, "schema": {"type": "object",
                    "properties": {"answers": answers_schema}, "required": ["answers"],
                    "additionalProperties": False}}})
        return {"model": model, "messages": [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False,
                    separators=(",", ":"), allow_nan=False)}], "temperature": 0,
                "max_tokens": 512, "stream": False, **options}

    @staticmethod
    def _complete_content(response: httpx.Response, capture: _ResponseCapture | None) -> bytes:
        if capture is not None:
            if capture.exceeded:
                raise ValueError("response_body_limit_exceeded")
            if not capture.complete:
                raise ValueError("incomplete_response_body")
            return bytes(capture.content)
        content = response.content
        if len(content) > MAX_RESPONSE_BODY_BYTES:
            raise ValueError("response_body_limit_exceeded")
        return content

    @staticmethod
    def _request_strings(body: Mapping[str, Any]) -> tuple[str, ...]:
        stack = [body.get("state"), body.get("questions")]
        for message in body.get("messages", []):
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                stack.append(content)
                with suppress(ValueError):
                    stack.append(strict_json_loads(content))
        strings = []
        while stack:
            item = stack.pop()
            if isinstance(item, str) and item:
                strings.append(item)
            elif isinstance(item, Mapping):
                stack.extend(item.keys())
                stack.extend(item.values())
            elif isinstance(item, (list, tuple)):
                stack.extend(item)
        return tuple(strings)

    def _safe_identifier(self, value: Any, *, provider: bool = False,
                         request_strings: tuple[str, ...] = ()) -> str | None:
        pattern = r"[A-Za-z0-9][A-Za-z0-9_. +:/-]{0,127}" if provider else r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}"
        if (not isinstance(value, str) or re.fullmatch(pattern, value) is None
                or value.lower().startswith(("sk-", "bearer "))
                or any(secret in value for secret in self._credential_redactions)
                or any(value == item or (len(item) >= 8 and item in value) for item in request_strings)):
            return None
        return value

    def _receipt(self, attempt: str, body: dict[str, Any], start: float,
                 response: httpx.Response | None, error: str | None = None,
                 *, capture: _ResponseCapture | None = None) -> CallReceipt:
        payload: dict[str, Any] = {}
        diagnostics = None
        if response is not None:
            if capture is None:
                capture = _ResponseCapture()
                try:
                    # Pure reduction of an already-buffered response obeys the
                    # same parse cap; real transports capture while streaming.
                    for offset in range(0, len(response.content), RESPONSE_CHUNK_BYTES):
                        capture.observe(response.content[offset:offset + RESPONSE_CHUNK_BYTES])
                    capture.complete = True
                except (ValueError, httpx.ResponseNotRead):
                    pass
            classification = "incomplete"
            try:
                content = self._complete_content(response, capture)
                data = strict_json_loads(content, parse_float=Decimal)
                classification = "json_object" if isinstance(data, dict) else "json_other"
                if isinstance(data, dict):
                    payload = data
            except ValueError:
                if capture.exceeded:
                    classification = error = "body_limit_exceeded"
                elif capture.complete:
                    classification = "invalid_json" if capture.observed else "empty"
                    error = "invalid_json"
                else:
                    error = error or "incomplete_response_body"
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            diagnostics = HTTPResponseDiagnostics(
                capture.digest.hexdigest(), capture.observed, capture.complete,
                "complete_decoded_body" if capture.complete else "observed_decoded_prefix",
                (media_type if media_type in _MEDIA_TYPES else "other") if media_type else None,
                classification,
            )
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, dict):
            error = error or "invalid_accounting"
        usage = usage if isinstance(usage, dict) else {}
        cost = input_tokens = output_tokens = None
        try:
            cost = _cost(usage)
        except ValueError:
            error = error or "invalid_accounting"
        try:
            input_tokens = _tokens(usage, "input_tokens", "prompt_tokens")
        except ValueError:
            error = error or "invalid_accounting"
        try:
            output_tokens = _tokens(usage, "output_tokens", "completion_tokens")
        except ValueError:
            error = error or "invalid_accounting"
        request_strings = self._request_strings(body)
        def optional_string(key: str) -> str | None:
            return self._safe_identifier(payload.get(key), provider=key == "provider", request_strings=request_strings)
        return CallReceipt(
            attempt, utc_now(), self.endpoint, body["model"], optional_string("model"),
            optional_string("provider"), optional_string("id") or
            (self._safe_identifier(response.headers.get("x-typesafe-request-id"), request_strings=request_strings)
             if response is not None else None),
            content_hash(body), time.perf_counter() - start,
            response.status_code if response is not None else None, input_tokens, output_tokens,
            cost if self.hosted else None, ("reported" if cost is not None else "unknown") if self.hosted else "local", error,
            diagnostics,
        )

    def _decode(self, response: httpx.Response, request: DecisionRequest, receipt: CallReceipt,
                *, capture: _ResponseCapture | None = None) -> DecisionResult:
        if not response.is_success:
            raise BackendHTTPError(response.status_code)
        payload = strict_json_loads(self._complete_content(response, capture))
        if not isinstance(payload, dict):
            raise ValueError("decision response must be an object")
        if "truncated" in payload and not isinstance(payload["truncated"], bool):
            raise ValueError("invalid provider truncation flag")
        if payload.get("truncated") is True:
            raise ValueError("provider truncated the requested state")
        usage = payload.get("usage", {})
        if isinstance(usage, dict):
            state_tokens = _tokens(usage, "state_tokens", "state_tokens")
            used_tokens = _tokens(usage, "state_tokens_used", "state_tokens_used")
            if state_tokens is not None and used_tokens is not None and used_tokens < state_tokens:
                raise ValueError("provider did not consume the complete state")
        predictions = {}
        if self.mode == "systemone":
            from daf_jev._types import validate_response
            result = parse_response(payload, probability_rounding_digits=self.capabilities.probability_rounding_digits)
            validate_response(result, request.questions, probability_rounding_digits=self.capabilities.probability_rounding_digits)
            for key, answer in result.answers.items():
                kind = answer.type
                value = getattr(answer, "choice", getattr(answer, "score", getattr(answer, "noul", None)))
                if not isinstance(value, (str, float, int)):
                    raise ValueError("native decision lacks a primary value")
                probabilities = getattr(answer, "probabilities", None)
                source = self.capabilities.probability_source
                if kind == "noul":
                    probabilities = {"false": 1 - float(value), "true": float(value)}
                    source = "native_binary_scalar"
                predictions[key] = DecisionPrediction(kind, value, probabilities,
                    getattr(answer, "confidence", None), source,
                    self.capabilities.confidence_semantics, self.capabilities.probability_rounding_digits,
                    self.capabilities.probability_semantics)
        else:
            choice = payload["choices"][0]
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise ValueError("incomplete chat decision")
            content = choice["message"]["content"]
            if self.mode == "letter":
                key, question = next(iter(request.questions.items()))
                labels = list(question.to_wire()["criteria"])
                if content.strip() not in [chr(65+i) for i in range(len(labels))]:
                    raise ValueError("invalid option letter")
                answers = {key: {"value": labels[ord(content.strip()) - 65]}}
            else:
                answers = strict_json_loads(content)["answers"]
            if set(answers) != set(request.questions):
                raise ValueError("chat answer IDs do not match request")
            for key, question in request.questions.items():
                wire = question.to_wire()
                value = answers[key]["value"]
                kind = wire["type"]
                if kind == "choice":
                    if not isinstance(value, str) or value not in wire["criteria"]:
                        raise ValueError("invalid chat choice")
                else:
                    upper = 1 if kind == "noul" else len(wire["criteria"]) - 1
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= upper:
                        raise ValueError("invalid chat numeric decision")
                    value = float(value)
                # A generated noul scalar is self-reported, never native belief.
                predictions[key] = DecisionPrediction(kind, value, probability_source="generated" if kind == "noul" else None)
        return DecisionResult(predictions, (receipt,))


class HTTPDecisionBackend(_HTTPAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = httpx.Client(follow_redirects=False, trust_env=False)

    def predict(self, request: DecisionRequest) -> DecisionResult:
        body = self._body(request)
        observer = request.observer or self.observer
        attempt = observer.before(content_hash(body), body["model"], self.endpoint) if observer else str(uuid.uuid4())
        start = time.perf_counter()
        response = None
        capture = None
        error = None
        failure = None
        try:
            with self._client.stream("POST", self.endpoint, json=body, headers=self._headers,
                                     timeout=request.timeout) as response:
                capture = _ResponseCapture()
                for chunk in response.iter_bytes(chunk_size=RESPONSE_CHUNK_BYTES):
                    capture.observe(chunk)
                capture.complete = True
                initial = self._receipt(attempt, body, start, response, capture=capture)
                if initial.error:
                    raise ValueError(initial.error)
                decoded = self._decode(response, request, initial, capture=capture)
        except BaseException as exc:
            error = type(exc).__name__
            failure = exc
            raise
        finally:
            try:
                receipt = self._receipt(attempt, body, start, response, error, capture=capture)
                if observer:
                    observer.after(receipt)
            except BaseException as finalization_error:
                if failure is not None and not isinstance(failure, Exception):
                    raise failure from finalization_error
                raise
        return DecisionResult(decoded.predictions, (receipt,))

    def close(self) -> None:
        self._client.close()


class AsyncHTTPDecisionBackend(_HTTPAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = httpx.AsyncClient(follow_redirects=False, trust_env=False)

    async def predict(self, request: DecisionRequest) -> DecisionResult:
        body = self._body(request)
        observer = request.observer or self.observer
        attempt = observer.before(content_hash(body), body["model"], self.endpoint) if observer else str(uuid.uuid4())
        start = time.perf_counter()
        response = None
        capture = None
        error = None
        failure = None
        try:
            async with self._client.stream("POST", self.endpoint, json=body, headers=self._headers,
                                           timeout=request.timeout) as response:
                capture = _ResponseCapture()
                async for chunk in response.aiter_bytes(chunk_size=RESPONSE_CHUNK_BYTES):
                    capture.observe(chunk)
                capture.complete = True
                initial = self._receipt(attempt, body, start, response, capture=capture)
                if initial.error:
                    raise ValueError(initial.error)
                decoded = self._decode(response, request, initial, capture=capture)
        except BaseException as exc:
            error = type(exc).__name__
            failure = exc
            raise
        finally:
            try:
                receipt = self._receipt(attempt, body, start, response, error, capture=capture)
                if observer:
                    observer.after(receipt)
            except BaseException as finalization_error:
                if failure is not None and not isinstance(failure, Exception):
                    raise failure from finalization_error
                raise
        return DecisionResult(decoded.predictions, (receipt,))

    async def close(self) -> None:
        await self._client.aclose()


class PriorBackend:
    """Frozen reference prior; fit only with explicitly supplied training rows."""
    def __init__(self, priors: Mapping[str, Mapping[str, float]] | None = None) -> None:
        self.model = "training-prior"
        self.capabilities = BackendCapabilities(probability_source="training_prior" if priors else "uniform_reference", confidence_semantics="top_probability", probability_rounding_digits=None,
            probability_semantics="training_label_frequency" if priors else "uniform_reference_distribution")
        self.priors = dict(priors or {})

    def predict(self, request: DecisionRequest) -> DecisionResult:
        answers = {}
        for key, question in request.questions.items():
            wire = question.to_wire()
            kind = wire["type"]
            labels = list(wire["criteria"]) if kind == "choice" else ([str(i) for i in range(len(wire["criteria"]))] if kind == "score" else ["false", "true"])
            probs = dict(self.priors.get(key, dict.fromkeys(labels, 1 / len(labels))))
            from daf_jev._types import validate_probability_row
            validate_probability_row(probs)
            if set(probs) != set(labels):
                raise ValueError("prior vocabulary does not match request")
            label = max(labels, key=lambda x: probs[x])
            value = label if kind == "choice" else (sum(int(k)*v for k,v in probs.items()) if kind == "score" else probs["true"])
            answers[key] = DecisionPrediction(kind, value, probs, max(probs.values()), "training_prior" if key in self.priors else "uniform_reference", "top_probability",
                probability_semantics="training_label_frequency" if key in self.priors else "uniform_reference_distribution")
        return DecisionResult(answers)

    def close(self) -> None:
        pass


class ThreadedAsyncBackend:
    """Explicit wrapper for sync estimators. Cancellation does not kill a thread."""
    def __init__(self, backend: DecisionBackend) -> None:
        self.backend = backend
        self.model, self.capabilities = backend.model, backend.capabilities

    async def predict(self, request: DecisionRequest) -> DecisionResult:
        return await asyncio.to_thread(self.backend.predict, request)

    async def close(self) -> None:
        await asyncio.to_thread(self.backend.close)
