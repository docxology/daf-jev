"""Owned loopback responses exercise bounded diagnostics without provider I/O."""
import asyncio
import gzip
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from daf_jev import choice
from daf_jev._cancellation import (
    cancellation_workflow,
    mark_cancellation,
    original_cancellation,
)
from daf_jev.benchmark_datasets import make_synthetic_dataset, save_dataset
from daf_jev.benchmark_runner import execute_run, plan_run, report_run
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import (
    MAX_RESPONSE_BODY_BYTES,
    RESPONSE_CHUNK_BYTES,
    AsyncHTTPDecisionBackend,
    BackendHTTPError,
    DecisionRequest,
    HTTPDecisionBackend,
    content_hash,
)


class _Log:
    def __init__(self):
        self.started = []
        self.receipts = []

    def before(self, request_hash, model, endpoint):
        self.started.append((request_hash, model, endpoint))
        return f"owned-attempt-{len(self.started)}"

    def after(self, receipt):
        self.receipts.append(receipt)


def _request():
    return DecisionRequest("private-state-canary", {"decision": choice(
        "Choose without disclosing private-instructions-canary.", {"a": "first", "b": "second"})}, timeout=2)


def _native(**changes):
    return {"model": "resolved-model", "provider": "fixture-provider", "id": "response-id",
            "answers": {"decision": {"type": "choice", "choice": "a",
                "probabilities": {"a": .7, "b": .3}, "confidence": .7}}, "usage": {}, **changes}


def _call(stub, asynchronous, log, *, mode="systemone", request=None):
    args = {"endpoint": stub.base_url + "/v1/fixture", "model": "fixture",
            "mode": mode, "observer": log}
    if asynchronous:
        async def run():
            backend = AsyncHTTPDecisionBackend(**args)
            try:
                return await backend.predict(request or _request())
            finally:
                await backend.close()
        return asyncio.run(run())
    backend = HTTPDecisionBackend(**args)
    try:
        return backend.predict(request or _request())
    finally:
        backend.close()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_successful_http_finalizer_cancellation_cannot_inherit_previous_request(stub, asynchronous):
    stub.enqueue(body=_native())

    class CancelAfter(_Log):
        def after(self, receipt):
            super().after(receipt)
            raise asyncio.CancelledError("current receipt finalizer")

    log = CancelAfter()
    previous = asyncio.CancelledError("previous request")
    mark_cancellation(previous)
    previous.__dict__["dafjev_workflow"] = {"observed_receipts": ["unrelated-previous-receipt"]}

    async def run():
        adapter = AsyncHTTPDecisionBackend if asynchronous else HTTPDecisionBackend
        backend = adapter(endpoint=stub.base_url + "/v1/fixture", model="fixture", observer=log)
        try:
            try:
                raise previous
            except asyncio.CancelledError:
                if asynchronous:
                    await backend.predict(_request())
                else:
                    backend.predict(_request())
        finally:
            if asynchronous:
                await backend.close()
            else:
                backend.close()

    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(run())
    current = original_cancellation(caught.value)
    assert current is not previous
    assert current.__context__ is previous
    assert cancellation_workflow(caught.value) is None
    assert len(stub.hits) == len(log.started) == len(log.receipts) == 1
    receipt = log.receipts[0]
    assert receipt.status_code == 200 and receipt.error is None
    assert receipt.response_diagnostics.body_complete
    assert receipt.request_hash == log.started[0][0]
    assert "unrelated-previous-receipt" not in json.dumps(receipt.to_dict())


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("raw,media,classification", [
    ("", "text/plain", "empty"),
    ("private-state-canary Authorization: Bearer secret-error-canary", "text/plain", "invalid_json"),
    ('{"usage":{"cost":100,"cost":0}}', "application/json", "invalid_json"),
    ('{"usage":{"cost":NaN}}', "application/json", "invalid_json"),
    ('{"secret":"private-state-canary",', "application/json", "invalid_json"),
    ('[{"error":"private-state-canary"}]', "application/json", "json_other"),
])
def test_http_failure_keeps_digest_status_not_provider_text(stub, asynchronous, raw, media, classification):
    stub.enqueue(404, text=raw, content_type=media,
                 headers={"x-typesafe-request-id": "request-safe-1", "x-secret": "header-secret-canary"})
    log = _Log()
    with pytest.raises((ValueError, BackendHTTPError)):
        _call(stub, asynchronous, log)
    assert len(stub.hits) == len(log.started) == len(log.receipts) == 1
    receipt = log.receipts[0]
    diag = receipt.response_diagnostics
    assert receipt.status_code == 404 and receipt.response_id == "request-safe-1"
    assert diag.body_bytes_observed == len(raw.encode())
    assert diag.body_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    assert diag.body_complete and diag.digest_scope == "complete_decoded_body"
    assert diag.media_type == media and diag.classification == classification
    exported = json.dumps(receipt.to_dict(), allow_nan=False)
    assert all(secret not in exported for secret in
               ("private-state-canary", "secret-error-canary", "header-secret-canary", "Authorization"))


