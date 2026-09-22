"""Jev-as-factor-source elicitation for graphical models.

Two drivers over the public client API (``client.ask``) turn Jev answers
into factors for a discrete Bayesian network:

- :func:`elicit_cpts` asks one :func:`daf_jev.primitives.choice` question
  per CPT row — every child under every parent assignment — so a whole
  network's CPTs arrive in ONE batched request by default (chunked
  deterministically when ``max_questions_per_request`` is set), and the
  rows assemble into a validated :class:`~daf_jev.graphical.BayesNet`.
- :func:`propose_structure` asks one ``choice()`` question per unordered
  variable pair (options ``a->b``, ``b->a``, ``no-edge``, in order) and
  assembles a DAG from each chosen edge's log-probability gain over the
  no-edge baseline (``log(p_edge) - log(p_no_edge)``): an exact search
  over topological orderings for small nets, a greedy fallback for
  large ones. The returned net carries edges ONLY — its CPTs are empty and
  ``validate()`` is intentionally NOT yet satisfied until
  :func:`elicit_cpts` fills them (the two-step upstream flow: propose the
  structure, then elicit the CPTs).

Jev sits UPSTREAM of inference here: structure and CPTs are elicited once
and reused downstream; :meth:`daf_jev.graphical.BayesNet.posterior` performs
the inference itself in :mod:`daf_jev.graphical`.

Both functions accept any client object exposing
``ask(state, questions) -> SystemOneResponse`` — the sync
:class:`~daf_jev.client.JevClient`, the async
:class:`~daf_jev.client.AsyncJevClient` (the whole batch runs on one
private event loop, mirroring :mod:`daf_jev.evaluate`), or a test stand-in.
The client is never closed here: its lifecycle stays with the caller.
Provider choice happened upstream (``open_client`` /
``JevClient.for_provider``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import itertools
import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from daf_jev._types import (
    ChoiceAnswer,
    ChoiceQuestion,
    JSONContent,
    SystemOneResponse,
)
from daf_jev.primitives import choice

if TYPE_CHECKING:
    # Static only: the sibling graphical module is imported lazily inside
    # the public functions, keeping the runtime import graph acyclic while
    # the two modules land concurrently.
    from daf_jev.graphical import BayesNet, Edge, Variable

__all__ = ["elicit_cpts", "propose_structure"]

_CPT_INSTRUCTIONS_DEFAULT = (
    "You are supplying the conditional probability tables (CPTs) of a "
    "Bayesian network. Each question fixes the values of a child variable's "
    "parents (given as 'parent = value' facts) and asks for the probability "
    "distribution over the child's states. The options list the child's "
    "states in order; answer with calibrated probabilities that sum to 1 "
    "across the options."
)

_STRUCTURE_INSTRUCTIONS_DEFAULT = (
    "You are proposing the structure (directed edges) of a Bayesian "
    "network. Each question asks whether there is a DIRECT dependency "
    "between two variables, accounting for mediation through the other "
    "variables: if the influence would flow through other listed variables, "
    "answer 'no-edge'. Choose 'a->b' when a is a direct parent of b, "
    "'b->a' when b is a direct parent of a, or 'no-edge'."
)


# ---------------------------------------------------------------------------
# Client driving
# ---------------------------------------------------------------------------


def _run_coroutine(coro: Any) -> Any:
    """Drive a coroutine from the sync API, even inside a running loop.

    Mirrors ``daf_jev.evaluate.Evaluator._run_async``: a fresh event loop
    when none is running, otherwise a private single-worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _ask_chunks(
    client: Any, state: JSONContent, chunks: Sequence[Mapping[str, ChoiceQuestion]]
) -> list[SystemOneResponse]:
    """Round-trip every chunk in order through the public ``ask`` API.

    Async clients (``ask`` declared ``async def``, e.g.
    ``AsyncJevClient``) run the WHOLE batch on one private event loop so a
    shared async transport never straddles loops; sync clients ask chunk by
    chunk inline. A sync-declared ``ask`` that still returns a coroutine
    fails closed. The client is never closed here.
    """
    ask: Any = getattr(client, "ask", None)
    if not callable(ask):
        raise TypeError(
            "client must expose a callable ask(state, questions), got "
            f"{type(client).__name__}"
        )
    if inspect.iscoroutinefunction(ask):

        async def _run() -> list[SystemOneResponse]:
            return [await ask(state, chunk) for chunk in chunks]

        return _run_coroutine(_run())

    responses: list[SystemOneResponse] = []
    for chunk in chunks:
        result: Any = ask(state, chunk)
        if inspect.iscoroutine(result):
            raise ValueError(
                "client.ask returned a coroutine although it is not declared "
                "async; provide an async def ask() (AsyncJevClient) or a "
                "synchronous ask() (JevClient)"
            )
        responses.append(result)
    return responses


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _unique_variables(variables: Sequence[Variable]) -> list[Variable]:
    """Materialize the variable sequence; fail closed on duplicates."""
    items = list(variables)
    if not items:
        raise ValueError("variables must be a nonempty sequence")
    seen: set[str] = set()
    for index, variable in enumerate(items):
        key = getattr(variable, "key", None)
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"variables[{index}] must be a daf_jev.graphical.Variable "
                f"with a nonempty string key, got {type(variable).__name__}"
            )
        if key in seen:
            raise ValueError(f"variable key {key!r} appears more than once")
        seen.add(key)
    return items


