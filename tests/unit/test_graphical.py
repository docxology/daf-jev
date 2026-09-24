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
from typing import Any, Callable

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


def _unknown_top_level_key(spec: dict) -> None:
    spec["provenance"] = {"emitted_by": "unit-test"}


def _unknown_variables_item_key(spec: dict) -> None:
    spec["variables"][0]["source"] = "wire"


def _unknown_edges_item_key(spec: dict) -> None:
    spec["edges"][0]["weight"] = 0.5


def _unknown_cpts_item_key(spec: dict) -> None:
    spec["cpts"]["tub"]["emitted_at"] = "2026-01-01T00:00:00Z"


def _unknown_row_key(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["note"] = "reordered in flight"


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_top_level_key,
        _unknown_variables_item_key,
        _unknown_edges_item_key,
        _unknown_cpts_item_key,
        _unknown_row_key,
    ],
)
def test_json_tolerates_unknown_extra_fields(
    mutate: Callable[[dict], None],
) -> None:
    net = type(_asia_net()).from_json(_mutated_spec(mutate))
    assert net == _asia_net()


@pytest.mark.parametrize("section", ["variables", "edges", "cpts"])
def test_json_rejects_missing_section(section: str) -> None:
    def drop_section(spec: dict) -> None:
        del spec[section]

    with pytest.raises(ValueError, match=rf"missing required key: '{section}'"):
        type(_asia_net()).from_json(_mutated_spec(drop_section))


def _variables_not_a_list(spec: dict) -> None:
    spec["variables"] = {"asia": list(STATES)}


def _edges_not_a_list(spec: dict) -> None:
    spec["edges"] = "asia->tub"


