"""Unit tests for daf_jev.graphical_elicitation over the real local stub.

Same no-mock convention as the rest of the suite: elicitation drives a real
JevClient (built through the public open_client provider path) against the
ThreadingHTTPServer stand-in from tests/conftest.py; daf_jev internals are
never patched and the repo `.env` is never read (clean-provider-env pattern
from tests/unit/test_providers.py).

CPT elicitation question ids follow the pinned contract scheme
``cpt::<child>|<p>=<v>|...`` so canned responses are keyed up front. The
structure-proposal question id scheme is NOT pinned by the contract, so the
pair->id mapping is learned from a probe request's recorded questions (still
no mocks: the probe is a real request whose empty answer set is expected to
fail scoring) and reused to key the real canned body; the successful second
call doubles as proof that the id scheme is deterministic across calls.
The contract's literal structure score (maximize the sum of log p over
consistent edges minus edge_penalty per edge) is degenerate: log p <= 0 for
p <= 1, so any positive penalty prefers the empty graph and no known DAG
could ever be reproduced, contradicting the contract's own test item. The
canned answers below are robust across the two coherent repairs —
probability-weighted (sum p minus penalty) and surprisal (sum -log p minus
penalty): reference-pair directional options dominate their pair, non-
reference pairs choose "no-edge" (so no edge candidate exists), the
reproduction and greedy cases run at edge_penalty=0.0 where every reading
aligns all 8 reference edges, and the sparsity case runs at
edge_penalty=3.0 where no reading keeps any edge. A literal log-formula
implementation returns empty graphs everywhere and fails the reproduction
test visibly at fold.
"""


from __future__ import annotations

import contextlib
import json
import math
from itertools import combinations, product
from typing import Any

import pytest

STATES = ("false", "true")
VARIABLE_KEYS = ("asia", "tub", "smoke", "lung", "bronc", "either", "xray", "dysp")
_DESCRIPTIONS = {
    "asia": "Recently visited Asia?",
    "tub": "Has tuberculosis",
    "smoke": "Is a smoker",
    "lung": "Has lung cancer",
    "bronc": "Has bronchitis",
    "either": "Has tuberculosis or lung cancer",
    "xray": "Abnormal X-ray result",
    "dysp": "Has dyspnoea (shortness of breath)",
}
_PARENTS = {
    "asia": (),
    "tub": ("asia",),
    "smoke": (),
    "lung": ("smoke",),
    "bronc": ("smoke",),
    "either": ("lung", "tub"),
    "xray": ("either",),
    "dysp": ("either", "bronc"),
}

# Canonical Lauritzen-Spiegelhalter Asia probabilities, keyed
# (child, (p1, v1, p2, v2, ...)) flattened assignment tuples in
# parent-assignment lexicographic order by each parent's states order.
_CANONICAL_ROWS: dict[tuple, tuple[float, ...]] = {
    ("asia", ()): (0.99, 0.01),
    ("tub", ("asia", "false")): (0.99, 0.01),
    ("tub", ("asia", "true")): (0.95, 0.05),
    ("smoke", ()): (0.5, 0.5),
    ("lung", ("smoke", "false")): (0.99, 0.01),
    ("lung", ("smoke", "true")): (0.9, 0.1),
    ("bronc", ("smoke", "false")): (0.7, 0.3),
    ("bronc", ("smoke", "true")): (0.4, 0.6),
    ("either", ("lung", "false", "tub", "false")): (1.0, 0.0),
    ("either", ("lung", "false", "tub", "true")): (0.0, 1.0),
    ("either", ("lung", "true", "tub", "false")): (0.0, 1.0),
    ("either", ("lung", "true", "tub", "true")): (0.0, 1.0),
    ("xray", ("either", "false")): (0.95, 0.05),
    ("xray", ("either", "true")): (0.02, 0.98),
    ("dysp", ("either", "false", "bronc", "false")): (0.9, 0.1),
    ("dysp", ("either", "false", "bronc", "true")): (0.2, 0.8),
    ("dysp", ("either", "true", "bronc", "false")): (0.3, 0.7),
    ("dysp", ("either", "true", "bronc", "true")): (0.1, 0.9),
}