def _states_of(variable: Variable, context: str) -> tuple[str, ...]:
    """Return the variable's states; fail closed unless >= 2 unique labels."""
    states = getattr(variable, "states", None)
    if not isinstance(states, Sequence) or isinstance(states, str):
        raise ValueError(
            f"{context} must carry a states tuple with at least 2 states, "
            f"got {type(states).__name__}"
        )
    if len(states) < 2:
        raise ValueError(f"{context} must have at least 2 states, got {states!r}")
    if len(set(states)) != len(states):
        raise ValueError(f"{context} has duplicate state labels: {states!r}")
    if not all(isinstance(state, str) and state for state in states):
        raise ValueError(f"{context} states must be nonempty strings: {states!r}")
    return tuple(states)


def _validated_edges(edges: Sequence[Edge], keys: set[str]) -> list[Edge]:
    """Materialize edges; fail closed on unknown endpoints and duplicates."""
    items = list(edges)
    seen: set[tuple[str, str]] = set()
    for edge in items:
        parent = getattr(edge, "parent", None)
        child = getattr(edge, "child", None)
        if parent not in keys:
            raise ValueError(
                f"edge parent {parent!r} is not a declared variable: {edge!r}"
            )
        if child not in keys:
            raise ValueError(
                f"edge child {child!r} is not a declared variable: {edge!r}"
            )
        if parent == child:
            raise ValueError(f"edge from {parent!r} to itself is not allowed")
        if (parent, child) in seen:
            raise ValueError(f"duplicate edge {parent!r} -> {child!r}")
        seen.add((parent, child))
    return items


def _ensure_acyclic(keys: Sequence[str], edges: Sequence[tuple[str, str]]) -> None:
    """Raise unless the directed edges form a DAG (Kahn, deterministic)."""
    children: dict[str, list[str]] = {key: [] for key in keys}
    indegree: dict[str, int] = {key: 0 for key in keys}
    for parent, child in edges:
        children[parent].append(child)
        indegree[child] += 1
    ready = [key for key in keys if indegree[key] == 0]
    ordered = 0
    while ready:
        node = ready.pop()
        ordered += 1
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if ordered != len(keys):
        cyclic = sorted(key for key in keys if indegree[key] > 0)
        raise ValueError(
            "edges must form a DAG but contain a cycle through "
            + ", ".join(repr(key) for key in cyclic)
        )


# ---------------------------------------------------------------------------
# Deterministic prompt composition
# ---------------------------------------------------------------------------


def _base_instructions(instructions: str | None, default: str) -> str:
    """Caller text prepends context; the default base follows it."""
    if instructions is None:
        return default
    return f"{instructions}\n\n{default}"


def _default_state(
    variables: Sequence[Variable], *, include_states: bool
) -> str:
    """Deterministic default state: the composed variable meanings."""
    lines = []
    for variable in variables:
        line = f"- {variable.key}: {variable.description}"
        if include_states:
            line += f" (states: {' | '.join(variable.states)})"
        lines.append(line)
    return "Bayesian-network variables:\n" + "\n".join(lines)