@pytest.mark.parametrize("asynchronous", [False, True])
def test_response_identity_and_content_type_are_bounded_and_redacted(stub, asynchronous):
    stub.enqueue(503, body=_native(model="private-state-canary", provider="provider-" + "x" * 200,
                 id="secret?query=credential", error="do not publish private-instructions-canary"),
                 headers={"x-typesafe-request-id": "request-private-state-canary"})
    log = _Log()
    with pytest.raises(BackendHTTPError):
        _call(stub, asynchronous, log)
    receipt = log.receipts[0]
    assert receipt.resolved_model is receipt.provider is receipt.response_id is None
    assert "private-state-canary" not in json.dumps(receipt.to_dict())
    stub.enqueue(404, text="failure", content_type="application/private-media-secret; key=parameter-secret")
    with pytest.raises(ValueError):
        _call(stub, asynchronous, log)
    assert log.receipts[-1].response_diagnostics.media_type == "other"
    assert "private-media-secret" not in json.dumps(log.receipts[-1].to_dict())
    assert "parameter-secret" not in json.dumps(log.receipts[-1].to_dict())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_response_identifier_cannot_echo_private_object_key(stub, asynchronous):
    stub.enqueue(404, body={"id": "request-private-object-key-canary", "usage": {}})
    log = _Log()
    request = DecisionRequest({"private-object-key-canary": 7}, _request().questions, timeout=2)
    with pytest.raises(BackendHTTPError):
        _call(stub, asynchronous, log, request=request)
    assert log.receipts[0].response_id is None
    assert "private-object-key-canary" not in json.dumps(log.receipts[0].to_dict())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_oversized_body_stops_before_parsing_prefix_accounting(stub, asynchronous):
    raw = '{"usage":{"cost":0},"private":"' + "x" * MAX_RESPONSE_BODY_BYTES + '"}'
    stub.enqueue(200, text=raw, content_type="application/json")
    log = _Log()
    with pytest.raises(ValueError, match="response_body_limit_exceeded"):
        _call(stub, asynchronous, log)
    assert len(stub.hits) == len(log.receipts) == 1
    receipt = log.receipts[0]
    diag = receipt.response_diagnostics
    assert receipt.status_code == 200 and receipt.error == "body_limit_exceeded"
    assert MAX_RESPONSE_BODY_BYTES < diag.body_bytes_observed <= MAX_RESPONSE_BODY_BYTES + RESPONSE_CHUNK_BYTES
    assert not diag.body_complete and diag.digest_scope == "observed_decoded_prefix"
    assert diag.classification == "body_limit_exceeded"
    assert diag.body_sha256 == hashlib.sha256(raw.encode()[:diag.body_bytes_observed]).hexdigest()
    assert len(json.dumps(receipt.to_dict())) < 1500


class _RawServer:
    """Real byte/partial-response server; signals coordinate only owned fixtures."""
    def __init__(self, payload, *, headers=None, block_after=None):
        self.payload = payload
        self.headers = headers or {}
        self.block_after = block_after
        self.prefix_sent = threading.Event()
        self.release = threading.Event()
        self.hits = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                outer.hits.append(self.path)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(outer.payload)))
                    for key, value in outer.headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    cut = outer.block_after or len(outer.payload)
                    self.wfile.write(outer.payload[:cut])
                    self.wfile.flush()
                    outer.prefix_sent.set()
                    if outer.block_after:
                        outer.release.wait(5)
                        self.wfile.write(outer.payload[cut:])
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_compressed_response_cap_and_digest_use_decoded_bytes(asynchronous):
    raw = b" " * (MAX_RESPONSE_BODY_BYTES + 1)
    server = _RawServer(gzip.compress(raw), headers={"Content-Encoding": "gzip"})
    log = _Log()
    try:
        with pytest.raises(ValueError, match="response_body_limit_exceeded"):
            _call(server, asynchronous, log)
    finally:
        server.close()
    diag = log.receipts[0].response_diagnostics
    assert len(server.hits) == 1 and diag.body_bytes_observed == len(raw)
    assert diag.body_sha256 == hashlib.sha256(raw).hexdigest()
    assert not diag.body_complete and diag.classification == "body_limit_exceeded"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_complete_utf8_json_across_chunks_keeps_exact_digest_not_extra_payload(stub, asynchronous):
    raw = json.dumps(_native(private_metadata="λ" * RESPONSE_CHUNK_BYTES), ensure_ascii=False)
    stub.enqueue(200, text=raw, content_type="application/json; charset=utf-8")
    log = _Log()
    result = _call(stub, asynchronous, log)
    receipt = result.receipts[0]
    diag = receipt.response_diagnostics
    assert result.predictions["decision"].value == "a"
    assert len(stub.hits) == len(log.receipts) == 1
    assert diag.body_bytes_observed == len(raw.encode("utf-8"))
    assert diag.body_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert diag.body_complete and diag.classification == "json_object"
    assert diag.media_type == "application/json"
    assert "λ" not in json.dumps(receipt.to_dict(), ensure_ascii=False)


