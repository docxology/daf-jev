# daf-jev Benchmarks

Live-API benchmarks for the documented TypeSafe patterns this package
implements. All three scripts use the real network and the real key, so
they are **not** part of the test suite.

## Requirements

- A real API key: `JEV_API_KEY` (preferred) or `TYPESAFE_API_KEY`, from the
  process environment or the project `.env`. Without a key all three
  scripts print `SKIP: JEV_API_KEY not set` and exit 0 — they never raise.
- The package importable (`uv run` handles the src layout).

## [`bench_batching.py`](bench_batching.py) — parallel-questions claim

Reproduces
[`docs/reference/cookbooks/parallel_questions.md`](../docs/reference/cookbooks/parallel_questions.md):
for each N in {5, 10, 20} it compares

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

## [`bench_patterns.py`](bench_patterns.py) — decision-pattern latency

Measures end-to-end latency (network call + local composition logic) of:

- **composite_score** — one Score call →
  [`composite_score`](../src/daf_jev/compose.py) →
  [`confidence_gate`](../src/daf_jev/compose.py)
  ([docs](../docs/reference/patterns/composite-scoring.md),
  [docs](../docs/reference/patterns/confidence-routing.md)), and
- **intent_routing** — one Choice call →
  [`route()`](../src/daf_jev/compose.py) dispatching to a trivial handler
  ([docs](../docs/reference/patterns/confidence-routing.md)).

Each pipeline runs `--runs` times (default 10); the table reports mean, p50,
and p95 wall seconds plus total tokens. With `--async` the same runs are
executed concurrently through
[`AsyncJevClient`](../src/daf_jev/client.py) + `asyncio.gather` and compared
against the sequential wall time.

```bash
uv run python benchmarks/bench_patterns.py --runs 10 --model jev-latest
uv run python benchmarks/bench_patterns.py --runs 10 --async
```

## [`bench_calibration.py`](bench_calibration.py) — confidence calibration

Measures self-consistency calibration: for each of N short distinct states,
the same three-option choice question is asked R times, and agreement with
the modal choice across repeats is treated as a **self-consistency
correctness proxy — not ground truth**. The resulting `(confidence,
correct)` pairs feed the pure
[`daf_jev.calibration`](../src/daf_jev/calibration.py) functions (ECE,
Brier, reliability table); a noul question repeated the same way yields a
mean pairwise |Δnoul| stability metric. A failing call drops that state's
repeats into `n_errors` instead of aborting the batch.

```bash
uv run python benchmarks/bench_calibration.py
# flags: --states N (default 6), --repeats N (default 5), --model NAME
```

**Caveat:** never present the ECE/Brier figures as ground-truth accuracy —
they quantify confidence-vs-self-consistency only.

## Output

JSON results are written to deterministic filenames under `output/benchmarks/`:

- `output/benchmarks/batching_<YYYYMMDD>.json`
- `output/benchmarks/patterns_<YYYYMMDD>.json`
- `output/benchmarks/calibration_<YYYYMMDD>.json`

The directory is created with parents on first write (the writer lives in
[`_util.py`](_util.py)). Each payload records the model, run count, and
per-measurement numbers described above.

### Committed receipts

One receipt per script is committed under `output/benchmarks/`
(date-stamped: a re-run writes today's date, so the committed files stay
stable):

| Script | Receipt | Headline numbers |
|---|---|---|
| [`bench_batching.py`](bench_batching.py) | [`batching_20260916.json`](../output/benchmarks/batching_20260916.json) | `jev-latest`, 2 runs; batch-vs-single speedup 3.98× / 8.77× / 18.55× at N=5/10/20; token-cost ratio 2.80× → 4.22×. |
| [`bench_patterns.py`](bench_patterns.py) | [`patterns_20260916.json`](../output/benchmarks/patterns_20260916.json) | `jev-latest`, 6 runs; composite_score pipeline mean 0.154 s (p95 0.242 s), intent_routing mean 0.128 s (p95 0.152 s). |
| [`bench_calibration.py`](bench_calibration.py) | [`calibration_20260916.json`](../output/benchmarks/calibration_20260916.json) | `jev-latest`, 6 states × 5 repeats; ECE 0.073, Brier 0.0252, mean pairwise \|Δnoul\| 0.005, 0 dropped states (self-consistency proxy, not ground truth). |
