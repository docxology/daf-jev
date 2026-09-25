---
name: daf-jev
description: >
  Build with the daf-jev Python client for the TypeSafe Jev (System One) API:
  typed question builders (noul/choice/score), sync and async clients,
  concurrent evaluation, composable decision patterns (composite scoring,
  confidence and tiered gates), usage accounting (UsageLedger), an opt-in
  circuit breaker, calibration utilities, a CLI, an MCP server,
  multi-provider dispatch (jev, jeff, kev, localjev, openthai-systemone,
  openrouter), and Jev as a factor source for discrete Bayes nets (batched
  CPT elicitation, pairwise structure proposal, exact inference, GraphSpec
  interchange). Use when writing or reviewing daf-jev code, integrating
  System One judgments into a Python project, evaluating a question set
  over many states, eliciting Bayes-net factors from Jev, wiring Jev tools
  into an MCP-capable agent, or pointing the toolkit at a self-hosted
  System One server.
---

# daf-jev

`daf-jev` is a thin, composable Python client for `POST /v1/systemone`. Code
owns the workflow; Jev returns typed answers and probabilities. Package source
of truth: `docs/ARCHITECTURE.md`; live-API facts: `docs/reference/`.

## Install

```bash
uv sync --extra dev
uv sync --extra mcp      # only for the MCP server (daf-jev serve)
export JEV_API_KEY=...   # falls back to TYPESAFE_API_KEY
```

Optional `JEV_BASE_URL` overrides the endpoint. A `.env` at the project root
is auto-loaded (built-in loader, no python-dotenv); it is gitignored and MUST
never be committed, printed, or read by tests.

## Python API (`import daf_jev`)

- **Builders** (`daf_jev.primitives`) —
  `noul(instructions, *, true_desc=None, false_desc=None)`,
  `choice(instructions, options: Mapping[str, str | None])`,
  `score(instructions, levels: Sequence[str])` (>= 2 levels);
  `QuestionSet()` with `.add(id, q)`, `.merge(other)`, `.to_wire()`.
- **Clients** (`daf_jev.client`) — `JevClient(api_key=None, *, base_url=None, model=None, ...)`
  (`model=None` resolves `JEV_MODEL` / `TYPESAFE_DEFAULT_MODEL`, then
  `jev-latest`), `.ask(state, questions, *, model=None, timeout=None,
  request_headers=None) -> SystemOneResponse` (answers by id; cached views
  `.nouls` / `.choices` / `.scores`; `.usage`; `.request_id`).
  `AsyncJevClient` has the same surface, async. Errors form a
  `TypeSafeError` hierarchy; 429/529 retry per `RetryPolicy`.
- **Evaluation** (`daf_jev.evaluate`) — `Evaluator(client, questions, *, concurrency=...)`
  `.evaluate(states) -> list[EvaluationRecord]`, `.summary()` for
  aggregates; `await .evaluate_async(items)` is the public async entry
  point for in-loop use (requires an `AsyncJevClient`; the async session
  closes at batch end).
- **Compose** (`daf_jev.compose`, pure over answers):
  - `composite_score(answer, weights=None)` — expected value over sorted level
    indices; `weights` re-weight the probability distribution (only ratios
    matter; with non-negative weights the result stays within the level
    index range — negative weights are allowed but void that guarantee).
  - `confidence_gate(answer, *, threshold, below="review")` — primary value
    when `answer.confidence >= threshold`, else `below`.
  - `tiered_gate(answer, *, high=0.85, low=0.6, high_label="automate",
    middle_label="review", low_label="escalate")` — two-threshold routing.
  - `route(answer, handlers, *, min_confidence=0.0, fallback=None)` and
    `pick(actions, choices)` for dispatch to callables.
- **Usage** (`daf_jev.ledger`) — `UsageLedger()` thread-safe accounting
  across any loop of calls: `.record(usage | response | None)` (None is
  skipped; anything else raises `TypeError`), `.snapshot()` / `.reset()`
  return a frozen `UsageSnapshot` with
  `requests`, `input_tokens`, `output_tokens`, `.total_tokens`, `.to_dict()`.
- **Resilience** (`daf_jev.resilience`) — `CircuitBreaker(failure_threshold=5,
  cooldown_seconds=30.0, clock=time.monotonic)` opt-in failure isolation over
  any callable: `cb.call(fn, *args, **kwargs)` runs fn unless the circuit is
  open (`CircuitOpenError` with `.remaining_seconds`); N consecutive
  failures open for the cooldown, then one probe; `record_success()` /
  `record_failure()` drive it manually; states via `CircuitState`
  (closed/open/half_open).