def _partial_payload():
    prefix = b'{"usage":{"cost":"0.12"},"private":"'
    return prefix + b"x" * (2 * RESPONSE_CHUNK_BYTES - len(prefix)) + b'"}'


def test_sync_body_timeout_keeps_known_status_and_partial_digest():
    raw = _partial_payload()
    server = _RawServer(raw, block_after=len(raw) - 2)
    log = _Log()
    try:
        with pytest.raises(httpx.ReadTimeout):
            _call(server, False, log, request=DecisionRequest(_request().state, _request().questions, timeout=.1))
    finally:
        server.close()
    receipt = log.receipts[0]
    diag = receipt.response_diagnostics
    assert len(server.hits) == len(log.started) == len(log.receipts) == 1
    assert receipt.status_code == 200 and receipt.error == "ReadTimeout"
    assert diag.classification == "incomplete" and not diag.body_complete
    assert diag.body_bytes_observed == len(raw) - 2
    assert diag.body_sha256 == hashlib.sha256(raw[:-2]).hexdigest()


@pytest.mark.parametrize("after_fails", [False, True])
@pytest.mark.parametrize("task_layers", [0, 2])
def test_async_cancel_after_headers_preserves_partial_receipt_and_original_cancel(after_fails, task_layers):
    raw = _partial_payload()
    server = _RawServer(raw, block_after=len(raw) - 2)
    class Finalizer(_Log):
        def after(self, receipt):
            super().after(receipt)
            if after_fails:
                raise ValueError("owned-observer-outcome-not-persisted")
    log = Finalizer()

    async def run():
        backend = AsyncHTTPDecisionBackend(endpoint=server.base_url + "/fixture", model="fixture", observer=log)
        try:
            async def predict(depth):
                if depth:
                    return await asyncio.create_task(predict(depth - 1))
                return await backend.predict(_request())
            task = asyncio.create_task(predict(task_layers))
            assert await asyncio.to_thread(server.prefix_sent.wait, 2)
            await asyncio.sleep(.05)  # the real reader is blocked on the final two bytes
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as canceled:
                await task
            if after_fails:
                original = original_cancellation(canceled.value)
                assert isinstance(original.__cause__, ValueError)
                assert str(original.__cause__) == "owned-observer-outcome-not-persisted"
            assert task.cancelled()
        finally:
            await backend.close()
    try:
        asyncio.run(run())
    finally:
        server.close()
    receipt = log.receipts[0]
    diag = receipt.response_diagnostics
    assert len(server.hits) == len(log.started) == len(log.receipts) == 1
    assert receipt.status_code == 200 and receipt.error == "CancelledError"
    assert diag.body_bytes_observed == len(raw) - 2 and not diag.body_complete
    assert diag.classification == "incomplete"
    assert diag.body_sha256 == hashlib.sha256(raw[:-2]).hexdigest()


@pytest.mark.parametrize("payload", [
    b'{"usage":{"cost":0,"cost":100}}',
    b'{"usage":{"cost":Infinity}}',
    b'{"usage":{"cost":true}}',
    b'{"usage":[]}',
    b'{"usage":{"cost":0},"pad":"' + b"x" * MAX_RESPONSE_BODY_BYTES + b'"}',
], ids=["duplicate-cost", "infinite-cost", "boolean-cost", "nonobject-usage", "oversized-body"])
def test_hosted_pure_receipt_never_infers_free_billing_from_untrusted_body(tmp_path, payload):
    # Hosted construction/reduction only; the destination is never requested.
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/alpha/decisions", model="fixture",
        hosted=True, api_key="public-unit-placeholder")
    try:
        body = backend._body(_request())
        store = RunStore.create(tmp_path.resolve() / "pure-accounting", {"fixture": True, "budget_usd": "25"})
        ledger = SpendLedger(store, limit="25")
        attempt = ledger.reserve("cell", content_hash(body), body["model"], backend.endpoint, True, "0.25")
        receipt = backend._receipt(attempt, body, time.perf_counter(), httpx.Response(404, content=payload))
        ledger.finish("cell", receipt)
    finally:
        backend.close()
    assert receipt.cost_status == "unknown" and receipt.cost_usd is None
    assert receipt.status_code == 404 and receipt.response_diagnostics is not None
    snapshot = ledger.snapshot()
    assert snapshot["reported_cost_usd"] == "0" and snapshot["reserved_usd"] == "0.25"
    assert snapshot["unresolved_attempts"] == [attempt] and snapshot["admission_stopped"]
    assert SpendLedger(RunStore(store.directory), limit="25").snapshot() == snapshot
    with pytest.raises(BudgetStopped):
        ledger.reserve("next", content_hash(body), body["model"], backend.endpoint, True, "0.25")


