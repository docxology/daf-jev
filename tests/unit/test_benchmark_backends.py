"""Real local HTTP tests of native/generated decisions and attempt receipts."""

import asyncio
import json
import time

import httpx
import pytest

from daf_jev import choice, noul, score
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendCapabilities,
    BackendHTTPError,
    DecisionRequest,
    HTTPDecisionBackend,
    PriorBackend,
    ThreadedAsyncBackend,
    validate_endpoint,
)


class ObservationLog:
    """Injected recording observer, not a replacement for daf-jev behavior."""
    def __init__(self):
        self.started = []
        self.receipts = []

    def before(self, request_hash, model, endpoint):
        self.started.append((request_hash, model, endpoint))
        return f"attempt-{len(self.started)}"

    def after(self, receipt):
        self.receipts.append(receipt)


def _questions():
    return {"decision": choice("Choose an outcome.", {"a": "first", "b": "second"})}


def _native(**overrides):
    return {"model": "resolved-model", "id": "response-id", "provider": "fixture-provider",
            "answers": {"decision": {"type": "choice", "choice": "a",
                                       "probabilities": {"a": .7, "b": .3}, "confidence": .7}},
            "usage": {"input_tokens": 12, "output_tokens": 3, "cost": "0.00125"}, **overrides}


def test_native_request_and_exact_accounting_receipt(stub):
    stub.enqueue(body=_native())
    log = ObservationLog()
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="requested-model", observer=log)
    try:
        result = backend.predict(DecisionRequest("public fixture", _questions(), timeout=2))
    finally:
        backend.close()
    assert result.predictions["decision"].probabilities == {"a": .7, "b": .3}
    receipt = result.receipts[0]
    assert receipt.requested_model == "requested-model" and receipt.resolved_model == "resolved-model"
    assert receipt.response_id == "response-id" and receipt.provider == "fixture-provider"
    assert receipt.input_tokens == 12 and receipt.output_tokens == 3
    assert receipt.cost_usd is None and receipt.cost_status == "local"
    assert len(log.started) == len(log.receipts) == len(stub.hits) == 1
    assert stub.hits[0]["json"]["state"] == "public fixture"
    assert "authorization" not in stub.hits[0]["headers"]
    assert backend.capabilities.authentication == "none"


@pytest.mark.parametrize("mode,content", [("chat", '{"answers":{"decision":{"value":"b"}}}'), ("letter", " B ")])
def test_generated_answers_preserve_missing_distributions(stub, mode, content):
    stub.enqueue(body={"model": "generated-model", "choices": [{"finish_reason": "stop", "message": {"content": content}}]})
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/chat/completions", model="fixture", mode=mode)
    try:
        result = backend.predict(DecisionRequest("fixture", _questions(), timeout=2))
    finally:
        backend.close()
    answer = result.predictions["decision"]
    assert answer.value == "b" and answer.probabilities is None and answer.confidence is None
    assert result.receipts[0].input_tokens is None and result.receipts[0].cost_usd is None
    assert result.receipts[0].cost_status == "local"
    assert stub.hits[0]["json"]["temperature"] == 0


def test_generated_noul_is_self_reported_scalar_not_native_belief(stub):
    content = json.dumps({"answers": {"decision": {"value": .8}}})
    stub.enqueue(body={"choices": [{"message": {"content": content}}]})
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/chat/completions", model="fixture", mode="chat")
    try:
        result = backend.predict(DecisionRequest("fixture", {"decision": noul("True?")}, timeout=2))
    finally:
        backend.close()
    assert result.predictions["decision"].value == .8
    assert result.predictions["decision"].probability_source == "generated"
    assert result.predictions["decision"].probabilities is None


def test_native_noul_probability_scalar_has_complement_distribution_without_invented_confidence(stub):
    stub.enqueue(body={"model": "fixture", "answers": {"decision": {"type": "noul", "noul": .8}}, "usage": {}})
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="fixture")
    try:
        result = backend.predict(DecisionRequest("fixture", {"decision": noul("True?")}, timeout=2))
    finally:
        backend.close()
    answer = result.predictions["decision"]
    assert answer.value == .8 and answer.confidence is None
    assert answer.probabilities == {"false": pytest.approx(.2), "true": .8}
    assert answer.probability_source == "native_binary_scalar"


