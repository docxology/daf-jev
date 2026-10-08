from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from daf_jev.benchmark_graphical import (
    GraphicalExperimentError,
    acquire_evidence,
    reference_graph,
    run_graphical_experiment,
)
from daf_jev.benchmark_store import BudgetStopped, RunStore, SpendLedger
from daf_jev.decision_backends import (
    AsyncHTTPDecisionBackend,
    BackendCapabilities,
    CallReceipt,
    DecisionPrediction,
    DecisionRequest,
    DecisionResult,
)


class ReferenceOracleBackend:
    """Independent deterministic test provider implementing the public protocol."""
    capabilities = BackendCapabilities(probability_source="analytical_test_oracle")
    model = "disclosed-reference-oracle"

    def __init__(self, defect: str | None = None) -> None:
        self.requests: list[DecisionRequest] = []
        self.closed = False
        self.defect = defect

    async def predict(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        net = reference_graph()
        predictions = {}
        for qid, question in request.questions.items():
            if qid.startswith("cpt::"):
                child, *facts = qid.removeprefix("cpt::").split("|")
                assignment = tuple(fact.split("=", 1)[1] for fact in facts if fact)
                row = dict(net.cpts[child].table)[assignment]
                probabilities = dict(zip(net.variable(child).states, row, strict=True))
            elif qid.startswith("reask::"):
                key = qid.removeprefix("reask::")
                probabilities = dict(zip(net.variable(key).states, net.posterior(request.state["evidence"])[key], strict=True))
            else:
                pair = qid.removeprefix("edge::")
                expected = pair if pair in ("cloudy->rain", "rain->wet") else "no-edge"
                probabilities = {key: .98 if key == expected else .01 for key in question.to_wire()["criteria"]}
            label = max(probabilities, key=probabilities.__getitem__)
            prediction = DecisionPrediction("choice", label, probabilities, .8,
                                            "analytical_test_oracle", "test_provider")
            if self.defect == "missing":
                prediction = replace(prediction, probabilities=None)
            elif self.defect == "vocabulary":
                prediction = replace(prediction, probabilities={"unrequested": 1.0})
            elif self.defect == "mass":
                prediction = replace(prediction, probabilities={key: value * .9999 for key, value in probabilities.items()},
                                     probability_rounding_digits=4)
            elif self.defect == "confidence":
                prediction = replace(prediction, confidence=None)
            elif self.defect == "wrong_type":
                prediction = replace(prediction, type="score")
            predictions[qid] = prediction
        receipt = CallReceipt(f"attempt-{len(self.requests)}", "2026-10-07T00:00:00Z",
            "test://analytical-oracle", self.model, self.model, None, f"response-{len(self.requests)}",
            "0" * 64, .01, 200, 10, 10, None, "local")
        if self.defect == "ids":
            predictions.pop(next(iter(predictions)))
        return DecisionResult(predictions, (receipt,))

    async def close(self) -> None:
        self.closed = True


def test_reconstructs_disclosed_factors_and_preserves_caller_lifecycle() -> None:
    backend = ReferenceOracleBackend()
    result = asyncio.run(run_graphical_experiment(backend, seed=41))
    assert result["status"] == "complete"
    assert result["cpt_soft_brier_mean"] == 0
    assert len(result["cpt_rows"]) == 5
    assert len(backend.requests) == 4
    assert [len(request.questions) for request in backend.requests] == [5, 3, 1, 1]
    assert not backend.closed
    assert result["proposed_edges"] == [{"parent": "cloudy", "child": "rain"}, {"parent": "rain", "child": "wet"}]
    assert result["acquisition"]["additional_model_calls"] == 2
    assert result["acquisition"]["observation_cost_units"] == 3
    assert len(result["calls"]) == 4
    assert result["model_reask_soft_brier_mean"] == 0
    assert [len(request.state["evidence"]) for request in backend.requests[2:]] == [1, 2]
    assert backend.requests[0].state["reference_graph"] == reference_graph().to_json()
    assert backend.requests[0].state["hidden_assignment_disclosed"] is False
    assert "oracle" not in backend.requests[0].state
    json.dumps(result, allow_nan=False)


def test_reasking_conditions_other_variables_not_only_observed_row() -> None:
    result = acquire_evidence(reference_graph(), {"cloudy": "true", "rain": "true", "wet": "true"}, max_reveals=2,
                              observation_costs={"cloudy": 2, "rain": 3, "wet": 4})
    first = result["trajectory"][1]
    assert first["revealed"]["variable"] == "cloudy"
    assert first["posteriors"]["cloudy"] == (0, 1)
    assert first["posteriors"]["rain"] == pytest.approx((.2, .8))
    assert first["posteriors"]["wet"] == pytest.approx((.26, .74))
    assert result["trajectory"][2]["revealed"]["variable"] == "wet"
    assert result["observation_cost_units"] == 6
    assert result["revealed_assignment"] == {"cloudy": "true", "wet": "true"}


@pytest.mark.parametrize("defect", ["missing", "vocabulary", "mass", "confidence", "wrong_type", "ids"])
def test_rejects_unusable_beliefs_without_repair_and_retains_receipt(defect: str) -> None:
    backend = ReferenceOracleBackend(defect)
    with pytest.raises(GraphicalExperimentError) as exc:
        asyncio.run(run_graphical_experiment(backend))
    record = exc.value.record
    assert record["status"] == "failed"
    assert record["phase"] == "elicit_cpts"
    assert record["calls"][0]["receipts"][0]["response_id"] == "response-1"
    assert len(backend.requests) == 1
    assert not backend.closed


@pytest.mark.parametrize("kwargs", [
    {"seed": True}, {"timeout": 0}, {"timeout": float("nan")}, {"max_reveals": 4},
    {"max_reveals": True}, {"observation_costs": {}},
    {"observation_costs": {"cloudy": 1, "rain": -1, "wet": 1}},
])
def test_invalid_local_protocol_rejected_before_model_calls(kwargs: dict) -> None:
    backend = ReferenceOracleBackend()
    with pytest.raises(ValueError):
        asyncio.run(run_graphical_experiment(backend, **kwargs))
    assert backend.requests == []


def test_zero_reveals_and_deterministic_seed() -> None:
    first = asyncio.run(run_graphical_experiment(ReferenceOracleBackend(), seed=91, max_reveals=0))
    second = asyncio.run(run_graphical_experiment(ReferenceOracleBackend(), seed=91, max_reveals=0))
    assert first["acquisition"] == second["acquisition"]
    assert first["acquisition"]["revealed_assignment"] == {}
    assert len(first["acquisition"]["trajectory"]) == 1


def test_invalid_oracle_rejected() -> None:
    with pytest.raises(ValueError, match="cover exactly"):
        acquire_evidence(reference_graph(), {})
    with pytest.raises(ValueError, match="unknown state"):
        acquire_evidence(reference_graph(), {"cloudy": "other", "rain": "true", "wet": "true"})


def test_cancellation_propagates_without_closing_backend() -> None:
    class CancelledBackend(ReferenceOracleBackend):
        async def predict(self, request: DecisionRequest) -> DecisionResult:
            raise asyncio.CancelledError

    backend = CancelledBackend()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_graphical_experiment(backend))
    assert not backend.closed


