# daf-jev Benchmarks

Live-API benchmarks for the two documented TypeSafe patterns this package
implements. Both scripts use the real network and the real key, so they are
**not** part of the test suite.

## Requirements

- A real API key: `JEV_API_KEY` (preferred) or `TYPESAFE_API_KEY`, from the
  process environment or the project `.env`. Without a key both scripts print
  `SKIP: JEV_API_KEY not set` and exit 0 — they never raise.
- The package importable (`uv run` handles the src layout).

## bench_batching.py — parallel-questions claim

Reproduces `docs/reference/cookbooks/parallel_questions.md`: for each
N in {5, 10, 20} it compares

- **batched** — one call carrying all N questions, vs
- **single** — N sequential single-question calls,

over the same short state paragraph (20 real questions, noul/choice/score mix;
each N uses the first N). The answers are unchanged by batching; what changes
is wall time (one round trip vs N) and tokens (the state is re-sent N times).
The table reports mean wall seconds per strategy, the speedup ratio, total
tokens for each side, and the token-cost ratio.

```bash
uv run python benchmarks/bench_batching.py --runs 3 --model jev-latest
```

`--runs` (default 3) repeats each strategy per N; `--model` defaults to
`jev-latest`.

## bench_patterns.py — decision-pattern latency

Measures end-to-end latency (network call + local composition logic) of:

- **composite_score** — one Score call → `composite_score` →
  `confidence_gate` (docs/reference/patterns/composite-scoring.md,
  confidence-routing.md), and
- **intent_routing** — one Choice call → `route()` dispatching to a trivial
  handler (docs/reference/patterns/confidence-routing.md).

Each pipeline runs `--runs` times (default 10); the table reports mean, p50,
and p95 wall seconds plus total tokens. With `--async` the same runs are
executed concurrently through `AsyncJevClient` + `asyncio.gather` and compared
against the sequential wall time.

```bash
uv run python benchmarks/bench_patterns.py --runs 10 --model jev-latest
uv run python benchmarks/bench_patterns.py --runs 10 --async
```

## Output

JSON results are written to deterministic filenames under `output/benchmarks/`:

- `output/benchmarks/batching_<YYYYMMDD>.json`
- `output/benchmarks/patterns_<YYYYMMDD>.json`

The directory is created with parents on first write. Each payload records the
model, run count, and per-measurement numbers described above; `_util.py`
holds the shared key-resolution (graceful SKIP), percentile, and JSON-writer
helpers.