# Reference Asia edges and the canned probability of each chosen directional
# option (distinct descending values keep greedy assembly deterministic).
# Reverse directions get 0.02 and "no-edge" the remainder; non-reference
# pairs get "no-edge" 0.9 and 0.05 per direction. Under either coherent
# reading of the contract's edge-score formula this yields the reference
# 8-edge DAG at edge_penalty <= ~0.8 and the empty graph at >= 2.0.
_REFERENCE_P = {
    ("asia", "tub"): 0.90,
    ("smoke", "lung"): 0.89,
    ("smoke", "bronc"): 0.88,
    ("lung", "either"): 0.87,
    ("tub", "either"): 0.86,
    ("either", "xray"): 0.85,
    ("either", "dysp"): 0.84,
    ("bronc", "dysp"): 0.83,
}


def _graphical():
    import daf_jev.graphical as graphical

    return graphical


def _elicitation_module():
    import daf_jev.graphical_elicitation as elicitation

    return elicitation


_PROVIDER_ENV_VARS = (
    "JEV_API_KEY",
    "JEV_BASE_URL",
    "JEV_MODEL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "TYPESAFE_DEFAULT_MODEL",
    "JEFF_API_KEY",
    "JEFF_BASE_URL",
    "JEFF_MODEL",
    "KEV_API_KEY",
    "KEV_BASE_URL",
    "KEV_MODEL",
    "LOCALJEV_API_KEY",
    "LOCALJEV_BASE_URL",
    "LOCALJEV_MODEL",
    "OPENTHAI_API_KEY",
    "OPENTHAI_BASE_URL",
    "OPENTHAI_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "DAF_JEV_PROVIDER",
)


@pytest.fixture
def clean_provider_env(monkeypatch, tmp_path: Any):
    """Isolate provider resolution from the host env and the repo `.env`."""
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # the `.env` fallback resolves relative to CWD
    return monkeypatch


# ------------------------------------------------------------- fixtures ------


def _asia_variables():
    graphical = _graphical()
    Variable = graphical.Variable
    return tuple(
        Variable(key=key, description=_DESCRIPTIONS[key], states=STATES)
        for key in VARIABLE_KEYS
    )


def _asia_edges():
    graphical = _graphical()
    Edge = graphical.Edge
    return tuple(
        Edge(parent=parent, child=child) for parent, child in _REFERENCE_P
    )


def _flat_assignment(parents: tuple[str, ...], combo: tuple[str, ...]) -> tuple:
    return tuple(
        v for pair in zip(parents, combo, strict=True) for v in pair
    )


def _expected_asia_net():
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = {}
    for child in VARIABLE_KEYS:
        parents = _PARENTS[child]
        table = tuple(
            (combo, _CANONICAL_ROWS[(child, _flat_assignment(parents, combo))])
            for combo in product(*(STATES for _ in parents))
        )
        cpts[child] = CPT(child=child, parents=parents, table=table)
    return graphical.BayesNet(
        variables=_asia_variables(), edges=_asia_edges(), cpts=cpts
    )


def _cpt_question_id(child: str, assignment: tuple[str, ...]) -> str:
    # Pinned contract scheme: f"cpt::{child}|{'|'.join(f'{p}={v}' ...)}".
    return f"cpt::{child}|" + "|".join(
        f"{parent}={value}"
        for parent, value in zip(_PARENTS[child], assignment, strict=True)
    )


def _expected_elicit_ids() -> tuple[str, ...]:
    ids: list[str] = []
    for child in VARIABLE_KEYS:
        for combo in product(*(STATES for _ in _PARENTS[child])):
            ids.append(_cpt_question_id(child, combo))
    return tuple(ids)