def test_real_http_reasks_preserve_observer_receipts_and_unknown_usage(stub) -> None:
    class Observer:
        def __init__(self) -> None:
            self.intents = []
            self.receipts = []

        def before(self, request_hash, model, endpoint):
            self.intents.append((request_hash, model, endpoint))
            return f"observed-{len(self.intents)}"

        def after(self, receipt):
            self.receipts.append(receipt)

    async def run():
        oracle = ReferenceOracleBackend()
        await run_graphical_experiment(oracle, seed=41)
        for request in list(oracle.requests):
            result = await ReferenceOracleBackend().predict(request)
            stub.enqueue(body={"model": "loopback-oracle", "usage": {}, "answers": {
                key: {"type": "choice", "choice": prediction.value,
                      "probabilities": prediction.probabilities, "confidence": prediction.confidence}
                for key, prediction in result.predictions.items()}})
        observer = Observer()
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="loopback-oracle",
            capabilities=BackendCapabilities(probability_rounding_digits=None))
        try:
            result = await run_graphical_experiment(backend, seed=41, observer=observer, timeout=2)
            assert len(stub.hits) == len(observer.intents) == len(observer.receipts) == 4
            assert result["model_reask_soft_brier_mean"] == 0
            assert all(receipt.input_tokens is None and receipt.output_tokens is None for receipt in observer.receipts)
            assert all(call["receipts"][0]["input_tokens"] is None for call in result["calls"])
            assert [call["receipts"][0]["attempt_id"] for call in result["calls"]] == [f"observed-{i}" for i in range(1, 5)]
        finally:
            await backend.close()
    asyncio.run(run())


