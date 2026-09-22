---
name: daf-jev
description: >
  Build with the daf-jev Python client for the TypeSafe Jev (System One) API:
  typed question builders (noul/choice/score), sync and async clients,
  concurrent evaluation, composable decision patterns (composite scoring,
  confidence and tiered gates), usage accounting (UsageLedger), an opt-in
  circuit breaker, calibration utilities, a CLI, an MCP server, and
  multi-provider dispatch (jev, jeff, kev, localjev, openthai-systemone,
  openrouter). Use when writing or reviewing daf-jev code, integrating
  System One judgments into a Python project, evaluating a question set
  over many states, wiring Jev tools into an MCP-capable agent, or pointing
  the toolkit at a self-hosted System One server.
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

- **Builders** — `noul(instructions, *, true_desc=None, false_desc=None)`,
  `choice(instructions, options: Mapping[str, str | None])`,
  `score(instructions, levels: Sequence[str])` (>= 2 levels);
  `QuestionSet()` with `.add(id, q)`, `.merge(other)`, `.to_wire()`.
- **Clients** — `JevClient(api_key=None, *, base_url=None, model=None, ...)`
  (`model=None` resolves `JEV_MODEL` / `TYPESAFE_DEFAULT_MODEL`, then
  `jev-latest`), `.ask(state, questions, *, model=None, timeout=None,
  request_headers=None) -> SystemOneResponse` (answers by id; cached views
  `.nouls` / `.choices` / `.scores`; `.usage`; `.request_id`).
  `AsyncJevClient` has the same surface, async. Errors form a
  `TypeSafeError` hierarchy; 429/529 retry per `RetryPolicy`.
- **Evaluation** — `Evaluator(client, questions, *, concurrency=...)`
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
- **Models** — `client.models(*, timeout=None, request_headers=None) ->
  list[ModelCard]` (same per-call params as `ask`, retried per policy);
  `pick_model(cards, *, contains=None, prefer="latest")`.
- **Calibration** (`daf_jev.calibration`, pure): `bucket_index(confidence,
  n_buckets=10)`, `reliability_table(pairs, *, n_buckets=10)`,
  `expected_calibration_error(pairs, *, n_buckets=10)`,
  `brier_score(pairs)` — pairs are `(confidence, correct: bool)` tuples.
- **Config** — package-root re-exports `load_settings`, `resolve_retry`,
  `resolve_timeout`; the API-key/base-URL resolvers live in
  `daf_jev.config` (`resolve_api_key`, `resolve_base_url`).

Runnable walkthroughs live in `examples/` (quickstart, triage router,
composite scoring, gated fallback, corpus evaluation, decision-point
decider, provider dispatch); each skips cleanly without a key.

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
# global --provider KEY precedes any subcommand: daf-jev --provider kev models
```

Question SPEC grammar (commas escaped as `\,`): `noul:<instructions>`,
`choice:<instructions>:opt1=desc,opt2=...`, `score:<instructions>:l1,l2,...`.
Output is JSON; exit codes 0 ok / 1 runtime / 2 usage.

## Providers

One wire contract (`POST /v1/systemone`), six registered providers;
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
