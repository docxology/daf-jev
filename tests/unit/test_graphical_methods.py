"""Unit tests for the daf_jev.graphical BayesNet methods: most probable
explanation, ancestral sampling, and conditional scenarios.

The canonical Asia fixture below is an independent copy of the one in
test_graphical.py (text inspiration only — no cross-test imports).
Correctness is pinned against direct enumeration over the CPT rows and
against direct ``posterior``/``query`` calls. No mocks, no network, no
.env reads.
"""

from __future__ import annotations

import itertools
import math
import random
from typing import Any

import pytest


def _graphical():
    import daf_jev.graphical as graphical

    return graphical


STATES = ("false", "true")


# --------------------------------------------------------- canonical fixture --


def _asia_variables():
    graphical = _graphical()
    Variable = graphical.Variable
    return (
        Variable(key="asia", description="Recently visited Asia?", states=STATES),
        Variable(key="tub", description="Has tuberculosis", states=STATES),
        Variable(key="smoke", description="Is a smoker", states=STATES),
        Variable(key="lung", description="Has lung cancer", states=STATES),
        Variable(key="bronc", description="Has bronchitis", states=STATES),
        Variable(
            key="either",
            description="Has tuberculosis or lung cancer",
            states=STATES,
        ),
        Variable(key="xray", description="Abnormal X-ray result", states=STATES),
        Variable(
            key="dysp",
            description="Has dyspnoea (shortness of breath)",
            states=STATES,
        ),
    )


def _asia_edges():
    graphical = _graphical()
    Edge = graphical.Edge
    return (
        Edge(parent="asia", child="tub"),
        Edge(parent="smoke", child="lung"),
        Edge(parent="smoke", child="bronc"),
        Edge(parent="lung", child="either"),
        Edge(parent="tub", child="either"),
        Edge(parent="either", child="xray"),
        Edge(parent="either", child="dysp"),
        Edge(parent="bronc", child="dysp"),
    )


def _asia_cpts():
    """Canonical Lauritzen-Spiegelhalter Asia CPTs (independent copy)."""
    graphical = _graphical()
    CPT = graphical.CPT
    return {
        "asia": CPT(child="asia", parents=(), table=(((), (0.99, 0.01)),)),
        "tub": CPT(
            child="tub",
            parents=("asia",),
            table=((("false",), (0.99, 0.01)), (("true",), (0.95, 0.05))),
        ),
        "smoke": CPT(child="smoke", parents=(), table=(((), (0.5, 0.5)),)),
        "lung": CPT(
            child="lung",
            parents=("smoke",),
            table=((("false",), (0.99, 0.01)), (("true",), (0.9, 0.1))),
        ),
        "bronc": CPT(
            child="bronc",
            parents=("smoke",),
            table=((("false",), (0.7, 0.3)), (("true",), (0.4, 0.6))),
        ),
        "either": CPT(
            child="either",
            parents=("lung", "tub"),
            table=(
                (("false", "false"), (1.0, 0.0)),
                (("false", "true"), (0.0, 1.0)),
                (("true", "false"), (0.0, 1.0)),
                (("true", "true"), (0.0, 1.0)),
            ),
        ),
        "xray": CPT(
            child="xray",
            parents=("either",),
            table=((("false",), (0.95, 0.05)), (("true",), (0.02, 0.98))),
        ),
        "dysp": CPT(
            child="dysp",
            parents=("either", "bronc"),
            table=(
                (("false", "false"), (0.9, 0.1)),
                (("false", "true"), (0.2, 0.8)),
                (("true", "false"), (0.3, 0.7)),
                (("true", "true"), (0.1, 0.9)),
            ),
        ),
    }


def _asia_net():
    graphical = _graphical()
    return graphical.BayesNet(
        variables=_asia_variables(),
        edges=_asia_edges(),
        cpts=_asia_cpts(),
    )


# ------------------------------------------------------------- brute force ----