def _choice_body(
    answers: dict[str, dict[str, float]], model: str = "jev-latest"
) -> dict:
    """System One response body: one choice answer per question id."""
    wire_answers = {}
    for qid, probabilities in answers.items():
        choice = None
        best = -1.0
        for option, value in probabilities.items():
            if value > best:
                best, choice = value, option
        wire_answers[qid] = {
            "type": "choice",
            "choice": choice,
            "probabilities": dict(probabilities),
            "confidence": 0.9,
        }
    return {
        "model": model,
        "usage": {"input_tokens": 120, "output_tokens": 45},
        "answers": wire_answers,
    }


def _canonical_answer_probabilities() -> dict[str, dict[str, float]]:
    return {
        _cpt_question_id(child, combo): {"false": row[0], "true": row[1]}
        for child in VARIABLE_KEYS
        for combo in product(*(STATES for _ in _PARENTS[child]))
        for row in (
            _CANONICAL_ROWS[(child, _flat_assignment(_PARENTS[child], combo))],
        )
    }


def _open_client(stub):
    from daf_jev import RetryPolicy, open_client

    return open_client(
        "jev",
        api_key="test-key",
        base_url=stub.base_url,
        retry=RetryPolicy(jitter=0.0),
    )


# ------------------------------------------------------- CPT elicitation -----


def test_elicit_cpts_single_request_18_canonical_asia(stub, clean_provider_env) -> None:
    stub.enqueue(body=_choice_body(_canonical_answer_probabilities()))
    with _open_client(stub) as client:
        net = _elicitation_module().elicit_cpts(
            _asia_variables(), _asia_edges(), client=client
        )

    assert len(stub.hits) == 1
    payload = stub.hits[0]["json"]
    assert payload["model"] == "jev-latest"
    assert isinstance(payload["state"], str) and payload["state"]
    questions = payload["questions"]
    assert list(questions) == list(_expected_elicit_ids())
    for qid, question in questions.items():
        assert question["type"] == "choice"
        assert isinstance(question["instructions"], str) and question["instructions"]
        assert list(question["criteria"]) == list(STATES), qid

    expected = _expected_asia_net()
    assert net == expected
    net.validate()  # elicitation returns a validated net


def test_elicit_cpts_chunking_three_requests_preserves_order(
    stub, clean_provider_env
) -> None:
    answers = _canonical_answer_probabilities()
    ids = _expected_elicit_ids()
    for chunk in (ids[:8], ids[8:16], ids[16:]):
        stub.enqueue(body=_choice_body({qid: answers[qid] for qid in chunk}))
    with _open_client(stub) as client:
        net = _elicitation_module().elicit_cpts(
            _asia_variables(),
            _asia_edges(),
            client=client,
            max_questions_per_request=8,
        )

    assert len(stub.hits) == 3
    assert list(stub.hits[0]["json"]["questions"]) == list(ids[:8])
    assert list(stub.hits[1]["json"]["questions"]) == list(ids[8:16])
    assert list(stub.hits[2]["json"]["questions"]) == list(ids[16:])
    assert net == _expected_asia_net()


def test_elicit_cpts_missing_answer_names_question_id(stub, clean_provider_env) -> None:
    answers = _canonical_answer_probabilities()
    missing = "cpt::xray|either=true"
    del answers[missing]
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client, pytest.raises(
        ValueError, match=r"cpt::xray\|either=true"
    ):
        _elicitation_module().elicit_cpts(
            _asia_variables(), _asia_edges(), client=client
        )


def test_elicit_cpts_rejects_non_finite_probability(stub, clean_provider_env) -> None:
    answers = _canonical_answer_probabilities()
    answers["cpt::tub|asia=true"] = {"false": 0.95, "true": math.inf}
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client, pytest.raises(ValueError):
        _elicitation_module().elicit_cpts(
            _asia_variables(), _asia_edges(), client=client
        )


