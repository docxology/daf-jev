"""Synthetic rules and frozen supervised comparators; sklearn loads on fit."""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from collections.abc import Mapping
from typing import Any

from daf_jev.decision_backends import (
    BackendCapabilities,
    DecisionPrediction,
    DecisionRequest,
    DecisionResult,
    PriorBackend,
    canonical_json,
)


def _labels(wire: Mapping[str, Any]) -> list[str]:
    if wire["type"] == "noul":
        return ["false", "true"]
    return list(wire["criteria"]) if wire["type"] == "choice" else [str(i) for i in range(len(wire["criteria"]))]


def _target(value: Any, kind: str) -> str:
    if isinstance(value, Mapping):
        raise ValueError("supervised training requires independent discrete labels")
    if kind == "noul":
        if value in ("false", "true"):
            return value
        if value not in (0, 1, False, True):
            raise ValueError("binary training requires hard independent labels")
        return "true" if value else "false"
    return str(value)


def fit_prior(dataset: Any) -> PriorBackend:
    counts: dict[str, Counter[str]] = {}
    vocab: dict[str, list[str]] = {}
    for example in dataset.examples:
        if example.split != "train":
            continue
        for key, target in example.targets.items():
            if isinstance(target, Mapping):
                raise ValueError("training prior requires independent discrete labels")
            wire = example.questions[key].to_wire()
            labels = _labels(wire)
            vocab[key] = labels
            counts.setdefault(key, Counter())[_target(target, wire["type"])] += 1
    if not counts:
        raise ValueError("no training examples")
    priors = {key: {label: (counts[key][label] + 1) / (sum(counts[key].values()) + len(labels)) for label in labels}
              for key, labels in vocab.items()}
    return PriorBackend(priors)


_NEGATION_PREFIX = "Do not treat an unrelated negative statement as overriding the authoritative fields. "
_AUTHORITATIVE_PREFIX = "Authoritative record: "
_RULE_QUESTIONS = {
    "binary": ("noul", "Approve exactly when enabled is true and amount <= limit.", None),
    "categorical": ("choice", "Route duplicate charges to billing, password resets to account, server errors to technical.",
                    {"billing", "account", "technical"}),
    "ordinal": ("score", "Apply the exact point bands.",
                ["0 through 24 points", "25 through 49 points", "50 through 74 points", "75 through 100 points"]),
    "bayes": ("choice", "Apply Bayes' rule to estimate the posterior of the latent binary variable.", {"false", "true"}),
}


def _record_match(state: str, pattern: str) -> re.Match[str]:
    """Consume one anchored authoritative record, never search a quoted suffix."""
    if state.startswith(_NEGATION_PREFIX):
        state = state[len(_NEGATION_PREFIX):]
    elif state.startswith(_AUTHORITATIVE_PREFIX):
        state = state[len(_AUTHORITATIVE_PREFIX):]
    match = re.match(pattern, state, flags=re.ASCII)
    if match is None:
        raise ValueError("malformed or ambiguous authoritative synthetic record")
    suffix = state[match.end():]
    if suffix and not suffix.startswith((" Untrusted quoted note: ", "\nIrrelevant reference: ")):
        raise ValueError("unrecognized suffix or multiple authoritative records")
    return match


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate authoritative JSON field")
        result[key] = value
    return result


