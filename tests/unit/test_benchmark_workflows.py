"""Executed cascade paths through actual loopback HTTP clients."""

import asyncio

import pytest

from daf_jev import choice
from daf_jev._cancellation import cancellation_workflow, original_cancellation
from daf_jev.benchmark_policies import GateCalibration, wilson_upper
from daf_jev.benchmark_store import BudgetStopped
from daf_jev.benchmark_workflows import CascadeDecisionBackend, gate_from_dict
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendHTTPError,
    DecisionRequest,
)


class Observer:
    def __init__(self, *, refuse=False):
        self.refuse = refuse
        self.intents = []
        self.receipts = []

    def before(self, request_hash, model, endpoint):
        if self.refuse:
            raise BudgetStopped("public test admission refused")
        self.intents.append((request_hash, model, endpoint))
        return f"{model}-{len(self.intents)}"

    def after(self, receipt):
        self.receipts.append(receipt)


def _response(value, confidence):
    answer = {"type": "choice", "choice": value, "probabilities": {"a": .1, "b": .9}}
    if confidence is not None:
        answer["confidence"] = confidence
    return {"model": "fixture", "answers": {"decision": answer}, "usage": {}}


def _gate(admitted=True):
    return GateCalibration("admitted" if admitted else "insufficient_evidence", .8 if admitted else None,
                           .05, wilson_upper(0, 80) if admitted else None, 80 if admitted else 0, 0, 80)


def _request():
    return DecisionRequest("public fixture", {"decision": choice("Choose.", {"a": "first", "b": "second"})}, timeout=2)


def test_accepted_weak_avoids_strong_transport_and_preserves_caller_ownership(stub):
    async def run():
        weak = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/weak", model="weak")
        strong = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/strong", model="strong")
        logs = {"weak": Observer(), "strong": Observer()}
        cascade = CascadeDecisionBackend(weak, strong, gate=_gate(), observers=logs.get)
        try:
            stub.enqueue(body=_response("a", .9))
            result = await cascade.predict(_request())
            assert result.predictions["decision"].value == "a"
            assert result.workflow["strong_invoked"] is False
            assert [hit["path"] for hit in stub.hits] == ["/weak"]
            assert len(logs["weak"].receipts) == 1 and logs["strong"].intents == []
            await cascade.close()
            stub.enqueue(body=_response("b", .9))
            assert (await strong.predict(_request())).predictions["decision"].value == "b"
        finally:
            await weak.close()
            await strong.close()
    asyncio.run(run())


@pytest.mark.parametrize("confidence,admitted", [(None, True), (.7, True), (.99, False)])
def test_missing_low_or_unadmitted_confidence_executes_strong_and_retains_both_receipts(stub, confidence, admitted):
    async def run():
        weak = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/weak", model="weak",
                                       mode="chat" if confidence is None else "systemone")
        strong = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/strong", model="strong")
        logs = {"weak": Observer(), "strong": Observer()}
        cascade = CascadeDecisionBackend(weak, strong, gate=_gate(admitted), observers=logs.get)
        try:
            stub.enqueue(body={"choices": [{"message": {"content": '{"answers":{"decision":{"value":"a"}}}'}}]}
                         if confidence is None else _response("a", confidence))
            stub.enqueue(body=_response("b", .9))
            result = await cascade.predict(_request())
            assert result.predictions["decision"].value == "b"
            assert result.predictions["decision"].probability_source == "native"
            assert result.workflow["selected_model"] == "strong"
            assert result.workflow["strong_invoked"] is True
            assert [hit["path"] for hit in stub.hits] == ["/weak", "/strong"]
            assert len(result.receipts) == 2
            assert len(logs["weak"].receipts) == len(logs["strong"].receipts) == 1
        finally:
            await weak.close()
            await strong.close()
    asyncio.run(run())