def test_elicit_cpts_rejects_unknown_state_label(stub, clean_provider_env) -> None:
    answers = _canonical_answer_probabilities()
    answers["cpt::smoke|"] = {"false": 0.5, "true": 0.25, "maybe": 0.25}
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client, pytest.raises(ValueError):
        _elicitation_module().elicit_cpts(
            _asia_variables(), _asia_edges(), client=client
        )


def test_elicit_cpts_custom_instructions_reach_the_request(
    stub, clean_provider_env
) -> None:
    stub.enqueue(body=_choice_body(_canonical_answer_probabilities()))
    with _open_client(stub) as client:
        _elicitation_module().elicit_cpts(
            _asia_variables(),
            _asia_edges(),
            client=client,
            instructions="Cohort: 50-year-old patients.",
        )
    assert "50-year-old" in json.dumps(stub.hits[0]["json"])


def test_elicit_cpts_rejects_cyclic_edges(stub, clean_provider_env) -> None:
    graphical = _graphical()
    Variable, Edge = graphical.Variable, graphical.Edge
    variables = (
        Variable(key="a", description="a", states=STATES),
        Variable(key="b", description="b", states=STATES),
    )
    edges = (Edge(parent="a", child="b"), Edge(parent="b", child="a"))
    with _open_client(stub) as client, pytest.raises(ValueError):
        _elicitation_module().elicit_cpts(variables, edges, client=client)
    assert stub.hits == []  # rejected before any network round-trip


# ------------------------------------------------- structure proposal --------




def _parse_pair(options: list[str]) -> tuple[str, str]:
    assert len(options) == 3
    assert options[2] == "no-edge"
    a, b = options[0].split("->")
    assert options[1] == f"{b}->{a}"
    return a, b


def _learned_pair_ids(stub, variables, client) -> dict[frozenset[str], str]:
    """One throwaway round-trip to learn the implementation's (unpinned)
    structure question id scheme from the recorded request."""
    stub.enqueue(body=_choice_body({}, model="probe"))
    with contextlib.suppress(Exception):
        # Empty answers cannot be scored; the request itself is recorded.
        _elicitation_module().propose_structure(
            variables, client=client, exact_limit=2
        )
    questions = stub.hits[0]["json"]["questions"]
    mapping: dict[frozenset[str], str] = {}
    for qid, wire in questions.items():
        pair = _parse_pair(list(wire["criteria"]))
        mapping[frozenset(pair)] = qid
    assert len(mapping) == 28
    return mapping


def _canned_structure_answers(stub, variables, client) -> dict[str, dict[str, float]]:
    learned = _learned_pair_ids(stub, variables, client)
    answers: dict[str, dict[str, float]] = {}
    for pair in combinations(VARIABLE_KEYS, 2):
        qid = learned[frozenset(pair)]
        options = list(stub.hits[0]["json"]["questions"][qid]["criteria"])
        reference_key = pair if pair in _REFERENCE_P else (pair[1], pair[0])
        if reference_key not in _REFERENCE_P:
            probabilities = {options[0]: 0.05, options[1]: 0.05, "no-edge": 0.9}
        else:
            probability = _REFERENCE_P[reference_key]
            forward = f"{reference_key[0]}->{reference_key[1]}"
            reverse = f"{reference_key[1]}->{reference_key[0]}"
            assert forward in (options[0], options[1])
            other = reverse if forward == options[0] else options[0]
            probabilities = {forward: probability, other: 0.02}
            probabilities["no-edge"] = round(1.0 - probability - 0.02, 10)
        answers[qid] = probabilities
    return answers