class RuleDecisionBackend:
    """Exact reference for declared synthetic tasks, without target access.

    Hard rule outputs are labels/levels, not one-hot beliefs. Only the Bayes
    task has a genuine analytical distribution; no correctness confidence is
    fabricated for any task. The grammar is scoped to generator-v2 records.
    """
    def __init__(self, kind: str) -> None:
        if not isinstance(kind, str) or kind not in _RULE_QUESTIONS:
            raise ValueError("rule backend requires a declared synthetic kind")
        self.kind = kind
        self.model = f"synthetic-rule-{kind}"
        self.capabilities = BackendCapabilities(
            primitives=(_RULE_QUESTIONS[kind][0],), max_questions=1,
            probability_source="analytical_bayes_rule" if kind == "bayes" else None,
            confidence_semantics=None, probability_rounding_digits=None,
            evidence="deterministic_synthetic_reference_method",
            probability_semantics="analytical_conditional_probability" if kind == "bayes" else None)

    def predict(self, request: DecisionRequest) -> DecisionResult:
        if not isinstance(request.state, str):
            raise ValueError("synthetic rule state must be text")
        if set(request.questions) != {"decision"}:
            raise ValueError("synthetic rule requires exactly the decision question")
        wire = request.questions["decision"].to_wire()
        kind, instructions, criteria = _RULE_QUESTIONS[self.kind]
        if wire["type"] != kind or wire["instructions"] != instructions:
            raise ValueError("question does not match the declared synthetic rule")
        if self.kind in {"categorical", "bayes"}:
            if set(wire["criteria"]) != criteria:
                raise ValueError("synthetic rule requires the complete choice vocabulary")
            descriptions = ({key: key for key in ("billing", "account", "technical")} if self.kind == "categorical"
                            else {"false": "latent variable false", "true": "latent variable true"})
            if wire["criteria"] != descriptions:
                raise ValueError("choice descriptions differ from the declared synthetic rule")
        elif self.kind == "ordinal" and wire["criteria"] != criteria:
            raise ValueError("ordinal point-band ordering differs from the declared rule")
        elif self.kind == "binary" and "criteria" in wire:
            raise ValueError("binary criteria differ from the declared synthetic rule")
        probabilities = None
        if self.kind == "binary":
            match = _record_match(request.state,
                r"\ARecord (?P<case>\d+): amount=(?P<amount>\d+), limit=(?P<limit>\d+), enabled=(?P<enabled>true|false)\.")
            value: str | float = float(match["enabled"] == "true" and int(match["amount"]) <= int(match["limit"]))
        elif self.kind == "categorical":
            match = _record_match(request.state,
                r"\ATicket (?P<case>\d+): Please handle my (?P<event>duplicate charge|password reset|server error)\. Reference \d+\.")
            value = {"duplicate charge": "billing", "password reset": "account", "server error": "technical"}[match["event"]]
        elif self.kind == "ordinal":
            match = _record_match(request.state, r"\ACase (?P<case>\d+) has (?P<points>\d+) points out of 100\.")
            points = int(match["points"])
            if points > 100:
                raise ValueError("synthetic ordinal points must be in [0, 100]")
            value = float(min(points // 25, 3))
        else:
            data = json.loads(request.state, object_pairs_hook=_unique_json_object)
            fields = {"case", "prior_true", "p_observation_true_given_true", "p_observation_true_given_false", "observation"}
            if not isinstance(data, dict) or set(data) not in (fields, fields | {"irrelevant_text"}):
                raise ValueError("Bayes state requires exactly the authoritative fields")
            if isinstance(data["case"], bool) or not isinstance(data["case"], int) or data["case"] < 0:
                raise ValueError("Bayes case must be a nonnegative integer")
            if not isinstance(data["observation"], bool) or ("irrelevant_text" in data and not isinstance(data["irrelevant_text"], str)):
                raise ValueError("Bayes observation must be boolean and irrelevant_text must be text")
            for key in fields - {"case", "observation"}:
                number = data[key]
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError("Bayes probabilities must be finite numbers in [0, 1]")
            prior = data["prior_true"]
            lt, lf = data["p_observation_true_given_true"], data["p_observation_true_given_false"]
            if not data["observation"]:
                lt, lf = 1 - lt, 1 - lf
            mass = prior * lt + (1 - prior) * lf
            if mass <= 0:
                raise ValueError("Bayes observation has zero probability")
            posterior = prior * lt / mass
            probabilities = {"false": 1 - posterior, "true": posterior}
            value = max(wire["criteria"], key=probabilities.__getitem__)
        prediction = DecisionPrediction(kind, value, probabilities,
            probability_source=self.capabilities.probability_source,
            probability_semantics=self.capabilities.probability_semantics)
        return DecisionResult({"decision": prediction}, workflow={"method": "exact_synthetic_rule", "kind": self.kind,
            "target_access": False, "rule_output_semantics": "analytical_distribution" if probabilities else "hard_rule_value"})

    def close(self) -> None:
        pass


class SklearnDecisionBackend:
    def __init__(self, dataset: Any, *, structured: bool = False, seed: int = 20261007) -> None:
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
            from sklearn.feature_extraction import DictVectorizer
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline
        except ImportError as exc:
            raise ImportError("supervised baselines require daf-jev[benchmark]") from exc
        self.model = "hist-gradient-boosting" if structured else "tfidf-logistic-C1"
        self.capabilities = BackendCapabilities(probability_source="classifier", confidence_semantics="top_probability", probability_rounding_digits=None, probability_semantics="estimated_class_probability")
        self.structured = structured
        self.estimators: dict[str, Any] = {}
        self.vocabulary: dict[str, list[str]] = {}
        start = time.perf_counter()
        rows = [example for example in dataset.examples if example.split == "train"]
        if not rows:
            raise ValueError("baseline fit requires training split")
        for key, question in rows[0].questions.items():
            wire = question.to_wire()
            labels = _labels(wire)
            self.vocabulary[key] = labels
            targets = [_target(row.targets[key], wire["type"]) for row in rows]
            if len(set(targets)) < 2:
                raise ValueError("supervised baseline needs at least two training classes")
            if any(label not in labels for label in targets):
                raise ValueError("training labels outside declared vocabulary")
            if structured:
                estimator = make_pipeline(DictVectorizer(sparse=False), HistGradientBoostingClassifier(max_iter=100, random_state=seed))
            else:
                estimator = make_pipeline(TfidfVectorizer(), LogisticRegression(C=1, max_iter=2000, random_state=seed))
            estimator.fit([self._features(row.state) for row in rows], targets)
            self.estimators[key] = estimator
        self.training = {"split": "train", "examples": len(rows), "elapsed_s": time.perf_counter() - start,
                         "seed": seed, "hyperparameters": "fixed; no test-driven selection"}

    def _features(self, state: Any) -> Any:
        if self.structured:
            value = state if isinstance(state, dict) else __import__("json").loads(state)
            if not isinstance(value, dict):
                raise ValueError("structured baseline requires feature object")
            if "features" in value:
                features = value["features"]
                if not isinstance(features, dict) or any(not isinstance(v, (int, float)) for v in features.values()):
                    raise ValueError("wine features must be numeric")
                return {**features, "wine_type": value["wine_type"]}
            return value
        return state if isinstance(state, str) else canonical_json(state)

    def predict(self, request: DecisionRequest) -> DecisionResult:
        predictions = {}
        for key, question in request.questions.items():
            if key not in self.estimators:
                raise ValueError("question absent from training fit")
            estimator = self.estimators[key]
            values = estimator.predict_proba([self._features(request.state)])[0]
            probabilities = dict.fromkeys(self.vocabulary[key], 0.0)
            probabilities.update({str(label): float(p) for label, p in zip(estimator.classes_, values, strict=True)})
            wire = question.to_wire()
            declared = _labels(wire)
            if set(declared) != set(probabilities):
                raise ValueError("evaluation vocabulary differs from fitted pipeline")
            label = max(declared, key=lambda k: probabilities[k])
            value = label if wire["type"] == "choice" else (sum(int(k)*v for k, v in probabilities.items()) if wire["type"] == "score" else probabilities["true"])
            predictions[key] = DecisionPrediction(wire["type"], value, probabilities, max(probabilities.values()), "classifier", "top_probability",
                probability_semantics="estimated_class_probability")
        return DecisionResult(predictions)

    def close(self) -> None:
        pass