def _joint_probability(net: Any, values: dict[str, str]) -> float:
    """Independent joint probability: the product of CPT row entries."""
    probability = 1.0
    for var in net.variables:
        cpt = net.cpts[var.key]
        labels = tuple(values[parent] for parent in cpt.parents)
        for assignment, probs in cpt.table:
            if assignment == labels:
                probability *= probs[var.states.index(values[var.key])]
                break
        else:
            raise AssertionError(f"no CPT row for {var.key} given {labels!r}")
    return probability


def _brute_force_mpe(net: Any, evidence: dict[str, str]) -> dict[str, str]:
    """Independent argmax over every assignment consistent with the
    evidence, with the same documented tiebreak: the lexicographically
    smallest tuple of state labels in variable-declaration order."""
    keys = [var.key for var in net.variables]
    domains = [
        (evidence[key],) if key in evidence else net.variable(key).states
        for key in keys
    ]
    best_probability = -1.0
    best: tuple[str, ...] | None = None
    for combo in itertools.product(*domains):
        values = dict(zip(keys, combo, strict=True))
        probability = _joint_probability(net, values)
        if probability > best_probability or (
            probability == best_probability and best is not None and combo < best
        ):
            best_probability = probability
            best = combo
    if best is None or best_probability <= 0.0:
        raise ValueError("zero-probability evidence")
    return dict(zip(keys, best, strict=True))


# --------------------------------------- 1. most_probable_explanation --------


def test_mpe_priors_match_brute_force() -> None:
    net = _asia_net()
    assert net.most_probable_explanation({}) == _brute_force_mpe(net, {})


def test_mpe_single_evidence_matches_brute_force() -> None:
    net = _asia_net()
    evidence = {"xray": "true"}
    assert net.most_probable_explanation(evidence) == _brute_force_mpe(net, evidence)


def test_mpe_multi_evidence_matches_brute_force() -> None:
    net = _asia_net()
    evidence = {"smoke": "true", "either": "true"}
    assert net.most_probable_explanation(evidence) == _brute_force_mpe(net, evidence)


@pytest.mark.parametrize(
    "key", ["asia", "tub", "smoke", "lung", "bronc", "either", "xray", "dysp"]
)
def test_mpe_every_variable_evidence_matches_brute_force(key: str) -> None:
    net = _asia_net()
    for state in STATES:
        evidence = {key: state}
        assert net.most_probable_explanation(evidence) == _brute_force_mpe(
            net, evidence
        )


def test_mpe_pins_evidence_variables() -> None:
    net = _asia_net()
    evidence = {"dysp": "true", "xray": "true"}
    explanation = net.most_probable_explanation(evidence)
    assert set(explanation) == {var.key for var in net.variables}
    for key, state in evidence.items():
        assert explanation[key] == state


def _random_net(rng: random.Random, n_vars: int) -> Any:
    """Random DAG + random strictly-positive CPTs; acyclic by construction
    (edges run from earlier-declared to later-declared variables)."""
    graphical = _graphical()
    variables = tuple(
        graphical.Variable(
            key=f"v{index}",
            description=f"random variable {index}",
            states=tuple(f"s{state}" for state in range(rng.randint(2, 3))),
        )
        for index in range(n_vars)
    )
    edges = []
    for index in range(1, n_vars):
        for parent in range(index):
            if rng.random() < 0.4:
                edges.append(graphical.Edge(parent=f"v{parent}", child=f"v{index}"))
    cpts: dict[str, Any] = {}
    for var in variables:
        parents = tuple(edge.parent for edge in edges if edge.child == var.key)
        parent_vars = [v for p in parents for v in variables if v.key == p]
        rows = []
        for assignment in itertools.product(*(pv.states for pv in parent_vars)):
            weights = [rng.random() + 1e-3 for _ in var.states]
            total = sum(weights)
            rows.append((assignment, tuple(w / total for w in weights)))
        cpts[var.key] = graphical.CPT(child=var.key, parents=parents, table=tuple(rows))
    return graphical.BayesNet(variables=variables, edges=tuple(edges), cpts=cpts)