def _cpt_question_id(
    child_key: str, assignment: Sequence[tuple[str, str]]
) -> str:
    """Deterministic CPT row id (pinned scheme): ``cpt::<child>|p=v|p=v``."""
    return (
        f"cpt::{child_key}|"
        + "|".join(f"{parent}={value}" for parent, value in assignment)
    )


def _cpt_question_text(
    base: str, child: Variable, assignment: Sequence[tuple[str, str]]
) -> str:
    """Per-row instructions: base plus the pinned parent-assignment facts."""
    if assignment:
        given = ", ".join(f"{parent} = {value}" for parent, value in assignment)
        return (
            f"{base}\n\nQuestion: given that {given}, what is the "
            f"probability distribution over {child.key} ({child.description})? "
            f"Options are the states of {child.key} in the listed order."
        )
    return (
        f"{base}\n\nQuestion: what is the prior probability distribution "
        f"over {child.key} ({child.description})? Options are the states of "
        f"{child.key} in the listed order."
    )


def _structure_question_text(base: str, a: Variable, b: Variable) -> str:
    """Per-pair instructions: base plus the direct-dependency framing."""
    return (
        f"{base}\n\nQuestion: is there a direct dependency between "
        f"{a.key} ({a.description}) and {b.key} ({b.description}), after "
        f"accounting for mediation through the other variables? Options in "
        f"order: '{a.key}->{b.key}', '{b.key}->{a.key}', 'no-edge'."
    )


# ---------------------------------------------------------------------------
# Answer extraction (fail closed)
# ---------------------------------------------------------------------------


def _choice_answer_of(answers: Mapping[str, object], qid: str) -> ChoiceAnswer:
    """Return the choice answer for ``qid`` or raise naming the question id."""
    answer = answers.get(qid)
    if answer is None:
        raise ValueError(f"response is missing an answer for question {qid!r}")
    if not isinstance(answer, ChoiceAnswer):
        raise ValueError(
            f"question {qid!r} requires a choice answer, got "
            f"{type(answer).__name__}"
        )
    return answer


def _distribution_of(
    answer: ChoiceAnswer, qid: str, states: Sequence[str]
) -> tuple[float, ...]:
    """Map the choice distribution onto ``states`` in order; fail closed."""
    values: list[float] = []
    for label in states:
        if label not in answer.probabilities:
            raise ValueError(
                f"answer for question {qid!r} is missing a probability for "
                f"option {label!r}"
            )
        value = answer.probabilities[label]
        if not math.isfinite(value):
            raise ValueError(
                f"answer for question {qid!r} has non-finite probability "
                f"{value!r} for option {label!r}"
            )
        if value < 0.0:
            raise ValueError(
                f"answer for question {qid!r} has negative probability "
                f"{value!r} for option {label!r}"
            )
        values.append(value)
    return tuple(values)


def _log_probability_of(answer: ChoiceAnswer, qid: str, option: str) -> float:
    """Return ``log(p)`` of one option; fail closed when missing/invalid."""
    if option not in answer.probabilities:
        raise ValueError(
            f"answer for question {qid!r} is missing a probability for "
            f"option {option!r}"
        )
    probability = answer.probabilities[option]
    if not math.isfinite(probability) or probability <= 0.0:
        raise ValueError(
            f"answer for question {qid!r} has non-positive or non-finite "
            f"probability {probability!r} for option {option!r}"
        )
    return math.log(probability)


