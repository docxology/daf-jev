"""Unit tests for daf_jev.graphical: BayesNet validation, topological order,
GraphSpec JSON interchange, and exact discrete inference.

Every inference result is cross-checked against an independent brute-force
joint enumeration (256 assignments for the Asia net) computed here in the
test with pure stdlib math, so the variable-elimination implementation is
never compared against itself.

Production modules land concurrently with this file: daf_jev is imported
lazily inside helpers so collection succeeds in any lane order. No mocks,
no patching of daf_jev internals, and the repo `.env` is never read.
"""

from __future__ import annotations

import json
import math
from itertools import product
from typing import Any

import pytest

GRAPH_SPEC_FORMAT = "dafjev.bayesnet/1"
STATES = ("false", "true")


def _graphical():
    import daf_jev.graphical as graphical

    return graphical


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
    """Canonical Lauritzen-Spiegelhalter Asia CPTs as (assignment, probs) rows
    in parent-assignment lexicographic order by each parent's states order."""
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


# ------------------------------------------------------------ brute force ----


def _row_probability(cpt: Any, assignment: dict[str, str]) -> float:
    labels = tuple(assignment[parent] for parent in cpt.parents)
    for row_labels, probabilities in cpt.table:
        if row_labels == labels:
            return probabilities[STATES.index(assignment[cpt.child])]
    raise AssertionError(f"no CPT row for {cpt.child} given {labels!r}")


def _brute_force_posterior(
    net: Any, evidence: dict[str, str]
) -> dict[str, tuple[float, ...]]:
    """Independent joint enumeration: sum the product of CPT entries over
    every full assignment consistent with the evidence, then normalize.
    Deliberately naive (2**n rows) so it shares no code with the
    variable-elimination implementation under test."""
    variables = list(net.variables)
    keys = [variable.key for variable in variables]
    states_of = {v.key: v.states for v in variables}
    marginal: dict[str, list[float]] = {
        key: [0.0] * len(states_of[key]) for key in keys
    }
    total = 0.0
    for combo in product(*(v.states for v in variables)):
        assignment = dict(zip(keys, combo, strict=True))
        if any(assignment[key] != value for key, value in evidence.items()):
            continue
        p = 1.0
        for key in keys:
            p *= _row_probability(net.cpts[key], assignment)
        for key in keys:
            marginal[key][states_of[key].index(assignment[key])] += p
        total += p
    assert total > 0.0
    return {
        key: tuple(value / total for value in values)
        for key, values in marginal.items()
    }


# --------------------------------------------------------------- helpers -----


def _expect_validation_error(
    variables: Any, edges: Any, cpts: Any, match: str
) -> None:
    """Assert the documented error class fires. Construction is inside the
    block so a lazy (validate()-time) or eager (__post_init__-time) check
    both satisfy the assertion."""
    graphical = _graphical()
    with pytest.raises(ValueError, match=match):
        net = graphical.BayesNet(variables=variables, edges=edges, cpts=cpts)
        net.validate()


def _cpts_with(child: str, cpt: Any) -> dict[str, Any]:
    cpts = dict(_asia_cpts())
    cpts[child] = cpt
    return cpts


# ------------------------------------------------- 1. validation matrix ------


def test_validate_accepts_canonical_asia() -> None:
    net = _asia_net()
    net.validate()  # must not raise
    net.validate()  # idempotent


def test_validate_rejects_unknown_edge_parent() -> None:
    graphical = _graphical()
    Edge = graphical.Edge
    _expect_validation_error(
        _asia_variables(),
        (*_asia_edges(), Edge(parent="mars", child="tub")),
        _asia_cpts(),
        match=r"mars",
    )


def test_validate_rejects_unknown_edge_child() -> None:
    graphical = _graphical()
    Edge = graphical.Edge
    _expect_validation_error(
        _asia_variables(),
        (*_asia_edges(), Edge(parent="asia", child="venus")),
        _asia_cpts(),
        match=r"venus",
    )