def test_weak_http_failure_falls_back_with_failed_attempt_evidence(stub):
    async def run():
        weak = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/weak", model="weak")
        strong = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/strong", model="strong")
        logs = {"weak": Observer(), "strong": Observer()}
        cascade = CascadeDecisionBackend(weak, strong, gate=_gate(), observers=logs.get)
        try:
            stub.enqueue(503, body={"error": "public failure"})
            stub.enqueue(body=_response("b", .9))
            result = await cascade.predict(_request())
            assert result.workflow["reason"] == "weak_failure:BackendHTTPError"
            assert logs["weak"].receipts[0].status_code == 503
            assert logs["weak"].receipts[0].error is not None
            assert [r.status_code for r in result.receipts] == [503, 200]
            assert len(stub.hits) == 2
            stub.enqueue(body=_response("a", None))
            stub.enqueue(401, body={"error": "public failure"})
            with pytest.raises(BackendHTTPError) as error:
                await cascade.predict(_request())
            assert error.value.status_code == 401
            assert len(logs["strong"].receipts) == 2
        finally:
            await weak.close()
            await strong.close()
    asyncio.run(run())


@pytest.mark.parametrize("refusing_child", ["weak", "strong"])
@pytest.mark.parametrize("confidence", [None, .7])
def test_child_budget_refusal_is_not_hidden_by_fallback(stub, refusing_child, confidence):
    async def run():
        weak = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/weak", model="weak")
        strong = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/strong", model="strong")
        logs = {name: Observer(refuse=name == refusing_child) for name in ("weak", "strong")}
        cascade = CascadeDecisionBackend(weak, strong, gate=_gate(), observers=logs.get)
        try:
            stub.enqueue(body=_response("a", confidence))
            with pytest.raises(BudgetStopped) as error:
                await cascade.predict(_request())
            assert len(stub.hits) == (0 if refusing_child == "weak" else 1)
            assert logs["strong"].receipts == []
            if refusing_child == "strong":
                record = error.value.dafjev_workflow
                assert record["weak_status"] == ("failed" if confidence is None else "completed")
                assert record["strong_status"] == "unattempted"
                assert len(record["observed_receipts"]) == len(record["attempt_ids"]["weak"]) == 1
                assert record["observed_receipts"][0] == logs["weak"].receipts[0].to_dict()
            else:
                assert not hasattr(error.value, "dafjev_workflow")
        finally:
            await weak.close()
            await strong.close()
    asyncio.run(run())


def test_gate_evidence_roundtrip_keeps_frozen_validation_statistics():
    gate = _gate()
    assert gate_from_dict(gate.to_dict()) == gate


@pytest.mark.parametrize("child", ["weak", "strong"])
@pytest.mark.parametrize("task_layers", [0, 2])
def test_original_cancellation_retains_partial_child_status_and_receipts(stub, child, task_layers):
    async def run():
        weak = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/weak", model="weak")
        strong = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/strong", model="strong")
        logs = {name: Observer() for name in ("weak", "strong")}
        cascade = CascadeDecisionBackend(weak, strong, gate=_gate(False), observers=logs.get)
        try:
            stub.enqueue(body=_response("a", .6), delay=1 if child == "weak" else 0)
            if child == "strong":
                stub.enqueue(body=_response("b", .9), delay=1)
            async def predict(depth):
                if depth:
                    return await asyncio.create_task(predict(depth - 1))
                return await cascade.predict(_request())
            task = asyncio.create_task(predict(task_layers))
            async def wait_for_hit():
                while len(stub.hits) < (1 if child == "weak" else 2):
                    await asyncio.sleep(.005)
            await asyncio.wait_for(wait_for_hit(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as error:
                await task
            record = cancellation_workflow(error.value)
            assert record is not None and task.cancelled()
            assert original_cancellation(error.value).dafjev_workflow == record
            assert record["failed_phase"] == child
            assert record["weak_status"] == ("unresolved" if child == "weak" else "completed")
            assert record["strong_status"] == ("unattempted" if child == "weak" else "unresolved")
            assert record["observed_receipts"][-1]["error"] == "CancelledError"
            assert record["observed_receipts"] == [r.to_dict() for name in ("weak", "strong") for r in logs[name].receipts]
            assert len(stub.hits) == len(record["observed_receipts"])
        finally:
            await weak.close()
            await strong.close()
    asyncio.run(run())