def test_propose_structure_single_request_28_pair_questions(
    stub, clean_provider_env
) -> None:
    variables = _asia_variables()
    answers = _canned_structure_answers(stub, variables, _open_client(stub))
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client:
        net = _elicitation_module().propose_structure(
            variables, client=client, exact_limit=2
        )

    assert len(stub.hits) == 2  # probe round-trip + the real request
    payload = stub.hits[-1]["json"]
    assert payload["model"] == "jev-latest"
    assert isinstance(payload["state"], str) and payload["state"]
    questions = payload["questions"]
    assert len(questions) == 28
    assert len(set(questions)) == 28
    pairs = set()
    for _qid, wire in questions.items():
        options = list(wire["criteria"])
        pair = _parse_pair(options)
        assert wire["type"] == "choice"
        assert isinstance(wire["instructions"], str) and wire["instructions"]
        # Option order is the pinned directional-then-no-edge triple.
        assert options[0] == f"{pair[0]}->{pair[1]}"
        assert options[1] == f"{pair[1]}->{pair[0]}"
        pairs.add(frozenset(pair))
    assert pairs == {frozenset(pair) for pair in combinations(VARIABLE_KEYS, 2)}
    # Two-step flow: structure only; CPTs come from elicit_cpts.
    assert dict(net.cpts) == {}


def test_propose_structure_request_is_deterministic(stub, clean_provider_env) -> None:
    variables = _asia_variables()
    answers = _canned_structure_answers(stub, variables, _open_client(stub))
    stub.enqueue(body=_choice_body(answers))
    stub.enqueue(body=_choice_body(answers))
    client = _open_client(stub)
    _elicitation_module().propose_structure(variables, client=client, exact_limit=2)
    _elicitation_module().propose_structure(variables, client=client, exact_limit=2)
    assert list(stub.hits[1]["json"]["questions"]) == list(
        stub.hits[2]["json"]["questions"]
    )


def test_propose_structure_exact_search_recovers_reference_edges(
    stub, clean_provider_env
) -> None:
    variables = _asia_variables()
    answers = _canned_structure_answers(stub, variables, _open_client(stub))
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client:
        net = _elicitation_module().propose_structure(
            variables, client=client, edge_penalty=0.0
        )

    edge_set = {(edge.parent, edge.child) for edge in net.edges}
    assert edge_set == set(_REFERENCE_P)
    assert dict(net.cpts) == {}
    # Topology is usable pre-CPT; full validation is the second step's job.
    assert sorted(net.topological_order()) == sorted(VARIABLE_KEYS)
    with pytest.raises(ValueError):
        net.validate()


def test_propose_structure_greedy_fallback_matches_exact(
    stub, clean_provider_env
) -> None:
    variables = _asia_variables()
    answers = _canned_structure_answers(stub, variables, _open_client(stub))
    stub.enqueue(body=_choice_body(answers))
    with _open_client(stub) as client:
        net = _elicitation_module().propose_structure(
            variables, client=client, exact_limit=2, edge_penalty=0.0
        )

    # n=8 > exact_limit=2 forces the greedy path; distinct descending
    # probabilities make it deterministic, and every reference edge clears
    # the penalty gate while keeping the graph acyclic.
    assert {(edge.parent, edge.child) for edge in net.edges} == set(_REFERENCE_P)


def test_propose_structure_edge_penalty_sparsifies(stub, clean_provider_env) -> None:
    variables = _asia_variables()
    answers = _canned_structure_answers(stub, variables, _open_client(stub))
    stub.enqueue(body=_choice_body(answers))
    stub.enqueue(body=_choice_body(answers))
    client = _open_client(stub)
    dense = _elicitation_module().propose_structure(
        variables, client=client, exact_limit=2, edge_penalty=0.0
    )
    sparse = _elicitation_module().propose_structure(
        variables, client=client, exact_limit=2, edge_penalty=3.0
    )
    assert len(dense.edges) == 8
    assert sparse.edges == ()  # no canned edge clears the penalty gate
    assert sorted(sparse.topological_order()) == sorted(VARIABLE_KEYS)