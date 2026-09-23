"""Discrete Bayesian networks over Jev-elicited factors, with exact
inference and the GraphSpec interchange format.

Four frozen dataclasses — :class:`Variable`, :class:`Edge`, :class:`CPT`,
:class:`BayesNet` — model a discrete Bayes net. Construction is permissive;
:meth:`BayesNet.validate` checks the full contract (naming the offending
key on failure). :meth:`BayesNet.posterior` / :meth:`BayesNet.query` run
exact variable elimination in pure stdlib floats — no numpy — with
deterministic tiebreaks, so identical inputs give identical results.
:meth:`BayesNet.to_json` / :meth:`BayesNet.from_json` project to and from
the ``dafjev.bayesnet/1`` GraphSpec, the cross-repo interchange consumed by
the GNN bridge and the RxInfer.jl example (changing the format string is a
cross-repo contract change).

Jev feeds this engine upstream: :mod:`daf_jev.graphical_elicitation`
elicitates CPTs and proposes structure through the public client API; the
elicited factors then answer evidence queries here — upstream (structure +
CPTs), within (factors), downstream (queries / re-asking).
"""

from __future__ import annotations

import dataclasses
import heapq
import itertools
import math
import random
import re
from collections.abc import Mapping, Sequence

__all__ = [
    "CPT",
    "GRAPH_SPEC_FORMAT",
    "BayesNet",
    "Edge",
    "Variable",
]

GRAPH_SPEC_FORMAT = "dafjev.bayesnet/1"

_KEY_PATTERN = r"[A-Za-z_][A-Za-z0-9_-]*"
_ROW_SUM_TOLERANCE = 1e-6

# A discrete factor: (scope tuple of variable keys, table mapping every
# assignment tuple of state labels over that scope to its probability).
_Factor = tuple[tuple[str, ...], dict[tuple[str, ...], float]]


@dataclasses.dataclass(frozen=True)
class Variable:
    """One discrete random variable of the network.

    ``key`` is the unique identifier and must match
    ``[A-Za-z_][A-Za-z0-9_-]*`` (question ids and the GraphSpec JSON rely
    on it). ``description`` is the natural-language meaning that drives
    elicitation. ``states`` are the ordered outcome labels — at least two,
    referenced by position in every distribution.
    """

    key: str
    description: str
    states: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Edge:
    """One directed ``parent`` -> ``child`` edge of the network."""

    parent: str
    child: str


@dataclasses.dataclass(frozen=True)
class CPT:
    """Conditional probability table for one child variable.

    ``parents`` lists the graph parents in order (empty tuple = a prior).
    Each ``table`` row is an ``(assignment, probabilities)`` pair:
    ``assignment`` holds one state label per parent in ``parents`` order,
    and ``probabilities`` holds one probability per child state, in the
    child's :attr:`Variable.states` order. Every parent assignment appears
    exactly once; rows are stored as given (renormalization is the
    caller's choice).
    """

    child: str
    parents: tuple[str, ...]
    table: tuple[tuple[tuple[str, ...], tuple[float, ...]], ...]