def _directed_edge_of(
    answer: ChoiceAnswer,
    qid: str,
    pair: tuple[int, int],
    keys: Sequence[str],
) -> tuple[tuple[int, int], float, float] | None:
    """Resolve one pair's chosen directed edge and its log-probabilities.

    Returns ``((u_index, v_index), log(p_edge), log(p_no_edge))`` for a
    chosen ``u->v`` option, or ``None`` for ``no-edge``. The no-edge
    probability is the baseline the edge's log-prob gain is measured
    against. Raises naming the question id when the choice is unknown or
    either probability is missing, non-finite, or non-positive (the log
    would be undefined).
    """
    u, v = pair
    forward = f"{keys[u]}->{keys[v]}"
    backward = f"{keys[v]}->{keys[u]}"
    option = answer.choice
    if option == "no-edge":
        return None
    if option == forward:
        edge = (u, v)
    elif option == backward:
        edge = (v, u)
    else:
        raise ValueError(
            f"answer for question {qid!r} chose unknown option {option!r}"
        )
    return (
        edge,
        _log_probability_of(answer, qid, option),
        _log_probability_of(answer, qid, "no-edge"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def elicit_cpts(
    variables: Sequence[Variable],
    edges: Sequence[Edge],
    *,
    client: Any,
    instructions: str | None = None,
    max_questions_per_request: int | None = None,
    state: JSONContent | None = None,
) -> BayesNet:
    """Elicit every CPT of a Bayes net in batched ``choice()`` asks.

    For every child (in ``variables`` order) and EVERY parent assignment
    (canonical lexicographic order by each parent's states), one
    ``choice()`` question is asked whose options are the child's states in
    order. Question ids follow the pinned deterministic scheme
    ``cpt::<child>|<p>=<v>|<p>=<v>``. One batched ask carries all rows when
    ``max_questions_per_request`` is ``None`` or >= the row count;
    otherwise rows chunk deterministically in enumeration order, one ask
    per chunk. The default ``state`` describes the variable meanings
    (deterministic text); pass ``state`` to override and ``instructions``
    to prepend context (population, unknown treatment, ...) to the shared
    base instructions.

    Args:
        variables: The net's variables in order (unique keys, >= 2 states
            each).
        edges: The DAG's edges; validated (endpoints, duplicates,
            self-loops, acyclicity) before any network call.
        client: Any object exposing ``ask(state, questions) ->
            SystemOneResponse`` (sync ``JevClient``, async
            ``AsyncJevClient``, or a test stand-in). Never closed here.
        instructions: Optional context prepended to the shared base
            instructions.
        max_questions_per_request: Optional batch size (>= 1); ``None``
            sends every row in one request.
        state: Optional override for the composed variable-meaning state.

    Returns:
        A validated :class:`daf_jev.graphical.BayesNet` (``validate()``
        runs before returning; row probabilities are stored as answered —
        renormalization is the caller's choice).

    Raises:
        ValueError: On invalid inputs, a missing or wrong-type answer for
            a row (naming the question id), missing/negative/non-finite
            option probabilities, or when the assembled net fails
            ``validate()``.
        TypeError: When ``client`` exposes no callable ``ask``.
    """
    from daf_jev.graphical import CPT, BayesNet  # lazy: sibling module

    if max_questions_per_request is not None and max_questions_per_request < 1:
        raise ValueError(
            "max_questions_per_request must be >= 1 when given, got "
            f"{max_questions_per_request!r}"
        )
    variables_list = _unique_variables(variables)
    keys = [variable.key for variable in variables_list]
    edges_list = _validated_edges(edges, set(keys))
    _ensure_acyclic(keys, [(edge.parent, edge.child) for edge in edges_list])

    # Canonical parent order comes from the graph itself, so the assembled
    # CPTs cannot disagree with validate()'s parent-order assertion.
    provisional = BayesNet(
        variables=tuple(variables_list), edges=tuple(edges_list), cpts={}
    )
    parents_of = {
        variable.key: provisional.parents_of(variable.key)
        for variable in variables_list
    }
    states_of = {
        variable.key: _states_of(variable, f"variable {variable.key!r}")
        for variable in variables_list
    }

    base = _base_instructions(instructions, _CPT_INSTRUCTIONS_DEFAULT)
    resolved_state = (
        state
        if state is not None
        else _default_state(variables_list, include_states=True)
    )

    questions: dict[str, ChoiceQuestion] = {}
    rows: list[tuple[str, Variable, tuple[tuple[str, str], ...], tuple[str, ...]]] = []
    for child in variables_list:
        parents = parents_of[child.key]
        for values in itertools.product(
            *(states_of[parent] for parent in parents)
        ):
            assignment = tuple(zip(parents, values, strict=True))
            qid = _cpt_question_id(child.key, assignment)
            questions[qid] = choice(
                _cpt_question_text(base, child, assignment),
                dict.fromkeys(states_of[child.key]),
            )
            rows.append((qid, child, assignment, values))

    if max_questions_per_request is None or len(rows) <= max_questions_per_request:
        chunks = [rows]
    else:
        chunks = [
            rows[start : start + max_questions_per_request]
            for start in range(0, len(rows), max_questions_per_request)
        ]
    responses = _ask_chunks(
        client,
        resolved_state,
        [{qid: questions[qid] for qid, *_rest in chunk} for chunk in chunks],
    )

    answers_by_qid: dict[str, object] = {}
    for response in responses:
        answers_by_qid.update(response.answers)

    tables: dict[str, list[tuple[tuple[str, ...], tuple[float, ...]]]] = {
        variable.key: [] for variable in variables_list
    }
    for qid, child, _assignment, values in rows:
        answer = _choice_answer_of(answers_by_qid, qid)
        probabilities = _distribution_of(answer, qid, states_of[child.key])
        tables[child.key].append((values, probabilities))

    cpts = {
        child.key: CPT(
            child=child.key,
            parents=parents_of[child.key],
            table=tuple(tables[child.key]),
        )
        for child in variables_list
    }
    net = BayesNet(
        variables=tuple(variables_list), edges=tuple(edges_list), cpts=cpts
    )
    net.validate()
    return net


def propose_structure(
    variables: Sequence[Variable],
    *,
    client: Any,
    instructions: str | None = None,
    edge_penalty: float = 1.0,
    exact_limit: int = 8,
    state: JSONContent | None = None,
) -> BayesNet:
    """Propose a Bayes net's DAG from pairwise Jev ``choice()`` answers.

    One batched ask carries one question per unordered variable pair
    (``n(n-1)/2`` questions; ids ``edge::<a>->{b}``), with options in
    order: ``a->b``, ``b->a``, ``no-edge``. The edge score is the chosen
    option's ``log(p)`` measured as a GAIN over the pair's ``no-edge``
    baseline, ``log(p_edge) - log(p_no_edge)``: a raw ``log(p) <= 0``
    sum would always prefer the empty DAG (any acyclic candidate set has
    an ordering consistent with none of its edges), while the baseline
    delta is what makes a well-believed edge attractive and is the
    "log-prob gain" the greedy admission test compares against
    ``edge_penalty``. The DAG assembles by exact search over topological
    orderings when ``n <= exact_limit`` (O(n! * n^2), the n! search of
    the Dellaert-style experiment): each ordering's score is the sum of
    ``log(p_edge/p_no_edge) - edge_penalty`` over the chosen edges
    consistent with it — equivalently the full per-pair score (edges
    contribute ``log(p_edge) - edge_penalty``, every other pair its
    ``log(p_no_edge)`` baseline) up to one ordering-independent
    constant — and the best ordering wins (ties
    break to the lexicographically smallest ordering). Larger nets use
    the greedy fallback: start empty and repeatedly add the
    highest-scoring edge (max ``log(p_edge)``; ties break to enumeration
    order) that keeps the graph acyclic while its log-prob gain exceeds
    ``edge_penalty``. Note the pinned asymmetry: the exact path keeps
    ALL edges consistent with the winning ordering, while the greedy
    path drops edges whose gain does not exceed the penalty.

    The result carries edges only: CPTs are empty and ``validate()`` is
    intentionally NOT satisfied yet — pass the net's edges into
    :func:`elicit_cpts` to complete the two-step flow.

    Args:
        variables: The candidate variables in order (unique keys; at
            least 2).
        client: Any object exposing ``ask(state, questions) ->
            SystemOneResponse`` (sync ``JevClient``, async
            ``AsyncJevClient``, or a test stand-in). Never closed here.
        instructions: Optional context prepended to the shared base
            instructions.
        edge_penalty: Finite cost per consistent edge subtracted from
            its log-probability gain (higher penalizes to sparser nets).
        exact_limit: Maximum ``n`` for the exact ordering search;
            larger nets use the greedy fallback.
        state: Optional override for the composed variable-meaning state.

    Returns:
        A :class:`daf_jev.graphical.BayesNet` with edges only (ordered by
        pair enumeration, identical for the exact and greedy paths) and
        an empty ``cpts`` mapping.

    Raises:
        ValueError: On invalid inputs (non-finite ``edge_penalty``,
            ``exact_limit < 1``, fewer than 2 variables, duplicate keys)
            or answers (missing/wrong type, unknown option, missing or
            non-positive/non-finite chosen-option or no-edge-baseline
            probability — naming the question id).
        TypeError: When ``client`` exposes no callable ``ask``.
    """
    from daf_jev.graphical import BayesNet, Edge  # lazy: sibling module

    if not math.isfinite(edge_penalty):
        raise ValueError(f"edge_penalty must be finite, got {edge_penalty!r}")
    if exact_limit < 1:
        raise ValueError(f"exact_limit must be >= 1, got {exact_limit!r}")
    variables_list = _unique_variables(variables)
    n = len(variables_list)
    if n < 2:
        raise ValueError(
            f"propose_structure requires at least 2 variables, got {n}"
        )
    keys = [variable.key for variable in variables_list]

    base = _base_instructions(instructions, _STRUCTURE_INSTRUCTIONS_DEFAULT)
    resolved_state = (
        state
        if state is not None
        else _default_state(variables_list, include_states=False)
    )

    pairs = list(itertools.combinations(range(n), 2))
    questions: dict[str, ChoiceQuestion] = {}
    for i, j in pairs:
        a, b = variables_list[i], variables_list[j]
        qid = f"edge::{keys[i]}->{keys[j]}"
        questions[qid] = choice(
            _structure_question_text(base, a, b),
            {
                f"{keys[i]}->{keys[j]}": f"{keys[i]} is a direct parent of {keys[j]}",
                f"{keys[j]}->{keys[i]}": f"{keys[j]} is a direct parent of {keys[i]}",
                "no-edge": None,
            },
        )

    (response,) = _ask_chunks(client, resolved_state, [questions])
    candidates: dict[tuple[int, int], tuple[tuple[int, int], float, float] | None] = {}
    for i, j in pairs:
        qid = f"edge::{keys[i]}->{keys[j]}"
        candidates[(i, j)] = _directed_edge_of(
            _choice_answer_of(response.answers, qid), qid, (i, j), keys
        )
    scored = [item for item in candidates.values() if item is not None]

    if n <= exact_limit:
        best_score: float | None = None
        best_ordering: tuple[int, ...] | None = None
        for ordering in itertools.permutations(range(n)):
            position = {node: index for index, node in enumerate(ordering)}
            total = 0.0
            count = 0
            for (u, v), log_edge, log_no_edge in scored:
                if position[u] < position[v]:
                    total += log_edge - log_no_edge
                    count += 1
            score = total - edge_penalty * count
            if (
                best_score is None
                or score > best_score
                or (
                    best_ordering is not None
                    and score == best_score
                    and ordering < best_ordering
                )
            ):
                best_score = score
                best_ordering = ordering
        assert best_ordering is not None  # n >= 2: at least one ordering
        position = {node: index for index, node in enumerate(best_ordering)}
        edge_pairs = [
            (u, v)
            for (u, v), _log_edge, _log_no_edge in scored
            if position[u] < position[v]
        ]
    else:
        adjacency: dict[int, set[int]] = {node: set() for node in range(n)}
        taken: set[tuple[int, int]] = set()
        while True:
            best: tuple[tuple[int, int], float] | None = None
            for candidate in scored:
                edge, log_edge, log_no_edge = candidate
                if edge in taken:
                    continue
                if log_edge - log_no_edge <= edge_penalty:
                    continue
                u, v = edge
                if _reachable(adjacency, v, u):
                    continue
                if best is None or log_edge > best[1]:
                    best = (edge, log_edge)
            if best is None:
                break
            (u, v), _log_edge = best
            taken.add((u, v))
            adjacency[u].add(v)
        # Canonical result order: pair enumeration, same as the exact path.
        edge_pairs = [edge for edge, _le, _ln in scored if edge in taken]

    edges = tuple(
        Edge(parent=keys[u], child=keys[v]) for (u, v) in edge_pairs
    )
    return BayesNet(variables=tuple(variables_list), edges=edges, cpts={})


def _reachable(
    adjacency: Mapping[int, set[int]], source: int, target: int
) -> bool:
    """True when ``target`` is reachable from ``source`` (iterative DFS)."""
    stack = [source]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency[node])
    return False