def test_disabling_model_reasks_keeps_pure_coupled_control() -> None:
    backend = ReferenceOracleBackend()
    result = asyncio.run(run_graphical_experiment(backend, model_reask=False))
    assert len(backend.requests) == 2
    assert result["model_reasks"] == []
    assert result["model_reask_soft_brier_mean"] is None
    assert result["acquisition"]["additional_model_calls"] == 0


@pytest.mark.parametrize("digits,accepted", [(4, True), (None, False), (3, False)])
def test_non_cpt_rows_use_only_the_declared_matching_precision(digits, accepted) -> None:
    class RoundedBackend(ReferenceOracleBackend):
        async def predict(self, request: DecisionRequest) -> DecisionResult:
            result = await super().predict(request)
            predictions = dict(result.predictions)
            for key, prediction in predictions.items():
                if key.startswith("cpt::"):
                    continue
                probabilities = dict(prediction.probabilities)
                if key.startswith("edge::"):
                    smallest = min(probabilities, key=probabilities.__getitem__)
                    probabilities[smallest] -= .0001
                else:
                    probabilities = dict(zip(probabilities, (.3333, .6666), strict=True))
                predictions[key] = replace(prediction, probabilities=probabilities,
                                            probability_rounding_digits=digits)
            return replace(result, predictions=predictions)

    if accepted:
        result = asyncio.run(run_graphical_experiment(RoundedBackend()))
        assert result["status"] == "complete"
        assert result["cpt_soft_brier_mean"] == 0
        assert result["model_reasks"][0]["prediction"] == (.3333, .6666)
        assert sum(result["model_reasks"][0]["prediction"]) == pytest.approx(.9999)
    else:
        with pytest.raises(GraphicalExperimentError) as exc:
            asyncio.run(run_graphical_experiment(RoundedBackend()))
        assert exc.value.record["phase"] == "propose_structure"
        assert len(exc.value.record["calls"]) == 2


def _cpt_http_response() -> dict:
    rows = {"cpt::cloudy|": (.5, .5), "cpt::rain|cloudy=false": (.8, .2),
            "cpt::rain|cloudy=true": (.2, .8), "cpt::wet|rain=false": (.9, .1),
            "cpt::wet|rain=true": (.1, .9)}
    return {"model": "loopback-reference", "usage": {}, "answers": {
        key: {"type": "choice", "choice": "false" if probabilities[0] >= probabilities[1] else "true",
              "probabilities": dict(zip(("false", "true"), probabilities, strict=True)), "confidence": .8}
        for key, probabilities in rows.items()}}


def test_real_ledger_initial_budget_rejection_is_unattempted(stub, tmp_path) -> None:
    async def run():
        store = RunStore.create(tmp_path.resolve(), {"fixture": "initial-graph-admission"})
        ledger = SpendLedger(store, limit="0")
        # The real USD ledger refuses before transport; no hosted request occurs.
        observer = ledger.observer(cell_id="graph", hosted=True, liability_usd="1")
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="loopback-reference")
        try:
            with pytest.raises(BudgetStopped):
                await run_graphical_experiment(backend, observer=observer)
            assert stub.hits == []
            assert store.events() == []
            assert ledger.snapshot()["unresolved_attempts"] == []
        finally:
            await backend.close()
    asyncio.run(run())