def test_valid_billing_is_independent_of_invalid_tokens_and_secret_response_identity():
    secret = "public-unit-secret-reflection"
    backend = HTTPDecisionBackend(endpoint="https://openrouter.ai/api/alpha/decisions", model="fixture",
        hosted=True, api_key=secret)
    try:
        body = backend._body(_request())
        response = httpx.Response(503, json={"id": secret, "model": "private-state-canary",
            "provider": "Bearer " + secret, "usage": {"cost": "0.123456789012345678",
                "input_tokens": True, "output_tokens": 7}})
        receipt = backend._receipt("pure-fixture", body, time.perf_counter(), response, "BackendHTTPError")
    finally:
        backend.close()
    assert receipt.cost_usd == "0.123456789012345678" and receipt.cost_status == "reported"
    assert receipt.input_tokens is None and receipt.output_tokens == 7
    assert receipt.resolved_model is receipt.provider is receipt.response_id is None
    assert secret not in json.dumps(receipt.to_dict())


def _probe_config(tmp_path, endpoint):
    save_dataset(make_synthetic_dataset("categorical", seed=13, n=6), tmp_path / "data.json")
    config = {"format": "dafjev.benchmark-run/1", "seed": 13, "budget_usd": "0", "sampling": "all",
        "execution_selection": {"phase": "quality"}, "timing_repetitions": 1, "timing_samples": 1,
        "capability_probes": True, "bootstrap_samples": 10, "timeout_s": 2,
        "datasets": [{"id": "owned-capability", "path": "data.json"}],
        "backends": [{"id": "owned-local", "kind": "http", "endpoint": endpoint, "model": "fixture"}]}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def test_failed_capability_probe_preserves_all_planned_quality_and_offline_diagnostics(tmp_path, stub):
    store = plan_run(_probe_config(tmp_path, stub.base_url + "/v1/fixture"), tmp_path / "runs")
    stub.enqueue(404, text="private-provider-error-canary")
    report = execute_run(store.directory)
    assert len(stub.hits) == 1
    assert report["denominators"] == {"failed": 1, "unsupported": len(store.manifest["cells"]) - 1}
    assert all(c["status"] == "unsupported" for c in report["cells"] if c["phase"] == "quality")
    receipt = next(e["receipt"] for e in store.events() if e["event"] == "attempt_finished")
    assert receipt["status_code"] == 404 and receipt["response_diagnostics"]["classification"] == "invalid_json"
    assert "private-provider-error-canary" not in json.dumps(report)
    assert report_run(store.directory)["denominators"] == report["denominators"]
    assert len(stub.hits) == 1


def test_transient_probe_retry_has_two_separate_digests_before_quality(tmp_path, stub):
    store = plan_run(_probe_config(tmp_path, stub.base_url + "/v1/fixture"), tmp_path / "runs")
    stub.enqueue(503, body={"error": "private-error-canary", "usage": {}})
    answer = {"model": "fixture", "answers": {"decision": {"type": "choice", "choice": "billing",
        "probabilities": {"billing": .6, "account": .2, "technical": .2}, "confidence": .6}}, "usage": {}}
    for _ in store.manifest["cells"]:
        stub.enqueue(body=answer)
    report = execute_run(store.directory)
    receipts = [e["receipt"] for e in store.events() if e["event"] == "attempt_finished"]
    assert report["status"] == "complete" and len(stub.hits) == len(store.manifest["cells"]) + 1
    assert receipts[0]["attempt_id"] != receipts[1]["attempt_id"]
    assert receipts[0]["status_code"] == 503 and receipts[1]["status_code"] == 200
    assert receipts[0]["response_diagnostics"]["body_sha256"] != receipts[1]["response_diagnostics"]["body_sha256"]
    assert "private-error-canary" not in json.dumps(report)