- **Decider** (`daf_jev.decider`) — `Decider(client=None, *,
  render_state, questions, map_answers, fallback, gate, budget, breaker,
  ledger, cache, cache_key, ...)`: the fail-open decision-point loop.
  `decide(state)` never raises; `DecisionEvent.to_dict()` carries the
  closed reason taxonomy (11 reasons, incl. `error`); `Budget` thresholds
  must be >= 0; `calibration_pairs()` accumulates `(declared confidence,
  gate-accepted)` pairs when the gate is a `ConfidenceGate` — a
  self-consistency proxy for `daf_jev.calibration`.
- **Models** (`daf_jev.models`) — `client.models(*, timeout=None, request_headers=None) ->
  list[ModelCard]` (same per-call params as `ask`, retried per policy);
  `pick_model(cards, *, contains=None, prefer="latest")`.
- **Calibration** (`daf_jev.calibration`, pure): `bucket_index(confidence,
  n_buckets=10)`, `reliability_table(pairs, *, n_buckets=10)`,
  `expected_calibration_error(pairs, *, n_buckets=10)`,
  `brier_score(pairs)` — pairs are `(confidence, correct: bool)` tuples.
- **Jaggedness** (`daf_jev.jaggedness`, pure stdlib) — how far repeated
  answers to stochastic prompts (coin flips, die rolls; built-in `COIN` /
  `COIN_NOUL` / `D6` fixtures) stray from the stated uniform distribution:
  `uniform_chi2` (chi-square + df + p), `uniform_deviation` (max |Δp| +
  total variation), `runs_test_z` / `max_streak` (serial structure),
  `position_slope` (order-rotation position bias), `noul_choice_delta`
  (the same coin asked as noul vs choice). `run_battery(client, fixtures,
  *, repeats=50, concurrent=32, timeout=None)` drives any duck-typed
  `ask` client; degeneracy (one label on every identical ask) is a
  reported finding, not an error. Live battery:
  `benchmarks/bench_jaggedness.py` (per-provider SKIP without its key;
  see `benchmarks/README.md`).
- **Graphical models** (`daf_jev.graphical` +
  `daf_jev.graphical_elicitation`) — Jev as a factor source for discrete
  Bayes nets: `Variable(key, description, states)`, `Edge(parent,
  child)`, `CPT(child, parents, table)`, `BayesNet(variables, edges,
  cpts)` with `.validate()`, `.topological_order()`,
  `.query(variable, evidence)` / `.posterior(evidence)` (exact variable
  elimination, pure stdlib), and `.to_json()` / `.from_json()` —
  GraphSpec `dafjev.bayesnet/1`, the interchange with GNN / RxInfer.jl /
  GTSAM-style engines. `elicit_cpts(variables, edges, *, client, ...)`
  elicits every CPT row of the whole net in one batched ask
  (deterministic ids, ordered state options, chunking via
  `max_questions_per_request`); `propose_structure(variables, *,
  client, ...)` proposes the DAG from one batched ask over all variable
  pairs (edges only; exact ordering search to `exact_limit=8`, greedy
  above with `edge_penalty`).
  `.most_probable_explanation(evidence)` (most probable joint assignment
  consistent with the evidence; deterministic lexicographic tiebreak),
  `.sample(n, rng=None)` (ancestral sampling in topological order), and
  `.conditional_scenarios(variable, evidence=None, targets=None)`
  (per-state posterior marginals of the targets) round out the
  inference surface.