@dataclasses.dataclass(frozen=True)
class BayesNet:
    """A discrete Bayesian network over named variables.

    ``variables`` are unique :class:`Variable` entries, ``edges`` the
    directed DAG, and ``cpts`` maps each child key to its :class:`CPT`.
    Construction is permissive — a structure-only net (empty ``cpts``) is
    legal input to the two-step flow (:meth:`propose_structure` then
    ``elicit_cpts``, in :mod:`daf_jev.graphical_elicitation`) but does not
    satisfy :meth:`validate`. Inference (:meth:`posterior`, :meth:`query`)
    requires a validated net and fails closed otherwise.
    """

    variables: tuple[Variable, ...]
    edges: tuple[Edge, ...]
    cpts: Mapping[str, CPT]

    def variable(self, key: str) -> Variable:
        """Return the variable for ``key``; ``KeyError`` names it otherwise."""
        for var in self.variables:
            if var.key == key:
                return var
        raise KeyError(f"unknown variable {key!r}")

    def parents_of(self, key: str) -> tuple[str, ...]:
        """Parents of ``key`` in edge order; ``KeyError`` for unknown keys."""
        self.variable(key)
        return tuple(edge.parent for edge in self.edges if edge.child == key)

    def children_of(self, key: str) -> tuple[str, ...]:
        """Children of ``key`` in edge order; ``KeyError`` for unknown keys."""
        self.variable(key)
        return tuple(edge.child for edge in self.edges if edge.parent == key)

    def topological_order(self) -> tuple[str, ...]:
        """Deterministic topological order of the variable keys.

        Kahn's algorithm with an insertion-order tiebreak: among the
        currently ready variables the one declared earliest in
        ``variables`` goes first, so identical inputs give identical
        orders. Raises ``ValueError`` naming the stuck variables when the
        edges contain a cycle.
        """
        for var in self.variables:
            if not isinstance(var.key, str):
                raise ValueError(f"variable key must be a string, got {var.key!r}")
        seen: set[str] = set()
        for var in self.variables:
            if var.key in seen:
                raise ValueError(f"duplicate variable key {var.key!r}")
            seen.add(var.key)
        index_of = {var.key: index for index, var in enumerate(self.variables)}
        children: dict[str, list[str]] = {var.key: [] for var in self.variables}
        indegree = {var.key: 0 for var in self.variables}
        for edge in self.edges:
            for endpoint in (edge.parent, edge.child):
                if endpoint not in index_of:
                    raise ValueError(
                        f"edge {edge.parent!r} -> {edge.child!r} references "
                        f"unknown variable {endpoint!r}"
                    )
            children[edge.parent].append(edge.child)
            indegree[edge.child] += 1
        heap = [index_of[key] for key, degree in indegree.items() if degree == 0]
        heapq.heapify(heap)
        order: list[str] = []
        while heap:
            key = self.variables[heapq.heappop(heap)].key
            order.append(key)
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    heapq.heappush(heap, index_of[child])
        if len(order) != len(self.variables):
            emitted = set(order)
            stuck = [var.key for var in self.variables if var.key not in emitted]
            raise ValueError(f"graph contains a cycle involving variables {stuck}")
        return tuple(order)

    def validate(self) -> None:
        """Check the full network contract, raising ``ValueError`` naming
        the offending key otherwise.

        Checks: variable keys match ``[A-Za-z_][A-Za-z0-9_-]*`` and are
        unique; each variable carries a string description and >= 2
        distinct state labels; edges reference known variables, with no
        self-loops or duplicates; every variable has exactly one CPT
        stored under its own key; CPT parents equal the graph parents
        (same set, order asserted); every parent assignment appears
        exactly once, with one finite, non-negative probability per child
        state, each row summing to 1 within ``1e-6``. Rows are stored as
        given — renormalization is the caller's choice.
        """
        seen: set[str] = set()
        for index, var in enumerate(self.variables):
            if not isinstance(var, Variable):
                raise ValueError(
                    f"variables[{index}] must be a Variable, got {type(var).__name__}"
                )
            if not isinstance(var.key, str) or re.fullmatch(_KEY_PATTERN, var.key) is None:
                raise ValueError(
                    f"variable key must match {_KEY_PATTERN}, got {var.key!r}"
                )
            if var.key in seen:
                raise ValueError(f"duplicate variable key {var.key!r}")
            seen.add(var.key)
            if not isinstance(var.description, str):
                raise ValueError(
                    f"variable {var.key!r} description must be a string, "
                    f"got {type(var.description).__name__}"
                )
            states = var.states
            if not isinstance(states, tuple) or len(states) < 2:
                raise ValueError(
                    f"variable {var.key!r} states must be a tuple of >= 2 labels, "
                    f"got {states!r}"
                )
            bad = [state for state in states if not isinstance(state, str) or not state]
            if bad:
                raise ValueError(
                    f"variable {var.key!r} states must all be non-empty strings; "
                    f"offending labels: {bad}"
                )
            if len(set(states)) != len(states):
                raise ValueError(
                    f"variable {var.key!r} has duplicate state labels: {states!r}"
                )
        edge_keys: set[tuple[str, str]] = set()
        for index, edge in enumerate(self.edges):
            if not isinstance(edge, Edge):
                raise ValueError(
                    f"edges[{index}] must be an Edge, got {type(edge).__name__}"
                )
            if not isinstance(edge.parent, str) or not isinstance(edge.child, str):
                raise ValueError(
                    f"edge endpoints must be strings, got parent={edge.parent!r} "
                    f"child={edge.child!r}"
                )
            for endpoint in (edge.parent, edge.child):
                if endpoint not in seen:
                    raise ValueError(
                        f"edge {edge.parent!r} -> {edge.child!r} references "
                        f"unknown variable {endpoint!r}"
                    )
            if edge.parent == edge.child:
                raise ValueError(
                    f"edge {edge.parent!r} -> {edge.child!r} is a self-loop"
                )
            pair = (edge.parent, edge.child)
            if pair in edge_keys:
                raise ValueError(f"duplicate edge {edge.parent!r} -> {edge.child!r}")
            edge_keys.add(pair)
        if not isinstance(self.cpts, Mapping):
            raise ValueError(
                f"cpts must be a mapping of child key -> CPT, "
                f"got {type(self.cpts).__name__}"
            )
        for key in self.cpts:
            if not isinstance(key, str):
                raise ValueError(f"CPT mapping key must be a string, got {key!r}")
        for key in sorted(self.cpts):
            cpt = self.cpts[key]
            if not isinstance(cpt, CPT):
                raise ValueError(
                    f"cpts[{key!r}] must be a CPT, got {type(cpt).__name__}"
                )
            if key not in seen:
                raise ValueError(f"CPT stored under unknown variable key {key!r}")
            if cpt.child != key:
                raise ValueError(
                    f"CPT stored under key {key!r} declares child {cpt.child!r}"
                )
        for var in self.variables:
            self._validate_cpt(var)

    def _validate_cpt(self, var: Variable) -> None:
        """Check one variable's CPT structure against the graph and itself."""
        cpt = self.cpts.get(var.key)
        if cpt is None:
            raise ValueError(f"missing CPT for variable {var.key!r}")
        if not isinstance(cpt.parents, tuple) or not all(
            isinstance(parent, str) for parent in cpt.parents
        ):
            raise ValueError(
                f"CPT for {var.key!r} parents must be a tuple of variable keys, "
                f"got {cpt.parents!r}"
            )
        parents = self.parents_of(var.key)
        if tuple(cpt.parents) != parents:
            raise ValueError(
                f"CPT for {var.key!r} parents {tuple(cpt.parents)!r} do not "
                f"match graph parents {parents!r}"
            )
        if not isinstance(cpt.table, tuple):
            raise ValueError(
                f"CPT for {var.key!r} table must be a tuple of rows, "
                f"got {type(cpt.table).__name__}"
            )
        expected = list(itertools.product(*(self.variable(p).states for p in parents)))
        if len(cpt.table) != len(expected):
            raise ValueError(
                f"CPT for {var.key!r} must have exactly {len(expected)} rows "
                f"(one per parent assignment), got {len(cpt.table)}"
            )
        seen_assignments: set[tuple[str, ...]] = set()
        for row_index, row in enumerate(cpt.table):
            if not isinstance(row, tuple) or len(row) != 2:
                raise ValueError(
                    f"CPT for {var.key!r} row {row_index} must be an "
                    f"(assignment, probabilities) tuple, got {row!r}"
                )
            assignment, probabilities = row
            if (
                not isinstance(assignment, tuple)
                or len(assignment) != len(parents)
                or not all(isinstance(label, str) for label in assignment)
            ):
                raise ValueError(
                    f"CPT for {var.key!r} row {row_index} assignment must be a "
                    f"tuple of {len(parents)} state labels over parents "
                    f"{parents!r}, got {assignment!r}"
                )
            for parent, label in zip(parents, assignment, strict=True):
                if label not in self.variable(parent).states:
                    raise ValueError(
                        f"CPT for {var.key!r}: parent {parent!r} has no state "
                        f"{label!r}"
                    )
            if assignment in seen_assignments:
                raise ValueError(
                    f"CPT for {var.key!r} has duplicate parent assignment "
                    f"{assignment!r}"
                )
            seen_assignments.add(assignment)
            if not isinstance(probabilities, tuple) or len(probabilities) != len(
                var.states
            ):
                raise ValueError(
                    f"CPT for {var.key!r} row {assignment!r} must carry exactly "
                    f"{len(var.states)} probabilities (child states "
                    f"{var.states!r}), got {probabilities!r}"
                )
            for position, probability in enumerate(probabilities):
                if isinstance(probability, bool) or not isinstance(
                    probability, (int, float)
                ):
                    raise ValueError(
                        f"CPT for {var.key!r} row {assignment!r} probability "
                        f"{position} must be a number, got {probability!r}"
                    )
                if not math.isfinite(probability):
                    raise ValueError(
                        f"CPT for {var.key!r} row {assignment!r} probability "
                        f"{position} must be finite, got {probability!r}"
                    )
                if probability < 0:
                    raise ValueError(
                        f"CPT for {var.key!r} row {assignment!r} probability "
                        f"{position} must be >= 0, got {probability!r}"
                    )
            total = math.fsum(probabilities)
            if abs(total - 1.0) > _ROW_SUM_TOLERANCE:
                raise ValueError(
                    f"CPT for {var.key!r} row {assignment!r} probabilities sum "
                    f"to {total!r}, expected 1 within {_ROW_SUM_TOLERANCE}"
                )

    def to_json(self) -> dict:
        """Project the net to a ``dafjev.bayesnet/1`` GraphSpec document.

        CPT rows are emitted in canonical order — parent assignments
        lexicographic by each parent's :attr:`Variable.states` order. The
        projection is faithful, not validating: a structure-only net
        serializes with an empty ``cpts`` mapping (loading such a document
        back raises via :meth:`from_json`).
        """
        variables = [
            {
                "key": var.key,
                "description": var.description,
                "states": list(var.states),
            }
            for var in self.variables
        ]
        edges = [{"parent": edge.parent, "child": edge.child} for edge in self.edges]
        cpts: dict[str, dict] = {}
        for var in self.variables:
            cpt = self.cpts.get(var.key)
            if cpt is None:
                continue
            rank = {
                parent: {
                    state: index
                    for index, state in enumerate(self.variable(parent).states)
                }
                for parent in cpt.parents
            }
            parents = cpt.parents
            keyed = sorted(
                (
                    (
                        tuple(
                            rank[name][label]
                            for name, label in zip(parents, row[0], strict=True)
                        ),
                        row,
                    )
                    for row in cpt.table
                ),
            )
            cpts[var.key] = {
                "child": cpt.child,
                "parents": list(parents),
                "rows": [
                    {
                        "assignment": dict(zip(parents, assignment, strict=True)),
                        "probabilities": list(probabilities),
                    }
                    for _, (assignment, probabilities) in keyed
                ],
            }
        return {
            "format": GRAPH_SPEC_FORMAT,
            "variables": variables,
            "edges": edges,
            "cpts": cpts,
        }

    @classmethod
    def from_json(cls, data: dict) -> BayesNet:
        """Parse a ``dafjev.bayesnet/1`` GraphSpec document into a net.

        Requires the exact format string and all three sections; rows may
        arrive in any order and are kept as given. The resulting net is
        validated, so malformed shapes (wrong row counts, unknown
        assignment labels, negative, non-finite, or non-summing
        probabilities) raise ``ValueError`` naming the offending key.
        Unknown extra fields are tolerated and ignored, as in the wire
        response parser.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"GraphSpec payload must be a dict, got {type(data).__name__}"
            )
        if data.get("format") != GRAPH_SPEC_FORMAT:
            raise ValueError(
                f"GraphSpec format must be {GRAPH_SPEC_FORMAT!r}, "
                f"got {data.get('format')!r}"
            )
        for section in ("variables", "edges", "cpts"):
            if section not in data:
                raise ValueError(f"GraphSpec is missing required key: {section!r}")
        net = cls(
            tuple(_variables_from_json(data["variables"])),
            tuple(_edges_from_json(data["edges"])),
            _cpts_from_json(data["cpts"]),
        )
        net.validate()
        return net

    def posterior(self, evidence: Mapping[str, str]) -> dict[str, tuple[float, ...]]:
        """Exact posterior marginal for every variable given ``evidence``.

        Variable elimination over discrete factors in pure stdlib floats:
        evidence reduces each CPT factor, hidden variables are summed out
        in :meth:`topological_order` order, and each marginal is
        normalized by a single division at the end. Evidence variables map
        to indicator distributions at their observed state. Returns one
        distribution per variable, aligned with :attr:`Variable.states`;
        empty ``evidence`` yields the priors. Unknown evidence keys or
        states raise ``ValueError``, as does zero-probability evidence
        (the posterior is undefined there).
        """
        checked, domains, factors, order = self._prepare(evidence)
        marginals = {
            var.key: self._marginal(var, checked, domains, factors, order)
            for var in self.variables
        }
        self._guard_fully_observed(checked, factors, evidence)
        return marginals

    def query(
        self, variable: str, evidence: Mapping[str, str] | None = None
    ) -> tuple[float, ...]:
        """Posterior marginal for one ``variable`` (see :meth:`posterior`).

        ``None`` evidence yields the prior. An evidence variable's
        marginal is its indicator at the observed state.
        """
        checked, domains, factors, order = self._prepare(
            {} if evidence is None else evidence
        )
        marginal = self._marginal(
            self.variable(variable), checked, domains, factors, order
        )
        self._guard_fully_observed(checked, factors, evidence or {})
        return marginal

    def most_probable_explanation(self, evidence: Mapping[str, str]) -> dict[str, str]:
        """Most probable explanation: the single joint assignment over ALL
        variables with the highest probability consistent with ``evidence``.

        Every assignment consistent with the evidence is enumerated and
        scored as the product of its CPT entries — complexity grows with
        the product of the state counts (2**n for binary nets), so this
        targets small nets (n <= 12). Exhaustive enumeration is what makes
        the tiebreak exact: among assignments achieving the maximum
        probability, the lexicographically smallest tuple of state labels
        in variable-declaration order wins, so identical inputs give
        identical results. Evidence variables are pinned to their observed
        states in the returned mapping. Unknown evidence keys or states
        raise ``ValueError`` as in :meth:`posterior`, as does
        zero-probability evidence (no assignment consistent with it has
        positive probability).
        """
        self.validate()
        checked = self._checked_evidence(evidence)
        keys = tuple(var.key for var in self.variables)
        index_of = {key: index for index, key in enumerate(keys)}
        domains = [
            (checked[var.key],) if var.key in checked else var.states
            for var in self.variables
        ]
        scored = [
            (tuple(index_of[name] for name in scope), table)
            for scope, table in (self._factor_of(var) for var in self.variables)
        ]
        best_probability = -1.0
        best: tuple[str, ...] | None = None
        for combo in itertools.product(*domains):
            probability = 1.0
            for positions, table in scored:
                probability *= table[tuple(combo[i] for i in positions)]
                if probability <= 0.0:
                    break
            if probability > best_probability or (
                probability == best_probability and best is not None and combo < best
            ):
                best_probability = probability
                best = combo
        if best is None or best_probability <= 0.0:
            raise ValueError(
                f"evidence {dict(evidence)!r} has zero probability; "
                "the most probable explanation is undefined"
            )
        return dict(zip(keys, best, strict=True))

    def _guard_fully_observed(
        self,
        checked: Mapping[str, str],
        factors: list[_Factor],
        evidence: Mapping[str, str],
    ) -> None:
        """Raise when the evidence is fully observed AND inconsistent.

        Observed variables short-circuit to indicator marginals before the
        zero-total check in ``_marginal`` can run, so a fully-observed
        inconsistent case would silently normalize fabricated indicators.
        With at least one hidden variable, that hidden marginal's
        zero-total check covers the whole evidence mass.
        """
        if len(checked) != len(self.variables):
            return
        domains = {
            var.key: (checked[var.key],) if var.key in checked else var.states
            for var in self.variables
        }
        _scope, table = _fold_multiply(list(factors), domains)
        if math.fsum(table.values()) <= 0.0:
            raise ValueError(
                f"evidence {dict(evidence)!r} has zero probability; "
                "the posterior is undefined"
            )

    def sample(self, n: int, rng: random.Random | None = None) -> list[dict[str, str]]:
        """Draw ``n`` joint assignments by ancestral sampling.

        Variables are drawn in :meth:`topological_order` order; each
        state is a categorical draw over its CPT row given the
        already-drawn parent states, via ``rng.random()`` against the
        row's cumulative distribution. ``rng`` defaults to a fresh
        :class:`random.Random`; pass a seeded instance for reproducible
        draws. ``n`` must be an integer >= 1. Rows are used as stored
        (summing to 1 within the :meth:`validate` tolerance); a
        float-rounding guard falls back to the last state with positive
        probability. No evidence handling — rejection sampling is
        caller-composed (draw, then keep the draws consistent with the
        wanted evidence).
        """
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError(f"n must be an integer >= 1, got {n!r}")
        self.validate()
        generator = random.Random() if rng is None else rng
        order = self.topological_order()
        states = {var.key: var.states for var in self.variables}
        rows = {var.key: dict(self.cpts[var.key].table) for var in self.variables}
        parents = {var.key: self.cpts[var.key].parents for var in self.variables}
        draws: list[dict[str, str]] = []
        for _ in range(n):
            values: dict[str, str] = {}
            for key in order:
                probabilities = rows[key][tuple(values[p] for p in parents[key])]
                threshold = generator.random()
                cumulative = 0.0
                chosen: str | None = None
                for state, probability in zip(states[key], probabilities, strict=True):
                    cumulative += probability
                    if threshold < cumulative:
                        chosen = state
                        break
                if chosen is None:
                    for state, probability in zip(
                        reversed(states[key]), reversed(probabilities), strict=True
                    ):
                        if probability > 0.0:
                            chosen = state
                            break
                if chosen is None:
                    raise ValueError(
                        f"internal error: CPT row for {key!r} has no positive "
                        "probability"
                    )
                values[key] = chosen
            draws.append(values)
        return draws

    def conditional_scenarios(
        self,
        variable: str,
        evidence: Mapping[str, str] | None = None,
        targets: Sequence[str] | None = None,
    ) -> dict[str, dict[str, tuple[float, ...]]]:
        """"What-if" scenarios over one variable's states.

        For each state of ``variable``, the posterior marginal of every
        target under ``evidence`` plus ``{variable: state}`` — one
        :meth:`posterior` call per state, returned as
        ``{state: {target: distribution}}``. ``targets`` defaults to all
        other variables, in declaration order; a scenario state overrides
        the same key in ``evidence``. Unknown ``variable`` or target keys
        raise ``ValueError`` naming the offender; evidence keys, states,
        and zero-probability scenarios surface from :meth:`posterior`
        unchanged.
        """
        var = next((v for v in self.variables if v.key == variable), None)
        if var is None:
            raise ValueError(f"unknown variable {variable!r}")
        if targets is None:
            target_keys = [v.key for v in self.variables if v.key != variable]
        else:
            if not isinstance(targets, Sequence) or isinstance(targets, str):
                raise ValueError(
                    "targets must be a sequence of variable keys, "
                    f"got {type(targets).__name__}"
                )
            target_keys = list(targets)
        known = {v.key for v in self.variables}
        for target in target_keys:
            if target not in known:
                raise ValueError(f"unknown target variable {target!r}")
        base = {} if evidence is None else evidence
        scenarios: dict[str, dict[str, tuple[float, ...]]] = {}
        for state in var.states:
            posterior = self.posterior({**base, variable: state})
            scenarios[state] = {key: posterior[key] for key in target_keys}
        return scenarios

    def _prepare(
        self, evidence: Mapping[str, str]
    ) -> tuple[
        dict[str, str], dict[str, tuple[str, ...]], list[_Factor], tuple[str, ...]
    ]:
        """Validate the net, check evidence, and build the base factors."""
        self.validate()
        checked = self._checked_evidence(evidence)
        domains = {var.key: var.states for var in self.variables}
        factors = [
            _factor_reduce(self._factor_of(var), checked) for var in self.variables
        ]
        return checked, domains, factors, self.topological_order()

    def _checked_evidence(self, evidence: Mapping[str, str]) -> dict[str, str]:
        """Return ``evidence`` or raise ``ValueError`` naming the offender."""
        if not isinstance(evidence, Mapping):
            raise ValueError(
                "evidence must be a mapping of variable key -> state, "
                f"got {type(evidence).__name__}"
            )
        checked: dict[str, str] = {}
        for key, state in evidence.items():
            var = next((v for v in self.variables if v.key == key), None)
            if var is None:
                raise ValueError(f"unknown evidence variable {key!r}")
            if not isinstance(state, str) or state not in var.states:
                raise ValueError(
                    f"unknown evidence state {state!r} for variable {key!r} "
                    f"(states: {var.states!r})"
                )
            checked[key] = state
        return checked

    def _factor_of(self, var: Variable) -> _Factor:
        """Build the CPT factor for ``var`` over its parents + itself."""
        cpt = self.cpts[var.key]
        scope = (*cpt.parents, var.key)
        table: dict[tuple[str, ...], float] = {}
        for assignment, probabilities in cpt.table:
            prefix = tuple(assignment)
            for state, probability in zip(var.states, probabilities, strict=True):
                table[(*prefix, state)] = probability
        return (scope, table)

    def _marginal(
        self,
        var: Variable,
        evidence: Mapping[str, str],
        domains: Mapping[str, tuple[str, ...]],
        factors: list[_Factor],
        order: tuple[str, ...],
    ) -> tuple[float, ...]:
        """Exact posterior for ``var``: one elimination pass, one division."""
        observed = evidence.get(var.key)
        if observed is not None:
            return tuple(1.0 if state == observed else 0.0 for state in var.states)
        eliminated = [key for key in order if key != var.key and key not in evidence]
        remaining = _eliminate(list(factors), eliminated, domains)
        scope, table = _fold_multiply(remaining, domains)
        if scope != (var.key,):
            raise ValueError(
                f"internal error: factors for {var.key!r} reduced to scope "
                f"{scope!r}"
            )
        unnormalized = tuple(table[(state,)] for state in var.states)
        total = sum(unnormalized)
        if total <= 0.0:
            raise ValueError(
                f"evidence {dict(evidence)!r} has zero probability; "
                "the posterior is undefined"
            )
        return tuple(value / total for value in unnormalized)


def _factor_reduce(factor: _Factor, evidence: Mapping[str, str]) -> _Factor:
    """Drop the rows inconsistent with ``evidence`` and the evidence
    variables from the factor's scope; complete factors stay complete."""
    scope, table = factor
    if not any(key in evidence for key in scope):
        return factor
    keep = tuple(i for i, key in enumerate(scope) if key not in evidence)
    reduced: dict[tuple[str, ...], float] = {}
    for assignment, value in table.items():
        if any(
            assignment[i] != evidence[name]
            for i, name in enumerate(scope)
            if name in evidence
        ):
            continue
        reduced[tuple(assignment[i] for i in keep)] = value
    return (tuple(scope[i] for i in keep), reduced)


