# Methodology: Package Architecture {#sec:methodology}

{{PACKAGE_NAME}} is organized as a strict layering: an ergonomic surface (CLI, scripts, benchmarks) on top of pure-logic composition, on top of primitives and wire types, on top of a single transport and client layer that owns all I/O. [@fig:architecture] shows the module graph. The layering is enforced by convention: the composition and primitive modules import no I/O machinery, so every decision pattern is testable against constructed answers without a network stand-in.

![Package layer diagram for {{PACKAGE_NAME}}. The CLI (`src/daf_jev/cli.py`) and the thin orchestration scripts (`scripts/`, `benchmarks/`) sit on the application layer; `compose.py` (pure decision patterns) and `primitives.py` (typed question builders and `QuestionSet`) form the logic layer over the wire dataclasses in `_types.py`; `client.py` and `_http.py` own the single transport to the System One endpoint, with `_retry.py` and `_errors.py` providing the pure retry policy and the typed exception hierarchy; `models.py`, `config.py`, and `evaluate.py` enter as side inputs and the batch harness respectively. Boxes are named modules only; no measured values appear in the diagram.](../output/figures/architecture.png){#fig:architecture width=85%}

## Layered architecture

The layers, bottom-up:

- **Transport** (`_http.py`) — a minimal `Transport` protocol with a synchronous and an asynchronous `httpx` implementation. It knows nothing about decisions; it posts JSON to a path and returns the raw response.
- **Client** (`client.py`) — `JevClient` / `AsyncJevClient` resolve the API key from the environment (injected mapping, process environment, then a `.env` file, in that precedence order via `config.py`), build the request for a state plus a mapping of questions, apply the retry policy, and map HTTP status classes onto the typed exception hierarchy of `_errors.py`. The retry policy itself (`_retry.py`) is a *pure* function of the attempt number and an optional server-supplied retry hint — exponential backoff with a base, a cap, and jitter, with the hint winning when present — so its timing behavior is unit-testable without sleeping.
- **Wire types** (`_types.py`) — frozen dataclasses for the three question types and the three answer types, a strict parser that rejects unknown answer shapes, a usage record, and the top-level response object with cached per-type views (`nouls`, `choices`, `scores`).
- **Primitives** (`primitives.py`) — the ergonomic builders `noul()`, `choice()`, `score()` and the `QuestionSet` mapping container with additive composition (`add`, `merge`, `to_wire`). No I/O.
- **Composition** (`compose.py`) — pure functions over answers, described below. No I/O; network access happens only through a client injected by the caller for multi-call helpers.
- **Harness** (`evaluate.py`) — the batch `Evaluator`, described below.

## Typed primitives

![The three question primitives of the System One surface and the typed answer shapes {{PACKAGE_NAME}} parses them into. A `noul` question yields a calibrated yes/no probability; a `choice` question yields a selected label, a full probability distribution over the named options, and a scalar confidence; a `score` question yields a probability-weighted score over ordered levels together with the level legend, the level distribution, and a confidence. The diagram is a schematic of shapes only — it carries no measured data.](../output/figures/primitives_overview.png){#fig:primitives width=85%}

The builders in [@fig:primitives] map one-to-one onto the wire contract of [@sec:jev_model]. Validation is strict and eager: score criteria must carry at least two ordered levels, choice criteria must be non-empty, and the answer-side parser rejects any payload whose shape does not match the discriminated union exactly. The payoff of strictness is that downstream composition code can pattern-match on answers without defensive parsing — the type system, not runtime guesswork, guarantees the shapes.

## Composable decision patterns

The composition layer implements the documented TypeSafe patterns as pure functions [@typesafe2026patterns]:

- **`composite_score(answer, weights=None)`** — the expected value of a `score` answer over its level indices, uniform by default or under caller-supplied weights (which must be finite and positive-massing). This turns an ordinal rating into a comparable scalar without a second model call.
- **`confidence_gate(answer, threshold, below)`** — returns the answer's primary value when its confidence meets the caller's threshold, and the `below` verdict otherwise. The threshold is owned by the calling code, never by the package.
- **`route(answer, handlers, min_confidence, fallback)`** — dispatches to the handler registered for a `choice` answer's label, gated on a minimum confidence with an optional fallback handler; `pick` fans the same dispatch across every answer in a mapping.

**Batching fan-out and the Evaluator.** Because the model evaluates questions independently and in parallel ([@sec:jev_model]), the cheapest correct strategy is to batch a fixed question set into one call. The `Evaluator` in `evaluate.py` inverts the axis: it holds the question set fixed and runs it over *many states*, concurrently — through a thread pool for the synchronous client or `asyncio` with a semaphore for the asynchronous client. Per-state failures never abort the batch; they are captured into the evaluation record alongside the answers and the measured latency, so one malformed state cannot cost the run. This harness is what the benchmark scripts in [@sec:results] reuse for their fan-out measurements.

**Confidence-gated routing.** [@fig:confidence] illustrates the three-band policy that `confidence_gate` and `route` implement: answers whose confidence clears the upper band are automated, mid-band answers are routed to review, and answers below the lower band are escalated. The boundary markers in the figure are *example thresholds* — the semantics are the bands, not any particular cut points, which remain policy owned by the caller.

![Parametric illustration of confidence-gated routing as implemented by `confidence_gate()` and `route()` in `src/daf_jev/compose.py`. The horizontal axis is the model-reported confidence on the unit interval; the three horizontal bands assign an action per confidence region — automate, review, escalate. The boundary markers are annotated as example thresholds: they illustrate the band semantics and are not fitted or recommended values.](../output/figures/confidence_bands.png){#fig:confidence width=80%}

## Design rulings

Four rulings shaped the codebase and are worth stating as contracts:

1. **Pure logic, injected I/O.** Everything under `compose.py`, `primitives.py`, `_types.py`, and `_retry.py` performs no I/O; network access is confined to the transport and client layer and is injectable (clock, sleep, transport) for deterministic tests.
2. **Real stand-ins, no mocks.** The test suite drives the real HTTP transport against a real local HTTP server fixture rather than patching client internals, so retry, timeout, and error-mapping behavior is exercised end to end.
3. **Pure retry policy.** Backoff timing is a function of the attempt number and the server's retry hint alone — testable without sleeping, and identical across the sync and async clients.
4. **Snapshotted documentation.** The bundled documentation snapshot carries a manifest of per-page content hashes and a snapshot identifier, and a CLI subcommand re-hashes the tree to detect drift ([@sec:reproducibility]). Prose claims about the model are therefore checkable against an immutable, verified source rather than a moving website.