def _cpts_not_a_dict(spec: dict) -> None:
    spec["cpts"] = [("tub", {"child": "tub", "parents": [], "rows": []})]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _variables_not_a_list,
            r"GraphSpec variables must be a list, got dict",
        ),
        (_edges_not_a_list, r"GraphSpec edges must be a list, got str"),
        (_cpts_not_a_dict, r"GraphSpec cpts must be a dict, got list"),
    ],
)
def test_json_rejects_wrong_section_container(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _variables_item_not_a_dict(spec: dict) -> None:
    spec["variables"][0] = "asia"


def _edges_item_not_a_dict(spec: dict) -> None:
    spec["edges"][0] = ["asia", "tub"]


def _cpt_row_not_a_dict(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0] = "asia=false"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _variables_item_not_a_dict,
            r"GraphSpec variables\[0\] must be a dict, got str",
        ),
        (
            _edges_item_not_a_dict,
            r"GraphSpec edges\[0\] must be a dict, got list",
        ),
        (
            _cpt_row_not_a_dict,
            r"GraphSpec cpts\['tub'\]\.rows\[0\] must be a dict, got str",
        ),
    ],
)
def test_json_rejects_non_dict_item(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _variable_key_not_a_string(spec: dict) -> None:
    spec["variables"][0]["key"] = 7


def _variable_description_not_a_string(spec: dict) -> None:
    spec["variables"][0]["description"] = None


def _variable_states_not_a_list(spec: dict) -> None:
    spec["variables"][0]["states"] = "false"


def _variable_states_with_non_string(spec: dict) -> None:
    spec["variables"][0]["states"] = ["false", 1]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _variable_key_not_a_string,
            r"variables\[0\]\.key must be a string, got 7",
        ),
        (
            _variable_description_not_a_string,
            r"variables\[0\]\.description must be a string, got NoneType",
        ),
        (
            _variable_states_not_a_list,
            r"variables\[0\]\.states must be a list of strings, got 'false'",
        ),
        (
            _variable_states_with_non_string,
            r"variables\[0\]\.states must be a list of strings, got \['false', 1\]",
        ),
    ],
)
def test_json_rejects_variable_field_type_error(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _edge_parent_not_a_string(spec: dict) -> None:
    spec["edges"][0]["parent"] = 7


def _edge_child_not_a_string(spec: dict) -> None:
    spec["edges"][0]["child"] = 7


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _edge_parent_not_a_string,
            r"parent and child must be strings, got parent=7 child='tub'",
        ),
        (
            _edge_child_not_a_string,
            r"parent and child must be strings, got parent='asia' child=7",
        ),
    ],
)
def test_json_rejects_non_string_edge_endpoint(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _cpt_child_mismatch(spec: dict) -> None:
    spec["cpts"]["tub"]["child"] = "lung"


def _cpt_parents_not_a_list(spec: dict) -> None:
    spec["cpts"]["xray"]["parents"] = "either"


def _cpt_parents_with_non_string(spec: dict) -> None:
    spec["cpts"]["xray"]["parents"] = ["either", 1]


def _cpt_rows_not_a_list(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"] = {"first": {}}


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _cpt_child_mismatch,
            r"cpts\['tub'\]\.child must be 'tub', got 'lung'",
        ),
        (
            _cpt_parents_not_a_list,
            r"cpts\['xray'\]\.parents must be a list of strings, got 'either'",
        ),
        (
            _cpt_parents_with_non_string,
            r"cpts\['xray'\]\.parents must be a list of strings, got \['either', 1\]",
        ),
        (_cpt_rows_not_a_list, r"cpts\['tub'\]\.rows must be a list, got dict"),
    ],
)
def test_json_rejects_malformed_cpt_entry(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _row_assignment_not_a_dict(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["assignment"] = "asia=false"


def _row_assignment_outside_parents(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["assignment"] = {"lung": "true"}


def _row_assignment_missing_parent(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["assignment"] = {}


def _row_probabilities_not_a_list(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["probabilities"] = "0.5"


def _row_probability_bool(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["probabilities"] = [True, 0.01]


def _row_probability_string(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"][0]["probabilities"] = ["0.5", 0.5]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _row_assignment_not_a_dict,
            r"cpts\['tub'\]\.rows\[0\]\.assignment must be a dict, got str",
        ),
        (
            _row_assignment_outside_parents,
            r"cpts\['tub'\]\.rows\[0\]\.assignment names variables outside parents",
        ),
        (
            _row_assignment_missing_parent,
            r"cpts\['tub'\]\.rows\[0\]\.assignment is missing parents \['asia'\]",
        ),
        (
            _row_probabilities_not_a_list,
            r"cpts\['tub'\]\.rows\[0\]\.probabilities must be a list of numbers, "
            r"got '0\.5'",
        ),
        (
            _row_probability_bool,
            r"cpts\['tub'\]\.rows\[0\]\.probabilities\[0\] must be a number, got True",
        ),
        (
            _row_probability_string,
            r"cpts\['tub'\]\.rows\[0\]\.probabilities\[0\] must be a number, "
            r"got '0\.5'",
        ),
    ],
)
def test_json_rejects_malformed_cpt_row(
    mutate: Callable[[dict], None], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def _cpts_entry_for_unknown_variable(spec: dict) -> None:
    spec["cpts"]["bogus"] = {"child": "bogus", "parents": [], "rows": []}


def _cpts_missing_entry(spec: dict) -> None:
    del spec["cpts"]["dysp"]


def _cpts_entry_with_no_rows(spec: dict) -> None:
    spec["cpts"]["tub"]["rows"] = []


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            _cpts_entry_for_unknown_variable,
            r"CPT stored under unknown variable key 'bogus'",
        ),
        (_cpts_missing_entry, r"missing CPT for variable 'dysp'"),
        (
            _cpts_entry_with_no_rows,
            r"CPT for 'tub' must have exactly 2 rows .* got 0",
        ),
    ],
)
def test_json_rejects_validation_stage_cpt_shape(
    mutate: Callable[[dict], None], match: str
) -> None:
    # These shapes pass JSON parsing and surface from the net-level
    # validation that from_json runs after construction.
    with pytest.raises(ValueError, match=match):
        type(_asia_net()).from_json(_mutated_spec(mutate))


def test_json_keeps_rows_as_given_and_resorts_on_reserialize() -> None:
    def shuffle(spec: dict) -> None:
        dysp_rows = spec["cpts"]["dysp"]["rows"]
        spec["cpts"]["dysp"]["rows"] = list(reversed(dysp_rows))
        tub_rows = spec["cpts"]["tub"]["rows"]
        spec["cpts"]["tub"]["rows"] = [tub_rows[1], tub_rows[0]]

    net_cls = type(_asia_net())
    canonical = _asia_net()
    shuffled = net_cls.from_json(_mutated_spec(shuffle))
    # Rows are kept in wire order, so the net is not the canonical one.
    assert shuffled != canonical
    # dysp wire order is the canonical order reversed: first row is (T, T).
    assert shuffled.cpts["dysp"].table[0][0] == ("true", "true")
    assert shuffled.cpts["dysp"].table == tuple(reversed(canonical.cpts["dysp"].table))
    # tub wire order is the canonical order swapped: first row is (T,).
    assert shuffled.cpts["tub"].table[0][0] == ("true",)
    assert shuffled.cpts["tub"].table == canonical.cpts["tub"].table[::-1]
    # to_json re-sorts rows into canonical order, so a re-parse restores
    # the canonical net exactly.
    assert net_cls.from_json(shuffled.to_json()) == canonical


def test_json_coerces_integer_probabilities_to_float() -> None:
    def integer_probs(spec: dict) -> None:
        spec["cpts"]["tub"]["rows"][0]["probabilities"] = [1, 0]

    net = type(_asia_net()).from_json(_mutated_spec(integer_probs))
    probabilities = net.cpts["tub"].table[0][1]
    assert all(isinstance(p, float) for p in probabilities)
    assert probabilities == (1.0, 0.0)




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


# ------------------------------- 5. single-parent decomposition --------------


# decompose_single_parent() rewrites every multi-parent CPT into a chain of
# deterministic auxiliary variables. The contract is the joint distribution
# over the ORIGINAL variables; auxiliary marginals are deterministic
# bookkeeping, NOT elicited beliefs, so every equivalence check below compares
# the decomposed net against the untouched original net — never against the
# helper's own re-derived numbers.

ORIGINAL_KEYS = ("p1", "p2", "p3", "X", "w")

EVIDENCE_CASES: tuple[dict[str, str], ...] = (
    {},
    {"p1": "a"},
    {"p3": "z"},
    {"p1": "b", "p3": "y"},
)


def _prior(key: str, probabilities: tuple[float, ...]):
    """A CPT with no parents: one row over the child's states."""
    graphical = _graphical()
    return graphical.CPT(key, (), (((), probabilities),))


def _table(
    child: str,
    parents: tuple[str, ...],
    rows: list[tuple[tuple[str, ...], tuple[float, ...]]],
):
    graphical = _graphical()
    return graphical.CPT(
        child,
        parents,
        tuple(
            (tuple(assignment), tuple(probabilities))
            for assignment, probabilities in rows
        ),
    )


def _three_parent_net():
    """p1 -> p2; p1, p2, p3 -> X; p3 -> w. X carries the 3-parent CPT."""
    graphical = _graphical()
    net = graphical.BayesNet(
        (
            graphical.Variable("p1", "parent one", ("a", "b")),
            graphical.Variable("p2", "parent two", ("yes", "no")),
            graphical.Variable("p3", "parent three", ("x", "y", "z")),
            graphical.Variable("X", "three-parent child", ("low", "high")),
            graphical.Variable("w", "single-parent child", ("m", "n")),
        ),
        (
            graphical.Edge("p1", "p2"),
            graphical.Edge("p1", "X"),
            graphical.Edge("p2", "X"),
            graphical.Edge("p3", "X"),
            graphical.Edge("p3", "w"),
        ),
        {
            "p1": _prior("p1", (0.3, 0.7)),
            "p2": _table(
                "p2", ("p1",), [(("a",), (0.6, 0.4)), (("b",), (0.2, 0.8))]
            ),
            "p3": _prior("p3", (0.5, 0.3, 0.2)),
            "X": _table(
                "X",
                ("p1", "p2", "p3"),
                [
                    (("a", "yes", "x"), (0.9, 0.1)),
                    (("a", "yes", "y"), (0.4, 0.6)),
                    (("a", "yes", "z"), (0.25, 0.75)),
                    (("a", "no", "x"), (0.55, 0.45)),
                    (("a", "no", "y"), (0.1, 0.9)),
                    (("a", "no", "z"), (0.35, 0.65)),
                    (("b", "yes", "x"), (0.05, 0.95)),
                    (("b", "yes", "y"), (0.6, 0.4)),
                    (("b", "yes", "z"), (0.8, 0.2)),
                    (("b", "no", "x"), (0.45, 0.55)),
                    (("b", "no", "y"), (0.7, 0.3)),
                    (("b", "no", "z"), (0.15, 0.85)),
                ],
            ),
            "w": _table(
                "w",
                ("p3",),
                [
                    (("x",), (0.25, 0.75)),
                    (("y",), (0.5, 0.5)),
                    (("z",), (0.7, 0.3)),
                ],
            ),
        },
    )
    net.validate()
    return net


def _single_parent_net():
    """A strictly single-parent net: decompose must be a pure copy."""
    graphical = _graphical()
    net = graphical.BayesNet(
        (
            graphical.Variable("root", "root", ("0", "1")),
            graphical.Variable("leaf", "leaf", ("0", "1")),
        ),
        (graphical.Edge("root", "leaf"),),
        {
            "root": _prior("root", (0.35, 0.65)),
            "leaf": _table(
                "leaf", ("root",), [(("0",), (0.8, 0.2)), (("1",), (0.1, 0.9))]
            ),
        },
    )
    net.validate()
    return net


def _assert_original_posteriors_match(
    net: Any, dec: Any, evidence: dict[str, str], keys: tuple[str, ...]
) -> None:
    before = net.posterior(evidence)
    after = dec.posterior(evidence)
    for key in keys:
        assert after[key] == pytest.approx(before[key], abs=1e-12)


def _assert_point_masses(dec: Any, key: str) -> None:
    for _, probabilities in dec.cpts[key].table:
        assert probabilities.count(1.0) == 1
        assert all(value == 0.0 for value in probabilities if value != 1.0)


def test_decompose_three_parent_structure() -> None:
    net = _three_parent_net()
    dec = _graphical().decompose_single_parent(net)
    dec.validate()

    assert dec.parents_of("X") == ("X__aux3",)
    assert dec.cpts["X"].parents == ("X__aux3",)
    assert dec.parents_of("X__aux1") == ("p1",)
    assert dec.parents_of("X__aux2") == ("X__aux1", "p2")
    assert dec.parents_of("X__aux3") == ("X__aux2", "p3")
    assert dec.variable("X__aux1").states == ("0", "1")
    assert dec.variable("X__aux2").states == ("0,0", "0,1", "1,0", "1,1")
    assert dec.variable("X__aux3").states == tuple(
        f"{i},{j},{k}" for i, j, k in product(range(2), range(2), range(3))
    )
    assert (
        dec.variable("X__aux2").description
        == "deterministic joint state of (p1, p2) for X"
    )
    for key in ORIGINAL_KEYS:
        assert dec.variable(key).states == net.variable(key).states
    assert dec.cpts["w"] == net.cpts["w"]
    for aux_key in ("X__aux1", "X__aux2", "X__aux3"):
        _assert_point_masses(dec, aux_key)
    assert dict(dec.cpts["X"].table)[("1,0,2",)] == (0.8, 0.2)

    expected_edges = {
        ("p1", "p2"),
        ("p3", "w"),
        ("p1", "X__aux1"),
        ("X__aux1", "X__aux2"),
        ("p2", "X__aux2"),
        ("X__aux2", "X__aux3"),
        ("p3", "X__aux3"),
        ("X__aux3", "X"),
    }
    actual = {(edge.parent, edge.child) for edge in dec.edges}
    assert actual == expected_edges
    assert len(dec.edges) == len(expected_edges)
    assert tuple(var.key for var in dec.variables) == (
        "p1",
        "p2",
        "p3",
        "X",
        "w",
        "X__aux1",
        "X__aux2",
        "X__aux3",
    )


@pytest.mark.parametrize("evidence", EVIDENCE_CASES)
def test_decompose_preserves_joint_over_originals(evidence: dict[str, str]) -> None:
    net = _three_parent_net()
    dec = _graphical().decompose_single_parent(net)
    _assert_original_posteriors_match(net, dec, evidence, ORIGINAL_KEYS)
    assert dec.query("X", evidence) == pytest.approx(
        net.query("X", evidence), abs=1e-12
    )


def test_decompose_is_deterministic() -> None:
    net = _three_parent_net()
    decompose = _graphical().decompose_single_parent
    first = decompose(net)
    second = decompose(net)
    assert first is not second
    assert first == second


def test_decomposed_net_graphspec_round_trips() -> None:
    net = _three_parent_net()
    dec = _graphical().decompose_single_parent(net)
    back = type(dec).from_json(dec.to_json())
    assert back == dec
    for evidence in EVIDENCE_CASES:
        _assert_original_posteriors_match(net, back, evidence, ORIGINAL_KEYS)


def test_decompose_nested_multi_parent_asia() -> None:
    # Asia nests: `either` is multi-parent (lung, tub) and feeds the
    # multi-parent `dysp` (either, bronc), so one decompose pass must clean
    # up both levels while leaving the joint over the 8 original variables
    # untouched.
    net = _asia_net()
    dec = _graphical().decompose_single_parent(net)
    dec.validate()

    original_keys = tuple(var.key for var in net.variables)
    for key in original_keys:
        assert len(dec.parents_of(key)) <= 1
        assert dec.variable(key).states == net.variable(key).states

    # Asia has no key collisions, so the aux names are the plain scheme.
    for aux_key in ("either__aux1", "either__aux2", "dysp__aux1", "dysp__aux2"):
        assert aux_key in dec.cpts
    assert dec.parents_of("either") == ("either__aux2",)
    assert dec.parents_of("dysp") == ("dysp__aux2",)

    for evidence in (
        {},
        {"asia": "false"},
        {"xray": "true"},
        {"asia": "false", "dysp": "true"},
    ):
        _assert_original_posteriors_match(net, dec, evidence, original_keys)


def test_decompose_single_parent_net_returns_equivalent_copy() -> None:
    net = _single_parent_net()
    dec = _graphical().decompose_single_parent(net)
    assert dec is not net
    assert dec == net
    assert dec.cpts is not net.cpts
    assert dec.variables == net.variables
    assert dec.edges == net.edges


def test_decompose_rejects_non_bayesnet() -> None:
    with pytest.raises(TypeError, match=r"BayesNet"):
        _graphical().decompose_single_parent({"variables": []})  # type: ignore[arg-type]