def _factor_multiply(
    left: _Factor, right: _Factor, domains: Mapping[str, tuple[str, ...]]
) -> _Factor:
    """Row-wise product over the union scope (left scope order first)."""
    scope_l, table_l = left
    scope_r, table_r = right
    extra = tuple(key for key in scope_r if key not in scope_l)
    positions: list[tuple[bool, int]] = []
    for key in scope_r:
        if key in scope_l:
            positions.append((False, scope_l.index(key)))
        else:
            positions.append((True, extra.index(key)))
    combos = (
        list(itertools.product(*(domains[key] for key in extra))) if extra else [()]
    )
    table: dict[tuple[str, ...], float] = {}
    for key_l, value_l in table_l.items():
        for combo in combos:
            key_r = tuple(
                combo[i] if is_combo else key_l[i] for is_combo, i in positions
            )
            table[key_l + combo] = value_l * table_r[key_r]
    return (scope_l + extra, table)


def _factor_sum_out(factor: _Factor, key: str) -> _Factor:
    """Sum the factor over ``key``, dropping it from the scope."""
    scope, table = factor
    index = scope.index(key)
    summed: dict[tuple[str, ...], float] = {}
    for assignment, value in table.items():
        remaining = assignment[:index] + assignment[index + 1 :]
        summed[remaining] = summed.get(remaining, 0.0) + value
    return (scope[:index] + scope[index + 1 :], summed)