@pytest.mark.parametrize("body", [
    {"choices": [{"finish_reason": "length", "message": {"content": '{"answers":{"decision":{"value":"a"}}}'}}], "usage": {"cost": ".002"}},
    {"choices": [{"message": {"content": "not json"}}], "usage": {"cost": ".002"}},
    _native(answers={}),
    _native(usage={"cost": ".002", "input_tokens": -1}),
])
def test_decode_failure_retains_local_attempt_receipt(stub, body):
    stub.enqueue(body=body)
    log = ObservationLog()
    mode = "chat" if "choices" in body else "systemone"
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", mode=mode, observer=log)
    try:
        with pytest.raises(ValueError):
            backend.predict(DecisionRequest("fixture", _questions(), timeout=2))
    finally:
        backend.close()
    assert len(log.started) == len(log.receipts) == 1
    assert log.receipts[0].cost_status == "local"
    assert log.receipts[0].error is not None


def test_http_error_has_one_transport_attempt_without_hidden_retry(stub):
    stub.enqueue(503, body={"error": "unavailable", "usage": {"cost": ".001"}})
    log = ObservationLog()
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", observer=log)
    try:
        with pytest.raises(BackendHTTPError) as caught:
            backend.predict(DecisionRequest("fixture", _questions(), timeout=2))
        assert caught.value.status_code == 503
    finally:
        backend.close()
    assert len(stub.hits) == len(log.receipts) == 1
    assert log.receipts[0].cost_usd is None


@pytest.mark.parametrize("capabilities,decision_request", [
    (BackendCapabilities(max_options=1), DecisionRequest("fixture", _questions())),
    (BackendCapabilities(batching=False), DecisionRequest("fixture", {**_questions(), "second": noul("Yes?")})),
    (BackendCapabilities(primitives=("noul",)), DecisionRequest("fixture", _questions())),
    (BackendCapabilities(max_context_chars=1), DecisionRequest("fixture", _questions())),
    (BackendCapabilities(), DecisionRequest("fixture", _questions(), settings={"state": "override"})),
    (BackendCapabilities(), DecisionRequest("fixture", _questions(), timeout=float("nan"))),
])
def test_unsupported_requests_reject_before_attempt_without_reduction(stub, capabilities, decision_request):
    log = ObservationLog()
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", capabilities=capabilities, observer=log)
    try:
        with pytest.raises(ValueError):
            backend.predict(decision_request)
    finally:
        backend.close()
    assert log.started == log.receipts == stub.hits == []


def test_async_native_and_timeout_receipts(stub):
    async def run():
        log = ObservationLog()
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", observer=log)
        try:
            stub.enqueue(body=_native())
            result = await backend.predict(DecisionRequest("fixture", _questions(), timeout=2))
            assert result.predictions["decision"].value == "a"
            stub.enqueue(body=_native(), delay=.15)
            with pytest.raises(httpx.TimeoutException):
                await backend.predict(DecisionRequest("fixture", _questions(), timeout=.01))
            assert len(log.receipts) == 2 and log.receipts[-1].error is not None
        finally:
            await backend.close()
    asyncio.run(run())


def test_prior_and_threaded_async_preserve_complete_vocabulary():
    prior = PriorBackend({"decision": {"a": .25, "b": .75}})
    result = prior.predict(DecisionRequest("fixture", _questions()))
    assert result.predictions["decision"].value == "b"
    async def run():
        wrapped = ThreadedAsyncBackend(prior)
        assert (await wrapped.predict(DecisionRequest("fixture", _questions()))).predictions == result.predictions
        await wrapped.close()
    asyncio.run(run())
    numeric = PriorBackend().predict(DecisionRequest("fixture", {"n": noul("Yes?"), "s": score("Level?", ["low", "high"])}))
    assert numeric.predictions["n"].value == numeric.predictions["s"].value == .5
    with pytest.raises(ValueError):
        PriorBackend({"decision": {"a": 1.}}).predict(DecisionRequest("fixture", _questions()))


@pytest.mark.parametrize("endpoint,hosted", [("http://example.com/api", False), ("https://user:secret@openrouter.ai/api", True),
                                           ("https://openrouter.ai/api?key=secret", True), ("https://other.example/api", True)])
def test_endpoint_credentials_and_destination_validation(endpoint, hosted):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint, hosted=hosted)


def test_hosted_paid_accounting_survives_pure_decoding_failure_without_network():
    # The real HTTP path is tested above with loopback. This pure response
    # reduction tests hosted billing metadata without sending a hosted request.
    import time
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/v1/systemone",
                                  model="fixture", hosted=True, api_key="public-unit-test-placeholder")
    request = DecisionRequest("public fixture", _questions())
    body = backend._body(request)
    response = httpx.Response(200, json=_native(answers={}))
    try:
        receipt = backend._receipt("public-fixture-attempt", body, time.perf_counter(), response)
        assert receipt.cost_usd == "0.00125" and receipt.cost_status == "reported"
        with pytest.raises(ValueError):
            backend._decode(response, request, receipt)
        assert receipt.resolved_model == "resolved-model" and receipt.response_id == "response-id"
    finally:
        backend.close()