def test_validate_rejects_duplicate_edge() -> None:
    graphical = _graphical()
    Edge = graphical.Edge
    _expect_validation_error(
        _asia_variables(),
        (*_asia_edges(), Edge(parent="asia", child="tub")),
        _asia_cpts(),
        match=r"asia.*tub|tub.*asia",
    )


def test_validate_rejects_self_loop() -> None:
    graphical = _graphical()
    Edge = graphical.Edge
    _expect_validation_error(
        _asia_variables(),
        (*_asia_edges(), Edge(parent="tub", child="tub")),
        _asia_cpts(),
        match=r"tub",
    )


def test_validate_rejects_missing_cpt() -> None:
    cpts = _asia_cpts()
    del cpts["xray"]
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"xray"
    )


def test_validate_rejects_cpt_missing_graph_parent() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "xray",
        CPT(
            child="xray",
            parents=(),  # graph says xray has parent either
            table=(
                ((), (0.95, 0.05)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"xray"
    )


def test_validate_rejects_cpt_extra_parent() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "tub",
        CPT(
            child="tub",
            parents=("asia", "smoke"),  # graph only has asia -> tub
            table=(
                (("false", "false"), (0.99, 0.01)),
                (("false", "true"), (0.99, 0.01)),
                (("true", "false"), (0.95, 0.05)),
                (("true", "true"), (0.95, 0.05)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"tub"
    )


def test_validate_rejects_cpt_parent_order_mismatch() -> None:
    # Same parent set, wrong order: (bronc, either) vs graph (either, bronc).
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "dysp",
        CPT(
            child="dysp",
            parents=("bronc", "either"),
            table=(
                (("false", "false"), (0.9, 0.1)),
                (("false", "true"), (0.3, 0.7)),
                (("true", "false"), (0.2, 0.8)),
                (("true", "true"), (0.1, 0.9)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"dysp"
    )


def test_validate_rejects_wrong_probability_tuple_length() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "tub",
        CPT(
            child="tub",
            parents=("asia",),
            table=(
                (("false",), (0.99, 0.01)),
                (("true",), (0.95, 0.05, 0.0)),  # 3 values, 2 states
            ),
        ),
    )
    _expect_validation_error(_asia_variables(), _asia_edges(), cpts, match=r"tub")


def test_validate_rejects_missing_assignment_row() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "lung",
        CPT(
            child="lung",
            parents=("smoke",),
            table=((("false",), (0.99, 0.01)),),  # ("true",) row missing
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"lung"
    )


def test_validate_rejects_duplicate_assignment_row() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "lung",
        CPT(
            child="lung",
            parents=("smoke",),
            table=(
                (("false",), (0.99, 0.01)),
                (("false",), (0.99, 0.01)),  # duplicate assignment
                (("true",), (0.9, 0.1)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"lung"
    )


def test_validate_rejects_negative_probability() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "tub",
        CPT(
            child="tub",
            parents=("asia",),
            table=(
                (("false",), (-0.01, 1.01)),
                (("true",), (0.95, 0.05)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"tub"
    )


def test_validate_rejects_non_finite_probability() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    for bad in (math.nan, math.inf):
        cpts = _cpts_with(
            "tub",
            CPT(
                child="tub",
                parents=("asia",),
                table=(
                    (("false",), (bad, 1.0 - bad if not math.isnan(bad) else 0.0)),
                    (("true",), (0.95, 0.05)),
                ),
            ),
        )
        _expect_validation_error(
            _asia_variables(), _asia_edges(), cpts, match=r"tub"
        )


def test_validate_rejects_row_not_summing_to_one() -> None:
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "tub",
        CPT(
            child="tub",
            parents=("asia",),
            table=(
                (("false",), (0.5, 0.4)),  # sums to 0.9
                (("true",), (0.95, 0.05)),
            ),
        ),
    )
    _expect_validation_error(
        _asia_variables(), _asia_edges(), cpts, match=r"tub"
    )


def test_validate_accepts_row_within_tolerance() -> None:
    # Deviation of 5e-7 is inside the documented 1e-6 tolerance.
    graphical = _graphical()
    CPT = graphical.CPT
    cpts = _cpts_with(
        "tub",
        CPT(
            child="tub",
            parents=("asia",),
            table=(
                (("false",), (0.5, 0.5000005)),
                (("true",), (0.95, 0.05)),
            ),
        ),
    )
    net = graphical.BayesNet(
        variables=_asia_variables(), edges=_asia_edges(), cpts=cpts
    )
    net.validate()  # must not raise


def test_variable_lookup_and_error_message() -> None:
    net = _asia_net()
    assert net.variable("tub").description == "Has tuberculosis"
    with pytest.raises(KeyError, match=r"venus"):
        net.variable("venus")


def test_parent_and_child_lookups() -> None:
    net = _asia_net()
    assert net.parents_of("dysp") == ("either", "bronc")
    assert net.parents_of("asia") == ()
    assert net.children_of("smoke") == ("lung", "bronc")
    assert net.children_of("dysp") == ()


# ----------------------------------------- 2. topological order --------------


def test_topological_order_canonical_asia_deterministic() -> None:
    net = _asia_net()
    order = net.topological_order()
    keys = [variable.key for variable in net.variables]
    # "Kahn with insertion-order tiebreak" has two legitimate readings that
    # diverge on Asia at positions 2-3 — FIFO ready-queue gives
    # (asia, smoke, tub, lung, bronc, either, xray, dysp) while repeated
    # scan-in-insertion-order gives (asia, tub, smoke, ...). Both satisfy
    # the contract, so pin the invariants and reconcile the exact tuple at
    # fold instead of gambling on one tiebreak implementation.
    assert sorted(order) == sorted(keys)
    position = {key: index for index, key in enumerate(order)}
    for edge in net.edges:
        assert position[edge.parent] < position[edge.child], edge
    assert order == net.topological_order()


def test_topological_order_respects_edges_over_insertion_order() -> None:
    # Insertion order (b, a) must not leak into the topological result.
    graphical = _graphical()
    Variable, Edge = graphical.Variable, graphical.Edge
    net = graphical.BayesNet(
        variables=(
            Variable(key="b", description="child", states=STATES),
            Variable(key="a", description="parent", states=STATES),
        ),
        edges=(Edge(parent="a", child="b"),),
        cpts={
            "a": graphical.CPT(child="a", parents=(), table=(((), (0.5, 0.5)),)),
            "b": graphical.CPT(
                child="b",
                parents=("a",),
                table=((("false",), (0.9, 0.1)), (("true",), (0.1, 0.9))),
            ),
        },
    )
    assert net.topological_order() == ("a", "b")


def test_topological_order_rejects_two_cycle() -> None:
    graphical = _graphical()
    Variable, Edge = graphical.Variable, graphical.Edge
    net = graphical.BayesNet(
        variables=(
            Variable(key="a", description="a", states=STATES),
            Variable(key="b", description="b", states=STATES),
        ),
        edges=(
            Edge(parent="a", child="b"),
            Edge(parent="b", child="a"),
        ),
        cpts={},
    )
    with pytest.raises(ValueError):
        net.topological_order()


def test_topological_order_rejects_three_cycle() -> None:
    graphical = _graphical()
    Variable, Edge = graphical.Variable, graphical.Edge
    net = graphical.BayesNet(
        variables=tuple(
            Variable(key=key, description=key, states=STATES)
            for key in ("a", "b", "c")
        ),
        edges=(
            Edge(parent="a", child="b"),
            Edge(parent="b", child="c"),
            Edge(parent="c", child="a"),
        ),
        cpts={},
    )
    with pytest.raises(ValueError):
        net.topological_order()


# ------------------------------------------ 3. GraphSpec JSON interchange ----


def test_json_round_trip_is_lossless_on_asia() -> None:
    net = _asia_net()
    restored = type(net).from_json(net.to_json())
    assert restored == net
    assert net == type(net).from_json(restored.to_json())
    # Dataclass field types survive: states and table rows are tuples.
    assert all(isinstance(v.states, tuple) for v in restored.variables)
    for cpt in restored.cpts.values():
        assert isinstance(cpt.parents, tuple)
        assert isinstance(cpt.table, tuple)
        for labels, probabilities in cpt.table:
            assert isinstance(labels, tuple)
            assert isinstance(probabilities, tuple)


def test_json_graphspec_shape_and_canonical_row_order() -> None:
    net = _asia_net()
    spec = net.to_json()
    assert spec["format"] == "dafjev.bayesnet/1"
    assert spec["variables"][0] == {
        "key": "asia",
        "description": "Recently visited Asia?",
        "states": ["false", "true"],
    }
    assert {"parent": "asia", "child": "tub"} in [
        dict(edge) for edge in spec["edges"]
    ]
    tub = spec["cpts"]["tub"]
    assert tub["child"] == "tub"
    assert tub["parents"] == ["asia"]
    assert tub["rows"] == [
        {"assignment": {"asia": "false"}, "probabilities": [0.99, 0.01]},
        {"assignment": {"asia": "true"}, "probabilities": [0.95, 0.05]},
    ]
    # Multi-parent rows follow parent-assignment lexicographic order.
    either_rows = [row["assignment"] for row in spec["cpts"]["either"]["rows"]]
    assert either_rows == [
        {"lung": "false", "tub": "false"},
        {"lung": "false", "tub": "true"},
        {"lung": "true", "tub": "false"},
        {"lung": "true", "tub": "true"},
    ]
    # Deterministic output.
    assert json.dumps(spec) == json.dumps(net.to_json())


def test_json_rejects_wrong_format_string() -> None:
    net = _asia_net()
    spec = net.to_json()
    spec["format"] = "dafjev.bayesnet/2"
    with pytest.raises(ValueError, match=r"format"):
        type(net).from_json(spec)


def test_json_rejects_missing_format_string() -> None:
    net = _asia_net()
    spec = net.to_json()
    del spec["format"]
    with pytest.raises(ValueError, match=r"format"):
        type(net).from_json(spec)


def _mutated_spec(mutate) -> dict:
    spec = _asia_net().to_json()
    mutate(spec)
    return spec


def test_json_rejects_wrong_row_count() -> None:
    def drop_a_dysp_row(spec: dict) -> None:
        del spec["cpts"]["dysp"]["rows"][0]

    with pytest.raises(ValueError, match=r"dysp"):
        type(_asia_net()).from_json(_mutated_spec(drop_a_dysp_row))


def test_json_rejects_unknown_assignment_label() -> None:
    def bogus_label(spec: dict) -> None:
        spec["cpts"]["tub"]["rows"][1]["assignment"] = {"asia": "maybe"}

    with pytest.raises(ValueError, match=r"maybe"):
        type(_asia_net()).from_json(_mutated_spec(bogus_label))


def test_json_rejects_probabilities_not_summing_to_one() -> None:
    def bad_sum(spec: dict) -> None:
        spec["cpts"]["xray"]["rows"][0]["probabilities"] = [0.5, 0.4]

    with pytest.raises(ValueError, match=r"xray"):
        type(_asia_net()).from_json(_mutated_spec(bad_sum))


def test_json_rejects_negative_probability() -> None:
    def negative(spec: dict) -> None:
        spec["cpts"]["xray"]["rows"][0]["probabilities"] = [-0.1, 1.1]

    with pytest.raises(ValueError, match=r"xray"):
        type(_asia_net()).from_json(_mutated_spec(negative))


# --------------------------------------------------- 4. exact inference ------


def _assert_posterior_matches_brute_force(
    net: Any, evidence: dict[str, str], tol: float = 1e-9
) -> None:
    expected = _brute_force_posterior(net, evidence)
    actual = net.posterior(evidence)
    assert set(actual) == set(expected)
    for key, expected_tuple in expected.items():
        assert actual[key] == pytest.approx(expected_tuple, abs=tol), key


def test_posterior_priors_match_brute_force() -> None:
    net = _asia_net()
    _assert_posterior_matches_brute_force(net, {})
    # Spot checks against the canonical values.
    assert net.posterior({})["tub"] == pytest.approx((0.9896, 0.0104), abs=1e-12)
    assert net.posterior({})["smoke"] == pytest.approx((0.5, 0.5), abs=1e-12)


def test_posterior_single_evidence_matches_brute_force() -> None:
    net = _asia_net()
    _assert_posterior_matches_brute_force(net, {"asia": "false"})
    _assert_posterior_matches_brute_force(net, {"xray": "true"})
    _assert_posterior_matches_brute_force(net, {"bronc": "true"})


def test_posterior_multi_evidence_matches_brute_force() -> None:
    net = _asia_net()
    _assert_posterior_matches_brute_force(
        net, {"asia": "false", "xray": "true", "dysp": "true"}
    )
    _assert_posterior_matches_brute_force(net, {"smoke": "true", "either": "true"})


@pytest.mark.parametrize(
    "key", ["asia", "tub", "smoke", "lung", "bronc", "either", "xray", "dysp"]
)
def test_posterior_evidence_on_every_variable_matches_brute_force(key: str) -> None:
    net = _asia_net()
    _assert_posterior_matches_brute_force(net, {key: "true"})
    _assert_posterior_matches_brute_force(net, {key: "false"})


def test_posterior_marginals_sum_to_one() -> None:
    net = _asia_net()
    for evidence in ({}, {"asia": "true"}, {"either": "true", "dysp": "false"}):
        for distribution in net.posterior(evidence).values():
            assert sum(distribution) == pytest.approx(1.0, abs=1e-9)


def test_posterior_is_deterministic() -> None:
    net = _asia_net()
    evidence = {"xray": "true"}
    first = net.posterior(evidence)
    assert net.posterior(evidence) == first
    assert net.query("tub", evidence) == first["tub"]


def test_dellaert_tub_trajectory_rises() -> None:
    # Dellaert's walkthrough: P(tub=T) rises as evidence accumulates
    # (asia=F -> +xray=T -> +dysp=T). Canonical values:
    # 0.01 -> ~0.0891 -> ~0.1100.
    net = _asia_net()
    p1 = net.query("tub", {"asia": "false"})[1]
    p2 = net.query("tub", {"asia": "false", "xray": "true"})[1]
    p3 = net.query("tub", {"asia": "false", "xray": "true", "dysp": "true"})[1]
    assert p1 == pytest.approx(0.01, abs=1e-12)
    assert p2 == pytest.approx(0.0891, abs=1e-4)
    assert p3 == pytest.approx(0.1100, abs=1e-4)
    assert p3 > p2 > p1


def test_query_defaults_to_priors() -> None:
    net = _asia_net()
    assert net.query("tub") == net.posterior({})["tub"]
    assert net.query("tub") == pytest.approx((0.9896, 0.0104), abs=1e-12)


def test_posterior_rejects_unknown_evidence_key_and_state() -> None:
    net = _asia_net()
    with pytest.raises(ValueError, match=r"venus"):
        net.posterior({"venus": "true"})
    with pytest.raises(ValueError, match=r"perhaps"):
        net.posterior({"tub": "perhaps"})
    with pytest.raises(ValueError, match=r"venus"):
        net.query("tub", {"venus": "true"})