def _eliminate(
    factors: list[_Factor],
    order: Sequence[str],
    domains: Mapping[str, tuple[str, ...]],
) -> list[_Factor]:
    """Sum out every variable in the caller's fixed ``order``: multiply the
    factors containing it, then sum it out; the surviving factors keep
    scopes disjoint from ``order``."""
    for key in order:
        containing = [factor for factor in factors if key in factor[0]]
        if not containing:
            continue
        remaining = [factor for factor in factors if key not in factor[0]]
        product = containing[0]
        for factor in containing[1:]:
            product = _factor_multiply(product, factor, domains)
        remaining.append(_factor_sum_out(product, key))
        factors = remaining
    return factors


def _fold_multiply(
    factors: list[_Factor], domains: Mapping[str, tuple[str, ...]]
) -> _Factor:
    """Multiply ``factors`` left to right into a single factor."""
    fold = factors[0]
    for factor in factors[1:]:
        fold = _factor_multiply(fold, factor, domains)
    return fold


def _variables_from_json(raw: object) -> list[Variable]:
    """Parse the GraphSpec ``variables`` section, naming the offender."""
    if not isinstance(raw, list):
        raise ValueError(
            f"GraphSpec variables must be a list, got {type(raw).__name__}"
        )
    variables: list[Variable] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"GraphSpec variables[{index}] must be a dict, "
                f"got {type(item).__name__}"
            )
        key = item.get("key")
        description = item.get("description")
        states = item.get("states")
        if not isinstance(key, str):
            raise ValueError(
                f"GraphSpec variables[{index}].key must be a string, got {key!r}"
            )
        if not isinstance(description, str):
            raise ValueError(
                f"GraphSpec variables[{index}].description must be a string, "
                f"got {type(description).__name__}"
            )
        if not isinstance(states, list) or not all(
            isinstance(state, str) for state in states
        ):
            raise ValueError(
                f"GraphSpec variables[{index}].states must be a list of strings, "
                f"got {states!r}"
            )
        variables.append(Variable(key, description, tuple(states)))
    return variables


