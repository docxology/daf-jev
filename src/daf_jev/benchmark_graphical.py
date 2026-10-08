"""Bounded, injected-model graphical experiment with an analytical reference.

The prompt discloses the generative graph and its probabilities. This measures
factor reconstruction and evidence propagation, not undisclosed causal discovery.
Only the injected backend performs model I/O; its lifecycle belongs to the caller.
"""
from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from daf_jev._cancellation import mark_cancellation
from daf_jev._types import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    Question,
    validate_probability_row,
)
from daf_jev.benchmark_store import BudgetStopped
from daf_jev.decision_backends import (
    AsyncDecisionBackend,
    AttemptObserver,
    CallReceipt,
    DecisionRequest,
    content_hash,
)
from daf_jev.graphical import CPT, BayesNet, Edge, Variable
from daf_jev.graphical_elicitation import elicit_cpts_async, propose_structure_async
from daf_jev.primitives import choice
from daf_jev.reask import entropy_bits


def reference_graph() -> BayesNet:
    """Fresh immutable three-node reference, with strictly positive CPT rows."""
    variables = (
        Variable("cloudy", "The sky is cloudy", ("false", "true")),
        Variable("rain", "It rains", ("false", "true")),
        Variable("wet", "The ground is wet", ("false", "true")),
    )
    net = BayesNet(variables, (Edge("cloudy", "rain"), Edge("rain", "wet")), {
        "cloudy": CPT("cloudy", (), (((), (.5, .5)),)),
        "rain": CPT("rain", ("cloudy",), ((("false",), (.8, .2)), (("true",), (.2, .8)))),
        "wet": CPT("wet", ("rain",), ((("false",), (.9, .1)), (("true",), (.1, .9)))),
    })
    net.validate()
    return net


def _costs(net: BayesNet, costs: Mapping[str, float] | None) -> dict[str, float]:
    result = dict.fromkeys((v.key for v in net.variables), 1.0) if costs is None else dict(costs)
    if set(result) != {v.key for v in net.variables}:
        raise ValueError("observation costs must cover exactly the graph variables")
    for value in result.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("observation costs must be finite nonnegative numbers")
    return result