def test_mpe_random_nets_match_brute_force() -> None:
    rng = random.Random(20260922)
    for _trial in range(8):
        net = _random_net(rng, n_vars=rng.randint(3, 5))
        net.validate()
        keys = [var.key for var in net.variables]
        for _case in range(4):
            picked = rng.sample(keys, rng.randint(0, len(keys)))
            evidence = {key: rng.choice(net.variable(key).states) for key in picked}
            explanation = net.most_probable_explanation(evidence)
            assert explanation == _brute_force_mpe(net, evidence)
            for key, state in evidence.items():
                assert explanation[key] == state


def test_mpe_tiebreak_takes_lexicographically_smallest_labels() -> None:
    # Two independent uniform variables: all four assignments tie, so the
    # lexicographically smallest label tuple ("false", "false") must win.
    graphical = _graphical()
    net = graphical.BayesNet(
        variables=(
            graphical.Variable(key="a", description="A", states=STATES),
            graphical.Variable(key="b", description="B", states=STATES),
        ),
        edges=(),
        cpts={
            "a": graphical.CPT(child="a", parents=(), table=(((), (0.5, 0.5)),)),
            "b": graphical.CPT(child="b", parents=(), table=(((), (0.5, 0.5)),)),
        },
    )
    assert net.most_probable_explanation({}) == {"a": "false", "b": "false"}


def test_mpe_tiebreak_compares_labels_not_declaration_order() -> None:
    # States declared ("true", "false"): the string-lexicographic winner is
    # "false", not the first-declared state.
    graphical = _graphical()
    net = graphical.BayesNet(
        variables=(
            graphical.Variable(key="x", description="X", states=("true", "false")),
        ),
        edges=(),
        cpts={"x": graphical.CPT(child="x", parents=(), table=(((), (0.5, 0.5)),))},
    )
    assert net.most_probable_explanation({}) == {"x": "false"}


def test_mpe_rejects_unknown_evidence_key() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown evidence variable 'venus'"):
        net.most_probable_explanation({"venus": "true"})


def test_mpe_rejects_unknown_evidence_state() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown evidence state 'maybe'"):
        net.most_probable_explanation({"tub": "maybe"})


def test_mpe_rejects_zero_probability_evidence() -> None:
    # either is a deterministic OR: lung=false AND tub=false force
    # either=false, so evidence demanding either=true has probability zero.
    net = _asia_net()
    evidence = {"lung": "false", "tub": "false", "either": "true"}
    with pytest.raises(ValueError, match=r"zero probability"):
        net.most_probable_explanation(evidence)


# ------------------------------------------------------------- 2. sample -----


def test_sample_seeded_rng_is_deterministic() -> None:
    net = _asia_net()
    first = net.sample(50, rng=random.Random(7))
    second = net.sample(50, rng=random.Random(7))
    assert first == second


def test_sample_different_seeds_differ() -> None:
    net = _asia_net()
    first = net.sample(200, rng=random.Random(7))
    second = net.sample(200, rng=random.Random(8))
    assert first != second


def test_sample_draws_cover_every_variable_with_valid_states() -> None:
    net = _asia_net()
    draws = net.sample(20, rng=random.Random(3))
    assert len(draws) == 20
    expected_keys = {var.key for var in net.variables}
    for draw in draws:
        assert set(draw) == expected_keys
        for var in net.variables:
            assert draw[var.key] in var.states


def test_sample_rejects_non_positive_n() -> None:
    net = _asia_net()
    for bad in (0, -3, 2.5):
        value: Any = bad
        with pytest.raises(ValueError, match=r"n must be an integer >= 1"):
            net.sample(value, rng=random.Random(1))


def test_sample_frequencies_within_three_sigma_of_priors() -> None:
    net = _asia_net()
    n = 20000
    draws = net.sample(n, rng=random.Random(20260922))
    priors = net.posterior({})
    counts: dict[str, dict[str, int]] = {
        var.key: {state: 0 for state in var.states} for var in net.variables
    }
    for draw in draws:
        for key, state in draw.items():
            counts[key][state] += 1
    for var in net.variables:
        for index, state in enumerate(var.states):
            expected = priors[var.key][index]
            sigma = math.sqrt(expected * (1.0 - expected) / n)
            frequency = counts[var.key][state] / n
            assert abs(frequency - expected) <= 3.0 * sigma, (var.key, state)