- **Graphical viz** (`daf_jev.graphical_viz`) — `to_mermaid(net)`
  (zero-dependency mermaid `graph TD` source), `plot_network(net, path)`
  (deterministic layered PNG), `plot_posterior_trajectory(net,
  query_keys, steps, path, labels=...)` (grouped P(true) bars over
  cumulative evidence steps; "true" = the last state of each variable's
  states tuple); matplotlib imports lazily inside the plotters
  (`figures` extra). Thin runner `scripts/bayes_experiment.py`
  reproduces the Asia experiment into `--out-dir` (default
  `output/experiments/asia`): `asia_graphspec.json`, `network.png`,
  `posterior_trajectory.png`, `mermaid.txt`.
  `animate_posterior(net, query_keys, evidence_steps, path, *,
  labels=None, fps=1, dpi=110)` and `animate_network(net,
  evidence_steps, path, *, fps=1)` — in `daf_jev.graphical_animation` —
  render the same walkthrough as GIFs (PillowWriter; `pillow` in the
  `figures` extra); the runner's `--animate` flag writes
  `posterior_animation.gif` + `network_animation.gif`.
  Keyword knobs: `to_mermaid` takes `direction` / `description_limit`;
  `plot_network` / `plot_posterior_trajectory` take `dpi` / `figsize`
  (the trajectory plotter also `labels`); `animate_network` /
  `animate_posterior` take `fps` / `dpi` (the posterior animation also
  `labels`); defaults unchanged.
- **Posteriors ingest** (`daf_jev.bayesnet_posteriors`) — fail-closed
  reader for GNN-emitted posterior sidecars:
  `load_posteriors(path, graphspec=None) -> PosteriorsSidecar` accepts
  both sibling variants — `dafjev.bayesnet-posteriors/1`
  (`{format, evidence, posteriors}`; raw Float64 rows under the flat
  per-row budget `|sum(row) - 1| <= 1e-6`, one-hot evidence rule) and
  the GNN-internal `gnn.marginals/1` (`{format, marginals,
  source_model}`; 6-digit-rounded rows with the length-widened row-sum
  budget) — optionally cross-checked against a `dafjev.bayesnet/1`
  GraphSpec. `pair_for_calibration(sidecar, assignments) ->
  CalibrationPairing` pairs Jev assignments against the sidecar as the
  calibration target (`(confidence, correct)` pairs — confidence is the
  exact posterior support for Jev's chosen state, correct is the
  modal-state match — plus per-variable soft multiclass Brier scores);
  `row_sum_deviations(sidecar)` reports per-variable `|sum(row) - 1|`.
  Surfaced as `daf-jev posteriors-load` and MCP `jev_posteriors_load`.

- **Questions** (`daf_jev.questions`) — `question_from_mapping(value, *,
  context="question")` builds a `NoulQuestion` / `ChoiceQuestion` /
  `ScoreQuestion` from a native `{type, instructions, criteria}` mapping
  with strict validation; the CLI (`evaluate --questions-file`) and the
  MCP server (`jev_ask` / `jev_evaluate`) route native mappings through it.
- **Docs snapshot** (`daf_jev.docs_verify`) —
  `verify_manifest(manifest_path)` re-hashes every page of the TypeSafe
  docs-snapshot manifest (flags `missing` / `drifted` / `added`); routed
  through `daf-jev docs-verify` and MCP `jev_docs_verify`.
- **Figures** (`daf_jev.figures`, `figures` extra) — `generate_all()`
  writes the 7 registry-named PNGs + `figure_registry.json` into the
  figures directory; data-driven figures read the newest
  `output/benchmarks/*.json` and raise `FileNotFoundError` (naming the
  missing JSON) rather than fabricating data.
- **Manuscript variables** (`daf_jev.manuscript_variables`) —
  `generate_variables` / `save_variables` derive the 49 `{{TOKEN}}`
  manuscript variables from pyproject, the docs MANIFEST, test counts,
  benchmark JSONs, and `manuscript/config.yaml` knobs; zero hardcoded
  results (strict default; `--allow-draft` for drafts).
- **CLI + MCP server** (`daf_jev.cli`, `daf_jev.mcp_server`) — the
  `daf-jev` console script (stdlib argparse, JSON to stdout, exit 0/1/2;
  see the CLI section below) and the FastMCP server (`build_server` /
  `main`, stdio only, JSON-safe tools, optional `mcp` extra).
- **Config** — package-root re-exports `load_settings`, `resolve_retry`,
  `resolve_timeout`; the API-key/base-URL resolvers live in
  `daf_jev.config` (`resolve_api_key`, `resolve_base_url`).

Runnable walkthroughs live in `examples/` (quickstart, triage router,
composite scoring, gated fallback, corpus evaluation, decision-point
decider, decider resilience, async evaluation, calibration walkthrough,
retry policies, provider dispatch, Asia Bayes net); each skips cleanly
without a key.

## Jev to RxInfer.jl pipeline (quick reference)