def acquire_evidence(
    net: BayesNet, oracle: Mapping[str, str], *, max_reveals: int = 3,
    observation_costs: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Reveal an oracle assignment by current entropy, conditioning the full net.

    Oracle observations have fixed synthetic cost units, not provider charges.
    Ties follow variable declaration order. There are no additional model calls.
    """
    net.validate()
    if isinstance(max_reveals, bool) or not isinstance(max_reveals, int) or not 0 <= max_reveals <= 3:
        raise ValueError("max_reveals must be an integer in [0, 3]")
    if set(oracle) != {v.key for v in net.variables}:
        raise ValueError("oracle must cover exactly the graph variables")
    if any(oracle[v.key] not in v.states for v in net.variables):
        raise ValueError("oracle contains an unknown state")
    costs = _costs(net, observation_costs)
    evidence: dict[str, str] = {}
    trajectory: list[dict[str, Any]] = []
    total_cost = 0.0
    posterior = net.posterior(evidence)
    trajectory.append({"step": 0, "evidence": {}, "posteriors": posterior,
                       "revealed": None, "observation_cost_units": total_cost})
    for step in range(1, min(max_reveals, len(net.variables)) + 1):
        remaining = [v for v in net.variables if v.key not in evidence]
        entropies = {v.key: entropy_bits(dict(zip(v.states, posterior[v.key], strict=True))) for v in remaining}
        selected = max(remaining, key=lambda v: entropies[v.key])
        evidence[selected.key] = oracle[selected.key]
        total_cost += costs[selected.key]
        posterior = net.posterior(evidence)
        trajectory.append({"step": step, "evidence": dict(evidence), "posteriors": posterior,
                           "revealed": {"variable": selected.key, "state": oracle[selected.key],
                                        "prior_entropy_bits": entropies[selected.key]},
                           "observation_cost_units": total_cost})
    return {"policy": "max_current_entropy_coupled_posterior", "max_reveals": max_reveals,
            "revealed_assignment": evidence, "trajectory": trajectory,
            "observation_costs": costs, "observation_cost_units": total_cost,
            "cost_semantics": "fixed synthetic observation units; not USD or model inference",
            "additional_model_calls": 0}


class GraphicalExperimentError(ValueError):
    """Failed experiment with retained model receipts and completed phase evidence."""
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        super().__init__(f"graphical experiment failed in {record['phase']}: {record['error_type']}")


@dataclass(frozen=True)
class _FactorResponse:
    """Only beliefs needed by factor assembly; does not invent usage fields."""
    answers: dict[str, Answer]


class _BackendClient:
    def __init__(self, backend: AsyncDecisionBackend, observer: AttemptObserver | None, timeout: float) -> None:
        self.backend, self.observer, self.timeout = backend, observer, timeout
        self.calls: list[dict[str, Any]] = []
        self.intents: list[str] = []
        self.observed_receipts: list[CallReceipt] = []

    def before(self, request_hash: str, model: str, endpoint: str) -> str:
        import uuid
        delegated = self.observer or getattr(self.backend, "observer", None)
        attempt = delegated.before(request_hash, model, endpoint) if delegated else str(uuid.uuid4())
        self.intents.append(attempt)
        return attempt

    def after(self, receipt: CallReceipt) -> None:
        self.observed_receipts.append(receipt)
        delegated = self.observer or getattr(self.backend, "observer", None)
        if delegated:
            delegated.after(receipt)

    async def ask(self, state: Any, questions: Mapping[str, Question]) -> _FactorResponse:
        result = await self.backend.predict(DecisionRequest(state, questions, timeout=self.timeout, observer=self))
        self.calls.append({"questions": {key: q.to_wire() for key, q in questions.items()},
                           "receipts": [receipt.to_dict() for receipt in result.receipts]})
        if set(result.predictions) != set(questions):
            raise ValueError("graphical answers must cover exactly the requested question IDs")
        answers: dict[str, Answer] = {}
        for key, question in questions.items():
            prediction = result.predictions[key]
            if not isinstance(question, ChoiceQuestion) or prediction.type != "choice":
                raise ValueError("graphical elicitation requires choice predictions")
            probabilities = prediction.probabilities
            if probabilities is None or prediction.probability_source is None:
                raise ValueError("graphical elicitation requires genuine choice probabilities")
            if set(probabilities) != set(question.criteria) or prediction.value not in question.criteria:
                raise ValueError("graphical probabilities must preserve the complete requested vocabulary")
            # CPT mass remains strict even if native transport rows are rounded.
            validate_probability_row(probabilities, context=f"graphical probabilities {key}",
                rounding_digits=None if key.startswith("cpt::") else prediction.probability_rounding_digits)
            confidence = prediction.confidence
            if confidence is None or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("ChoiceAnswer requires an actual finite confidence in [0, 1]")
            answers[key] = ChoiceAnswer(str(prediction.value), dict(probabilities), confidence)
        self.calls[-1]["validated_predictions"] = {key: asdict(p) for key, p in result.predictions.items()}
        return _FactorResponse(answers)


async def run_graphical_experiment(
    backend: AsyncDecisionBackend, *, seed: int = 20261007, max_reveals: int = 3,
    observation_costs: Mapping[str, float] | None = None,
    observer: AttemptObserver | None = None, timeout: float = 60.0,
    model_reask: bool = True,
) -> dict[str, Any]:
    """Elicit known factors, propose edges, and execute coupled oracle re-asking.

    No backend is created or closed. Per-request observers preserve caller-owned
    admission/accounting. Cancellation propagates; observer receipts remain in
    the caller's durable store. Other failures carry partial evidence in
    ``GraphicalExperimentError.record``.
    """
    reference = reference_graph()
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if not isinstance(model_reask, bool):
        raise ValueError("model_reask must be a boolean")
    # Complete local validation before any model call.
    oracle = reference.sample(1, random.Random(seed))[0]
    acquire_evidence(reference, oracle, max_reveals=max_reveals, observation_costs=observation_costs)
    graph = reference.to_json()
    state = {"task": "Reconstruct this disclosed generative Bayesian network; use the declared probabilities.",
             "reference_graph": graph, "hidden_assignment_disclosed": False}
    record: dict[str, Any] = {"format": "dafjev.graphical-experiment/1", "status": "running",
        "reference_graph": graph, "reference_sha256": content_hash(graph), "seed": seed,
        "target_source": "analytical disclosed generative CPTs; independent seeded reference sample for observations",
        "evidence_scope": "factor reconstruction and coupled synthetic observation policy; not causal discovery or real-world accuracy",
        "backend_model": backend.model,
        "probability_semantics": backend.capabilities.probability_semantics,
        "factor_interpretation": "normalized_surrogate_factor_under_disclosed_reference_protocol",
        "factor_semantics_limit": "Surrogate graph inference is conditional on supplied factors; native provenance does not attest calibrated probabilities, posterior meaning or CPT truth.", "protocol": {"max_questions_per_request": 32, "exact_limit": 8,
            "edge_penalty": 1.0, "max_reveals": max_reveals, "timeout": timeout,
            "model_reask": model_reask}, "phase": "elicit_cpts"}
    client = _BackendClient(backend, observer, timeout)
    started = time.perf_counter()
    try:
        elicited = await elicit_cpts_async(reference.variables, reference.edges, client=client,
            max_questions_per_request=32, state=state)
        record["elicited_graph"] = elicited.to_json()
        rows: list[dict[str, Any]] = []
        for variable in reference.variables:
            actual = dict(elicited.cpts[variable.key].table)
            for assignment, truth in reference.cpts[variable.key].table:
                predicted = actual[assignment]
                rows.append({"child": variable.key, "parents": reference.cpts[variable.key].parents,
                             "assignment": assignment, "target": truth, "prediction": predicted,
                             "soft_brier": math.fsum((p - t) ** 2 for p, t in zip(predicted, truth, strict=True))})
        record["cpt_rows"] = rows
        record["cpt_soft_brier_mean"] = math.fsum(row["soft_brier"] for row in rows) / len(rows)
        record["phase"] = "propose_structure"
        proposal = await propose_structure_async(reference.variables, client=client, state=state,
            exact_limit=8, edge_penalty=1.0)
        record["proposed_edges"] = [{"parent": edge.parent, "child": edge.child} for edge in proposal.edges]
        record["phase"] = "coupled_evidence_acquisition"
        acquisition = acquire_evidence(elicited, oracle, max_reveals=max_reveals, observation_costs=observation_costs)
        record["acquisition"] = acquisition
        record["model_reasks"] = []
        for entry in acquisition["trajectory"]:
            entry["reference_posteriors"] = reference.posterior(entry["evidence"])
            remaining = [v for v in reference.variables if v.key not in entry["evidence"]]
            if not model_reask or entry["step"] == 0 or not remaining:
                continue
            query = max(remaining, key=lambda v: entropy_bits(
                dict(zip(v.states, entry["posteriors"][v.key], strict=True))))
            record["phase"] = "model_posterior_reask"
            qid = f"reask::{query.key}"
            reask_state = {**state, "evidence": dict(entry["evidence"])}
            response = await client.ask(reask_state, {qid: choice(
                f"Given only the observed evidence in state, what is the posterior distribution over {query.key}?",
                dict.fromkeys(query.states))})
            answer = response.answers[qid]
            assert isinstance(answer, ChoiceAnswer)
            truth = entry["reference_posteriors"][query.key]
            prediction = tuple(answer.probabilities[value] for value in query.states)
            record["model_reasks"].append({"step": entry["step"], "query": query.key,
                "evidence": dict(entry["evidence"]), "target": truth, "prediction": prediction,
                "soft_brier": math.fsum((p - t) ** 2 for p, t in zip(prediction, truth, strict=True)),
                "call_index": len(client.calls) - 1})
        acquisition["additional_model_calls"] = len(record["model_reasks"])
        record["model_reask_soft_brier_mean"] = (
            math.fsum(row["soft_brier"] for row in record["model_reasks"]) / len(record["model_reasks"])
            if record["model_reasks"] else None)
        record["status"] = "complete"
        record["phase"] = "complete"
    except asyncio.CancelledError as exc:
        mark_cancellation(exc)
        record["status"] = "interrupted"
        record["error_type"] = type(exc).__name__
        record["calls"] = client.calls
        record["observed_receipts"] = [receipt.to_dict() for receipt in client.observed_receipts]
        record["attempt_ids"] = client.intents
        record["elapsed_s"] = time.perf_counter() - started
        exc.__dict__["dafjev_workflow"] = record
        raise
    except Exception as exc:
        if isinstance(exc, BudgetStopped) and not (client.calls or client.intents or client.observed_receipts):
            raise
        record["status"] = "failed"
        record["error_type"] = type(exc).__name__
        record["calls"] = client.calls
        record["observed_receipts"] = [receipt.to_dict() for receipt in client.observed_receipts]
        record["attempt_ids"] = client.intents
        record["elapsed_s"] = time.perf_counter() - started
        raise GraphicalExperimentError(record) from exc
    record["calls"] = client.calls
    record["observed_receipts"] = [receipt.to_dict() for receipt in client.observed_receipts]
    record["attempt_ids"] = client.intents
    record["elapsed_s"] = time.perf_counter() - started
    return record