def test_sample_conditional_frequency_matches_posterior() -> None:
    # Among bronc=true draws, the dysp=true frequency must track the
    # model's P(dysp=true | bronc=true) within 3 sigma.
    net = _asia_net()
    n = 20000
    draws = net.sample(n, rng=random.Random(20260922))
    matching = [draw for draw in draws if draw["bronc"] == "true"]
    expected = net.query("dysp", {"bronc": "true"})[1]
    frequency = sum(1 for draw in matching if draw["dysp"] == "true") / len(matching)
    sigma = math.sqrt(expected * (1.0 - expected) / len(matching))
    assert abs(frequency - expected) <= 3.0 * sigma


# ---------------------------------------------- 3. conditional_scenarios -----


def test_scenarios_match_direct_posterior_calls() -> None:
    net = _asia_net()
    evidence = {"smoke": "true"}
    scenarios = net.conditional_scenarios("tub", evidence=evidence)
    assert list(scenarios) == list(STATES)
    for state, scenario in scenarios.items():
        posterior = net.posterior({**evidence, "tub": state})
        expected = {
            var.key: posterior[var.key]
            for var in net.variables
            if var.key != "tub"
        }
        assert scenario == expected


def test_scenarios_default_targets_exclude_variable_in_declaration_order() -> None:
    net = _asia_net()
    scenarios = net.conditional_scenarios("tub")
    expected_keys = [var.key for var in net.variables if var.key != "tub"]
    for scenario in scenarios.values():
        assert list(scenario) == expected_keys


def test_scenarios_explicit_targets_match_direct_query() -> None:
    net = _asia_net()
    scenarios = net.conditional_scenarios("tub", targets=("dysp", "xray"))
    for state, scenario in scenarios.items():
        assert list(scenario) == ["dysp", "xray"]
        assert scenario["dysp"] == net.query("dysp", {"tub": state})
        assert scenario["xray"] == net.query("xray", {"tub": state})


def test_scenarios_scenario_state_overrides_same_evidence_key() -> None:
    net = _asia_net()
    scenarios = net.conditional_scenarios("lung", evidence={"lung": "false"})
    for state, scenario in scenarios.items():
        posterior = net.posterior({"lung": state})
        expected = {
            var.key: posterior[var.key]
            for var in net.variables
            if var.key != "lung"
        }
        assert scenario == expected


def test_scenarios_rejects_unknown_variable() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown variable 'venus'"):
        net.conditional_scenarios("venus")


def test_scenarios_rejects_non_string_variable() -> None:
    net = _asia_net()
    variable: Any = 123
    with pytest.raises(ValueError, match=r"unknown variable 123"):
        net.conditional_scenarios(variable)


def test_scenarios_rejects_unknown_target() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown target variable 'venus'"):
        net.conditional_scenarios("tub", targets=("dysp", "venus"))


def test_scenarios_rejects_string_targets() -> None:
    net = _asia_net()
    targets: Any = "dysp"
    with pytest.raises(ValueError, match=r"targets must be a sequence"):
        net.conditional_scenarios("tub", targets=targets)


def test_scenarios_rejects_unknown_evidence_key() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown evidence variable 'venus'"):
        net.conditional_scenarios("tub", evidence={"venus": "true"})


def test_scenarios_rejects_unknown_evidence_state() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"unknown evidence state 'maybe'"):
        net.conditional_scenarios("tub", evidence={"smoke": "maybe"})


def test_scenarios_rejects_zero_probability_scenario() -> None:
    # The either=true scenario conflicts with lung=false AND tub=false:
    # either is a deterministic OR, so that posterior is undefined.
    net = _asia_net()
    with pytest.raises(ValueError, match=r"zero probability"):
        net.conditional_scenarios("either", evidence={"lung": "false", "tub": "false"})