@pytest.mark.parametrize("backend_class", [HTTPDecisionBackend, AsyncHTTPDecisionBackend])
def test_local_adapters_cannot_receive_hosted_credentials(stub, backend_class):
    with pytest.raises(ValueError, match="keyless"):
        backend_class(endpoint=stub.base_url + "/v1/fixture", model="fixture",
                      api_key="public-unit-test-placeholder")
    assert stub.hits == []


@pytest.mark.parametrize("settings", [
    {"plugins": [{"id": "web"}]},
    {"models": ["different-provider-model"]},
    {"route": "fallback"},
    {"max_completion_tokens": 1000000},
])
def test_unbounded_hosted_options_rejected_before_client_or_admission(settings):
    log = ObservationLog()
    with pytest.raises(ValueError, match="unbounded"):
        HTTPDecisionBackend(endpoint="https://openrouter.ai/api/v1/chat/completions",
                            model="fixture", hosted=True, api_key="public-unit-test-placeholder",
                            options=settings, observer=log)
    assert log.started == log.receipts == []


@pytest.mark.parametrize("changes", [
    {"settings": {"provider": {"max_price": {"prompt": 999}}}},
    {"settings": {"max_tokens": 1000000}},
    {"model": "different-provider-model"},
])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_hosted_request_cannot_override_frozen_tariff_before_admission(changes, asynchronous):
    log = ObservationLog()
    arguments = {"endpoint": "https://openrouter.ai/api/v1/chat/completions",
                 "model": "fixture", "hosted": True, "mode": "chat",
                 "api_key": "public-unit-test-placeholder", "observer": log,
                 "options": {"max_tokens": 8, "provider": {"allow_fallbacks": False,
                     "require_parameters": True, "max_price": {"prompt": 1, "completion": 2,
                                                                "request": 0, "image": 0}}}}
    request = DecisionRequest("public fixture", _questions(), **changes)
    if asynchronous:
        async def run():
            backend = AsyncHTTPDecisionBackend(**arguments)
            try:
                with pytest.raises(ValueError, match="frozen"):
                    await backend.predict(request)
            finally:
                await backend.close()
        asyncio.run(run())
    else:
        backend = HTTPDecisionBackend(**arguments)
        try:
            with pytest.raises(ValueError, match="frozen"):
                backend.predict(request)
        finally:
            backend.close()
    assert log.started == log.receipts == []


def test_caller_mutation_cannot_raise_frozen_provider_ceiling():
    options = {"max_tokens": 8, "provider": {"max_price": {"prompt": 1, "completion": 2,
                                                            "request": 0, "image": 0}}}
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/v1/chat/completions",
                                  model="fixture", hosted=True, mode="chat",
                                  api_key="public-unit-test-placeholder", options=options)
    options["provider"]["max_price"]["prompt"] = 999
    options["max_tokens"] = 1000000
    try:
        body = backend._body(DecisionRequest("public fixture", _questions()))
        assert body["max_tokens"] == 8
        assert body["provider"]["max_price"]["prompt"] == 1
    finally:
        backend.close()


def test_numeric_json_billing_keeps_all_reported_decimal_digits():
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/v1/systemone",
                                  model="fixture", hosted=True, api_key="public-unit-test-placeholder")
    try:
        body = backend._body(DecisionRequest("public fixture", _questions()))
        response = httpx.Response(200, content=b'{"usage":{"cost":0.123456789012345678,"input_tokens":12,"output_tokens":3}}')
        receipt = backend._receipt("public-fixture-attempt", body, time.perf_counter(), response)
        assert receipt.cost_usd == "0.123456789012345678"
        assert receipt.cost_status == "reported"
        assert receipt.input_tokens == 12 and receipt.output_tokens == 3
    finally:
        backend.close()


@pytest.mark.parametrize("cost", [True, -1, "NaN", "Infinity", "1E1000000"])
def test_invalid_provider_cost_is_unknown_and_never_published_as_free(cost):
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/v1/systemone",
                                  model="fixture", hosted=True, api_key="public-unit-test-placeholder")
    try:
        body = backend._body(DecisionRequest("public fixture", _questions()))
        response = httpx.Response(200, json=_native(usage={"cost": cost, "input_tokens": 1,
                                                          "output_tokens": 1}))
        receipt = backend._receipt("public-fixture-attempt", body, time.perf_counter(), response)
        assert receipt.cost_usd is None
        assert receipt.cost_status == "unknown"
        assert receipt.error == "invalid_accounting"
    finally:
        backend.close()