def test_real_ledger_budget_stop_after_local_phase_retains_partial_evidence(stub, tmp_path) -> None:
    async def run():
        store = RunStore.create(tmp_path.resolve(), {"fixture": "partial-graph-admission"})
        ledger = SpendLedger(store, limit="0")
        local = ledger.observer(cell_id="graph", hosted=False, liability_usd="0")

        class OnePhaseBudget:
            def before(self, request_hash, model, endpoint):
                if ledger.admissions:
                    raise BudgetStopped("one local phase admitted by the fixture protocol")
                return local.before(request_hash, model, endpoint)

            def after(self, receipt):
                local.after(receipt)

        stub.enqueue(body=_cpt_http_response())
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="loopback-reference")
        try:
            with pytest.raises(GraphicalExperimentError) as exc:
                await run_graphical_experiment(backend, observer=OnePhaseBudget())
            record = exc.value.record
            assert record["phase"] == "propose_structure"
            assert record["error_type"] == "BudgetStopped"
            assert len(stub.hits) == len(record["calls"]) == len(record["observed_receipts"]) == 1
            assert len(record["attempt_ids"]) == 1
            assert [row["event"] for row in store.events()] == ["attempt_started", "attempt_finished"]
            assert store.events()[1]["receipt"] == record["observed_receipts"][0]
            assert ledger.snapshot()["unresolved_attempts"] == []
            assert record["calls"][0]["validated_predictions"]["cpt::cloudy|"]["probabilities"] == {"false": .5, "true": .5}
        finally:
            await backend.close()
    asyncio.run(run())


def test_after_receipt_budget_stop_does_not_misclassify_first_transport_as_unattempted(stub, tmp_path) -> None:
    async def run():
        store = RunStore.create(tmp_path.resolve(), {"fixture": "graph-post-transport-budget"})
        ledger = SpendLedger(store, limit="0")
        local = ledger.observer(cell_id="graph", hosted=False, liability_usd="0")

        class StopAfterRecordedReceipt:
            def before(self, request_hash, model, endpoint):
                return local.before(request_hash, model, endpoint)

            def after(self, receipt):
                local.after(receipt)
                raise BudgetStopped("fixture admission stops after this retained receipt")

        stub.enqueue(body=_cpt_http_response())
        backend = AsyncHTTPDecisionBackend(endpoint=stub.base_url + "/v1/systemone", model="loopback-reference")
        try:
            with pytest.raises(GraphicalExperimentError) as exc:
                await run_graphical_experiment(backend, observer=StopAfterRecordedReceipt())
            record = exc.value.record
            assert record["phase"] == "elicit_cpts"
            assert record["error_type"] == "BudgetStopped"
            assert record["calls"] == []  # predict could not return after its observer raised
            assert len(stub.hits) == len(record["observed_receipts"]) == len(record["attempt_ids"]) == 1
            assert [row["event"] for row in store.events()] == ["attempt_started", "attempt_finished"]
            assert store.events()[1]["receipt"] == record["observed_receipts"][0]
            json.dumps(record, allow_nan=False)
        finally:
            await backend.close()
    asyncio.run(run())


def test_graphical_factors_declare_surrogate_scope_and_preserve_unknown_probability_meaning():
    result = asyncio.run(run_graphical_experiment(ReferenceOracleBackend(), max_reveals=0))
    assert result["probability_semantics"] is None
    assert result["factor_interpretation"] == "normalized_surrogate_factor_under_disclosed_reference_protocol"
    assert "does not attest" in result["factor_semantics_limit"]
    assert all(prediction["probability_semantics"] is None
               for call in result["calls"] for prediction in call["validated_predictions"].values())