def _edges_from_json(raw: object) -> list[Edge]:
    """Parse the GraphSpec ``edges`` section, naming the offender."""
    if not isinstance(raw, list):
        raise ValueError(f"GraphSpec edges must be a list, got {type(raw).__name__}")
    edges: list[Edge] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"GraphSpec edges[{index}] must be a dict, got {type(item).__name__}"
            )
        parent = item.get("parent")
        child = item.get("child")
        if not isinstance(parent, str) or not isinstance(child, str):
            raise ValueError(
                f"GraphSpec edges[{index}] parent and child must be strings, "
                f"got parent={parent!r} child={child!r}"
            )
        edges.append(Edge(parent, child))
    return edges


def _cpts_from_json(raw: object) -> dict[str, CPT]:
    """Parse the GraphSpec ``cpts`` section, naming the offender."""
    if not isinstance(raw, dict):
        raise ValueError(f"GraphSpec cpts must be a dict, got {type(raw).__name__}")
    cpts: dict[str, CPT] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"GraphSpec cpts keys must be strings, got {key!r}")
        if not isinstance(item, dict):
            raise ValueError(
                f"GraphSpec cpts[{key!r}] must be a dict, got {type(item).__name__}"
            )
        child = item.get("child")
        if child != key:
            raise ValueError(
                f"GraphSpec cpts[{key!r}].child must be {key!r}, got {child!r}"
            )
        parents = item.get("parents")
        if not isinstance(parents, list) or not all(
            isinstance(parent, str) for parent in parents
        ):
            raise ValueError(
                f"GraphSpec cpts[{key!r}].parents must be a list of strings, "
                f"got {parents!r}"
            )
        rows = item.get("rows")
        if not isinstance(rows, list):
            raise ValueError(
                f"GraphSpec cpts[{key!r}].rows must be a list, "
                f"got {type(rows).__name__}"
            )
        parsed: list[tuple[tuple[str, ...], tuple[float, ...]]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(
                    f"GraphSpec cpts[{key!r}].rows[{index}] must be a dict, "
                    f"got {type(row).__name__}"
                )
            assignment = row.get("assignment")
            probabilities = row.get("probabilities")
            if not isinstance(assignment, dict):
                raise ValueError(
                    f"GraphSpec cpts[{key!r}].rows[{index}].assignment must be a "
                    f"dict, got {type(assignment).__name__}"
                )
            unknown = [key for key in assignment if key not in parents]
            if unknown:
                raise ValueError(
                    f"GraphSpec cpts[{key!r}].rows[{index}].assignment names "
                    f"variables outside parents {parents!r}: {unknown}"
                )
            missing = [parent for parent in parents if parent not in assignment]
            if missing:
                raise ValueError(
                    f"GraphSpec cpts[{key!r}].rows[{index}].assignment is missing "
                    f"parents {missing}"
                )
            if not isinstance(probabilities, list):
                raise ValueError(
                    f"GraphSpec cpts[{key!r}].rows[{index}].probabilities must be "
                    f"a list of numbers, got {probabilities!r}"
                )
            values: list[float] = []
            for position, value in enumerate(probabilities):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(
                        f"GraphSpec cpts[{key!r}].rows[{index}].probabilities"
                        f"[{position}] must be a number, got {value!r}"
                    )
                values.append(float(value))
            parsed.append(
                (
                    tuple(assignment[parent] for parent in parents),
                    tuple(values),
                )
            )
        cpts[key] = CPT(key, tuple(parents), tuple(parsed))
    return cpts