@pytest.mark.parametrize("metadata", [
    {"truncated": True},
    {"truncated": "true"},
    {"truncated": 0},
    {"usage": {"state_tokens": 100, "state_tokens_used": 99}},
    {"usage": {"state_tokens": float("nan"), "state_tokens_used": 100}},
    {"usage": {"state_tokens": 100, "state_tokens_used": float("nan")}},
    {"usage": {"state_tokens": "10", "state_tokens_used": "9"}},
    {"usage": {"state_tokens": 100, "state_tokens_used": 100.5}},
])
def test_underconsumed_or_invalid_state_metadata_never_becomes_quality(stub, metadata):
    stub.enqueue(body=_native(**metadata))
    log = ObservationLog()
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", observer=log)
    try:
        with pytest.raises(ValueError):
            backend.predict(DecisionRequest("public complete state", _questions(), timeout=2))
    finally:
        backend.close()
    assert len(stub.hits) == len(log.started) == len(log.receipts) == 1
    assert log.receipts[0].error is not None


@pytest.mark.parametrize("asynchronous", [False, True])
def test_chat_schema_preserves_large_vocabulary_and_mixed_primitive_bounds(stub, asynchronous):
    labels = {f"intent_{i}": None for i in range(151)}
    questions = {"intent": choice("Choose the complete intent label.", labels),
                 "binary": noul("Is the condition true?"),
                 "ordinal": score("Choose a severity level.", ["none", "low", "medium", "high"])}
    content = json.dumps({"answers": {"intent": {"value": "intent_150"},
                                      "binary": {"value": .8}, "ordinal": {"value": 2.5}}})
    stub.enqueue(body={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})
    arguments = {"endpoint": stub.base_url + "/v1/chat/completions", "model": "fixture", "mode": "chat"}
    request = DecisionRequest("public fixture", questions, timeout=2)
    if asynchronous:
        async def run():
            backend = AsyncHTTPDecisionBackend(**arguments)
            try:
                return await backend.predict(request)
            finally:
                await backend.close()
        result = asyncio.run(run())
    else:
        backend = HTTPDecisionBackend(**arguments)
        try:
            result = backend.predict(request)
        finally:
            backend.close()
    assert len(stub.hits) == 1
    sent = stub.hits[0]["json"]
    constraint = sent["response_format"]
    assert constraint["type"] == "json_schema"
    assert constraint["json_schema"]["strict"] is True
    schema = constraint["json_schema"]["schema"]
    assert schema["required"] == ["answers"] and schema["additionalProperties"] is False
    answers = schema["properties"]["answers"]
    assert set(answers["required"]) == set(answers["properties"]) == set(questions)
    assert answers["additionalProperties"] is False
    fields = answers["properties"]
    assert fields["intent"]["properties"]["value"] == {"type": "string", "enum": list(labels)}
    assert fields["binary"]["properties"]["value"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert fields["ordinal"]["properties"]["value"] == {"type": "number", "minimum": 0, "maximum": 3}
    assert all(row["required"] == ["value"] and row["additionalProperties"] is False for row in fields.values())
    prompt = json.loads(sent["messages"][1]["content"])
    assert set(prompt["questions"]["intent"]["criteria"]) == set(labels)
    assert result.predictions["intent"].value == "intent_150"
    assert result.predictions["binary"].value == .8
    assert result.predictions["ordinal"].value == 2.5
    assert all(prediction.probabilities is None and prediction.confidence is None
               for prediction in result.predictions.values())


def test_explicit_chat_output_format_remains_caller_selected(stub):
    explicit = {"type": "json_object"}
    stub.enqueue(body={"choices": [{"message": {"content": '{"answers":{"decision":{"value":"a"}}}'}}]})
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/chat/completions", model="fixture",
                                  mode="chat", options={"response_format": explicit})
    try:
        assert backend.predict(DecisionRequest("public fixture", _questions(), timeout=2)).predictions["decision"].value == "a"
    finally:
        backend.close()
    assert stub.hits[0]["json"]["response_format"] == explicit


@pytest.mark.parametrize("mode", ["systemone", "letter"])
def test_chat_schema_is_not_injected_into_native_or_letter_contract(stub, mode):
    payload = _native() if mode == "systemone" else {"choices": [{"message": {"content": "A"}}]}
    stub.enqueue(body=payload)
    backend = HTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture", mode=mode)
    try:
        backend.predict(DecisionRequest("public fixture", _questions(), timeout=2))
    finally:
        backend.close()
    assert "response_format" not in stub.hits[0]["json"]
