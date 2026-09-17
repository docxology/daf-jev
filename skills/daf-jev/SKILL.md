---
name: daf-jev
description: >
  Build with the daf-jev Python client for the TypeSafe Jev (System One) API:
  typed question builders (noul/choice/score), sync and async clients,
  concurrent evaluation, composable decision patterns (composite scoring,
  confidence and tiered gates), calibration utilities, a CLI, and an MCP
  server. Use when writing or reviewing daf-jev code, integrating System One
  judgments into a Python project, evaluating a question set over many states,
  or wiring Jev tools into an MCP-capable agent.
---

# daf-jev

`daf-jev` is a thin, composable Python client for `POST /v1/systemone`. Code
owns the workflow; Jev returns typed answers and probabilities. Package source
of truth: `docs/ARCHITECTURE.md`; live-API facts: `docs/reference/`.

## Install

```bash
uv sync --extra dev      # or: pip install -e ".[dev]"
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
- **Clients** — `JevClient(api_key=None, *, base_url=None, model="jev-latest",
  ...)`, `.ask(state, questions, *, model=None) -> SystemOneResponse`
  (answers by id; cached views `.nouls` / `.choices` / `.scores`; `.usage`;
  `.request_id`). `AsyncJevClient` has the same surface, async. Errors form a
  `TypeSafeError` hierarchy; 429/529 retry per `RetryPolicy`.
- **Evaluation** — `Evaluator(client, questions, *, concurrency=...)`
  `.evaluate(states) -> list[EvaluationRecord]`, `.summary()` for aggregates.
- **Compose** (`daf_jev.compose`, pure over answers):
  - `composite_score(answer, weights=None)` — expected value over sorted level
    indices; `weights` re-weight the probability distribution (only ratios
    matter; result stays within the level index range).
  - `confidence_gate(answer, *, threshold, below="review")` — primary value
    when `answer.confidence >= threshold`, else `below`.
  - `tiered_gate(answer, *, high=0.85, low=0.6, high_label="automate",
    middle_label="review", low_label="escalate")` — two-threshold routing.
  - `route(answer, handlers, *, min_confidence=0.0, fallback=None)` and
    `pick(actions, choices)` for dispatch to callables.
- **Models** — `client.models() -> list[ModelCard]`;
  `pick_model(cards, *, contains=None, prefer="latest")`.
- **Calibration** (`daf_jev.calibration`, pure): `bucket_index(confidence,
  n_buckets=10)`, `reliability_table(pairs, *, n_buckets=10)`,
  `expected_calibration_error(pairs, *, n_buckets=10)`,
  `brier_score(pairs)` — pairs are `(confidence, correct: bool)` tuples.
- **Config** — `load_settings()`; resolvers `resolve_api_key`,
  `resolve_base_url`, `resolve_retry`, `resolve_timeout`.

Runnable walkthroughs live in `examples/` (quickstart, triage router,
composite scoring, corpus evaluation); each skips cleanly without a key.

## CLI

```
daf-jev ask (--state-file FILE | --state TEXT) [--question ID=SPEC ...]
            [--model M] [--json | --pretty]
daf-jev models [--pick latest|first|last] [--contains STR]
daf-jev evaluate --questions-file PATH --states-file PATH
            [--concurrency N] [--include-records]
daf-jev docs-verify [--manifest PATH]        # exit 1 on snapshot drift
daf-jev serve [--transport stdio]            # MCP server (stdio default)
```

Question SPEC grammar (commas escaped as `\,`): `noul:<instructions>`,
`choice:<instructions>:opt1=desc,opt2=...`, `score:<instructions>:l1,l2,...`.
Output is JSON; exit codes 0 ok / 1 runtime / 2 usage.

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