The cross-repo story: daf-jev elicits a discrete Bayes net from Jev, the
GNN repo's `rxinfer_bridge` compiles the GraphSpec to RxInfer.jl, Julia
computes marginals, and posteriors feed back into daf-jev. GraphSpec
`dafjev.bayesnet/1` is the stable interchange (coordinate any change
across both repos).

1. Elicit — `scripts/bayes_experiment.py` (`--provider`, `--model`,
   `--propose-structure`, `--animate`, `--out-dir`): `propose_structure` +
   `elicit_cpts`, two batched asks.
2. Artifacts — `output/experiments/asia/`: `asia_graphspec.json`
   (`dafjev.bayesnet/1` interchange), `network.png`,
   `posterior_trajectory.png`, `mermaid.txt`, `receipts.json`
   (per-run provenance + posterior trajectory).
3. Bridge — GNN `rxinfer_bridge` (branch `feat/rxinfer-bridge`,
   [PR #165](https://github.com/ActiveInferenceInstitute/Generalized_Notation_Notation/pull/165)):
   reads the GraphSpec, parses `.gnn` subsets, emits a deterministic
   RxInfer.jl `@model`.
4. Infer — from the GNN checkout:
   `julia --project=examples/rxinfer examples/rxinfer/asia_model.jl
   examples/rxinfer/asia_graphspec.json` — single-parent nets print exact
   marginals; the committed 8-node Asia spec stalls at multi-parent
   `DiscreteTransition` (upstream gap). `--out FILE` writes a
   `dafjev.bayesnet-posteriors/1` sidecar.
5. Feed back — posteriors re-enter daf-jev through
   `daf_jev.bayesnet_posteriors` (`load_posteriors` +
   `pair_for_calibration`; also `daf-jev posteriors-load` and MCP
   `jev_posteriors_load`) — calibration, evidence queries. Gap:
   single-parent nets exact end-to-end on RxInfer 5.5.0 / 5.5.2;
   multi-parent `DiscreteTransition` stalls in RxInfer 5.5.x VMP
   (upstream limitation).

Deep links (resolve from the repo checkout):

- [Graphical models](../../README.md#graphical-models) — user-facing walkthrough
- [Graphical models — architecture contract](../../docs/ARCHITECTURE.md#graphical-models)
  and [Provider dispatch](../../docs/ARCHITECTURE.md#provider-dispatch)
- [`graphical.py`](../../src/daf_jev/graphical.py) ·
  [`graphical_elicitation.py`](../../src/daf_jev/graphical_elicitation.py) ·
  [`graphical_viz.py`](../../src/daf_jev/graphical_viz.py) ·
  [`graphical_animation.py`](../../src/daf_jev/graphical_animation.py) ·
  [`bayesnet_posteriors.py`](../../src/daf_jev/bayesnet_posteriors.py)
- [`scripts/bayes_experiment.py`](../../scripts/bayes_experiment.py) ·
  [receipts.json](../../output/experiments/asia/receipts.json) (live run)

## CLI

```
daf-jev ask (--state-file FILE | --state TEXT) [--question ID=SPEC ...]
            [--model M] [--base-url URL] [--json | --pretty]
daf-jev models [--base-url URL] [--pick latest|first|last] [--contains STR]
daf-jev evaluate --questions-file PATH --states-file PATH
            [--concurrency N] [--model M] [--base-url URL]
            [--include-records]
daf-jev docs-verify [--manifest PATH]        # exit 1 on snapshot drift
daf-jev serve [--transport stdio]            # MCP server (stdio default)
daf-jev providers                           # registry listing (keyless, exit 0)
daf-jev posteriors-load FILE [--graphspec FILE]
                                           # validate a posterior sidecar
                                           # (keyless; exit 1 on invalid)
# global --provider KEY precedes any subcommand: daf-jev --provider kev models
```

Question SPEC grammar (commas escaped as `\,`): `noul:<instructions>`,
`choice:<instructions>:opt1=desc,opt2=...`, `score:<instructions>:l1,l2,...`.
Output is JSON; exit codes 0 ok / 1 runtime / 2 usage.

## Providers

One wire contract (`POST /v1/systemone`), six registered providers in
`daf_jev.providers`;
`daf-jev providers` prints the registry as JSON (keyless):

| key | backend | default base URL | default model | client key env |
| --- | --- | --- | --- | --- |
| `jev` | TypeSafe Jev (System One), hosted | `https://api.typesafe.ai` | `jev-latest` | `JEV_API_KEY` (then `TYPESAFE_API_KEY`) |
| `jeff` | GLiFormer (self-hosted) | `http://localhost:8000` | `jev-latest` | `JEFF_API_KEY` |
| `kev` | Qwen3.5 0.8B/4B/9B (self-hosted) | `http://localhost:8009` | `kev-latest` | `KEV_API_KEY` |
| `localjev` | GitHub Next GLiFormer proxy (TS/Bun, any OpenAI-compatible endpoint, MIT) | `http://127.0.0.1:8080` | `localjev-latest` | `LOCALJEV_API_KEY` |
| `openthai-systemone` | Thai/English Qwen3.5-0.8B slot-softmax (self-hosted, Apache-2.0) | `http://localhost:8077` | `openthai-latest` | `OPENTHAI_API_KEY` |
| `openrouter` | hosted proxy | `https://openrouter.ai/api` | `jev-latest` | `OPENROUTER_API_KEY` |

- CLI: global `--provider KEY` precedes the subcommand (invalid keys are
  usage errors, exit 2); precedence `--provider` > `DAF_JEV_PROVIDER` env
  var > `jev`. The `models` command is unsupported on `openthai-systemone`
  (no `/v1/models`) and `openrouter` (OpenRouter-shaped listing); the
  keyless error names the provider's primary key var (e.g. `KEV_API_KEY`).
- Python: `load_settings(provider="kev")` resolves that provider's
  env vars; `JevClient.for_provider("kev", ...)` /
  `AsyncJevClient.for_provider(...)`; `open_client(provider, **kwargs)` /
  `open_async_client(...)`; constructors also accept `provider=`.
  Unknown keys raise `ValueError` listing the available providers.
- Extension: `register_provider(ProviderSpec(key=..., ...))` adds a
  third-party spec at runtime; for custom HTTP behavior inject a
  `Transport` / `AsyncTransport` — the upstream/downstream seam. Provider
  keys are stable API.
- Naming: the official TypeSafe SDK convention is `TYPESAFE_API_KEY` /
  `TYPESAFE_BASE_URL` / `TYPESAFE_DEFAULT_MODEL`; daf-jev keeps `JEV_*` as
  its own primary names with `TYPESAFE_*` fallbacks, and every provider's
  key/base-URL tuples fall back to the `TYPESAFE_*` names last.
- Behavioral caveats live in the registry `notes` (see `daf-jev providers`):
  jeff — temperature-scaled probabilities, nominal output tokens; kev —
  extra top-level `latency_ms` (parsed and ignored); openrouter — extra
  `id` / `provider` / `usage.cost` fields (parsed and ignored).

## MCP

`daf-jev serve` exposes the toolkit to any MCP client. Tools (all return
JSON-safe dicts):

- `jev_ask` — one mixed noul/choice/score call over a state.
- `jev_evaluate` — run a question set over many states; summary only.
- `jev_models` — model cards, optionally filtered/picked.
- `jev_composite_score` — composite score from a probability dict.
- `jev_confidence_gate` / `jev_tiered_gate` — one- and two-threshold routing.
- `jev_docs_verify` — check the docs snapshot manifest for drift.
- `jev_posteriors_load` — load/validate a posterior sidecar
  (`dafjev.bayesnet-posteriors/1` or `gnn.marginals/1`); no API call,
  optional GraphSpec cross-check.
- Resource `jev://docs/snapshot` — `{page_count, snapshot_id, scraped_at,
  index_sha256}` from `docs/reference/MANIFEST.json`.

## Pitfalls

- **No mocks.** Tests never patch client internals; the network stand-in is a
  real local HTTP server (see `docs/ARCHITECTURE.md`). Keep that convention.
- **Keys.** `.env` is never committed; the API key is never printed or logged.
- **Confidence semantics.** Confidence summarizes how concentrated the
  answer's probability distribution is — not correctness or permission to
  act. Noul answers have no confidence field, so `confidence_gate` /
  `tiered_gate` raise `TypeError` on them; use noul probabilities directly.
- **Composite weights** are distribution re-weightings, not score multipliers:
  scale-invariant, mass must land on probable levels.
- **Thresholds are domain-specific.** Calibrate on your own data
  (`expected_calibration_error`, `reliability_table`) before trusting
  defaults; keep question text and threshold constants in one reviewable place.
