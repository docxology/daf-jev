"""Ambiguous JSON is rejected through the real native HTTP clients."""

import asyncio
from decimal import Decimal

import pytest

from daf_jev import AsyncJevClient, JevClient, RetryPolicy, noul
from daf_jev._errors import AuthenticationError
from daf_jev._json import strict_json_loads
from daf_jev.decision_backends import AsyncHTTPDecisionBackend, DecisionRequest


@pytest.mark.parametrize("text", [
    '{"usage":{"cost":100,"cost":0}}',
    '{"answers":{"q":{"noul":1.1,"noul":0.5}}}',
    '{"a":1,"\\u0061":2}',
    '[{"nested":{"value":0,"value":1}}]',
    '{"answers":{"q":{},"q":{}}}',
])
def test_rejects_duplicate_keys_in_every_object(text):
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        strict_json_loads(text, parse_float=Decimal)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rejects_nonstandard_constants(constant):
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        strict_json_loads('{"usage":{"cost":' + constant + '}}')


def test_retains_exact_decimal_currency_and_order():
    result = strict_json_loads(
        '{"z":{"β":0,"a":1},"usage":{"cost":0.123456789012345678}}',
        parse_float=Decimal,
    )
    assert list(result) == ["z", "usage"]
    assert list(result["z"]) == ["β", "a"]
    assert result["usage"]["cost"] == Decimal("0.123456789012345678")
    assert strict_json_loads(bytearray(b'{"ok":true}')) == {"ok": True}


@pytest.mark.parametrize("literal", ["1e999", "-1e999", "1e999999999999999999999"])
def test_default_number_parser_rejects_overflow(literal):
    with pytest.raises(ValueError, match="must be finite"):
        strict_json_loads('{"number":' + literal + '}')


def test_decimal_precision_failure_uses_receipt_error_path():
    with pytest.raises(ValueError, match="supported precision"):
        strict_json_loads('{"cost":1e999999999999999999999}', parse_float=Decimal)
    assert strict_json_loads('{"cost":1e999}', parse_float=Decimal)["cost"] == Decimal("1e999")
    with pytest.raises(ValueError, match="must be finite"):
        strict_json_loads('{"cost":0.1}', parse_float=lambda _: Decimal("NaN"))


def test_decimal_failure_finalizes_real_http_attempt_receipt(stub):
    stub.enqueue(text='{"answers":{"q":{"type":"noul","noul":0.5,"confidence":0.7}},'
                      '"usage":{"cost":1e999999999999999999999}}')

    class Observer:
        def __init__(self):
            self.started, self.receipts = [], []

        def before(self, request_hash, model, endpoint):
            self.started.append(request_hash)
            return "owned-fixture-attempt"

        def after(self, receipt):
            self.receipts.append(receipt)

    observer = Observer()

    async def run():
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/fixture", model="fixture")
        try:
            with pytest.raises(ValueError):
                await backend.predict(DecisionRequest("fixture", {"q": noul("True?")}, observer=observer))
        finally:
            await backend.close()

    asyncio.run(run())
    assert len(stub.hits) == len(observer.started) == len(observer.receipts) == 1
    assert observer.receipts[0].error == "invalid_json"


def test_decoder_recursion_uses_malformed_response_error():
    # Exercise a real json.loads callback. New Python parsers can handle deeply
    # nested arrays iteratively; this keeps the failure path runtime independent.
    def recursive_float(value):
        return recursive_float(value)

    with pytest.raises(ValueError, match="JSON exceeds supported nesting depth"):
        strict_json_loads('{"number":0.5}', parse_float=recursive_float)


@pytest.mark.parametrize("body", [
    '{"answers":{"q":{"type":"noul","noul":1.1,"noul":0.5}}}',
    '{"answers":{"q":{"type":"noul","noul":0.5,"confidence":NaN}}}',
    '{"answers":{"q":{"type":"noul","noul":0.5}},"usage":{"input_tokens":2,"input_tokens":1}}',
])
def test_native_sync_rejects_ambiguous_real_http_body(stub, body):
    stub.enqueue(text=body)
    with (
        JevClient(api_key="fixture-only", base_url=stub.base_url,
                  retry=RetryPolicy(max_attempts=1)) as client,
        pytest.raises(ValueError),
    ):
        client.ask("fixture", {"q": noul("True?")})
    assert len(stub.hits) == 1


def test_native_async_rejects_ambiguous_real_http_body(stub):
    stub.enqueue(text='{"answers":{"q":{"type":"noul","noul":1.1,"noul":0.5}}}')

    async def run():
        async with AsyncJevClient(api_key="fixture-only", base_url=stub.base_url, retry=RetryPolicy(max_attempts=1)) as client:
            with pytest.raises(ValueError):
                await client.ask("fixture", {"q": noul("True?")})

    asyncio.run(run())
    assert len(stub.hits) == 1


def test_malformed_error_json_preserves_status_error_taxonomy(stub):
    stub.enqueue(401, text='{"error":"first","error":"second"}')
    with (
        JevClient(api_key="fixture-only", base_url=stub.base_url,
                  retry=RetryPolicy(max_attempts=1)) as client,
        pytest.raises(AuthenticationError) as caught,
    ):
        client.ask("fixture", {"q": noul("True?")})
    assert caught.value.status_code == 401
    assert caught.value.body == '{"error":"first","error":"second"}'
    assert len(stub.hits) == 1
