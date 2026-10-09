# daf-jev Benchmarks

The explicit `daf-jev benchmark` pipeline compares local/hosted model arms and
supervised baselines over prepared synthetic and public labeled datasets. Start
with [the command protocol](../docs/decision_benchmarking.md),
[dataset provenance](../docs/datasets.md) and
[provider contracts](../docs/providers.md) and
[local serving](../docs/local_serving.md). Config recipes live in
`configs/synthetic.yaml` (uniform and exact-rule synthetic controls),
`configs/offline.yaml`, `configs/local-mac.yaml`, `configs/pilot.yaml` and
`configs/native-jev-pilot.yaml`. The hosted pilot is a native decision-model
cohort. The Jev recipe pins the Decisions endpoint and TypeSafe route; generative
chat models are excluded from this cohort. Complete source snapshots and the
existing shared-allocation binding must be frozen before execution.
Plan creates an immutable UUID run without inference; run/resume execute it;
report reduces its retained journal offline. A catalog snapshot is an explicit
public GET and does not demonstrate inference access.

The requested warm comparison has 100 shared physical test examples overall,
reused across all models and five additional repetitions. The retained legacy
selector applied `timing_samples` per dataset; the retained Mac study had an
expanded 368-ID timing cohort and stopped after an early clean boundary. These
recipes and old manifests cannot establish the corrected global protocol by
changing a description or selecting a retrospective subset. A new accepted
source/manifest freezes the global ID pack and preserves unsupported cases,
separate complete matched quality-control bundles and the remaining cumulative
profile allowances. Current planning defaults to `timing_sampling_scope: cohort`
and rejects an insufficient exact pool; explicit `per_dataset` keeps the legacy
capped behavior. See
[the scope rules](../docs/decision_benchmarking.md#shared-timing-cohort-and-the-retained-scope-deviation).

Compare supplied numerical rows with their actual interpretation. Native origin
does not establish a calibrated posterior; generated labels have no probability
vector. [Provider semantics](../docs/providers.md#probability-meaning-and-confidence)
and [reproduction chronology](../docs/reproducibility.md#clean-stop-and-prospective-cohort-correction)
state the boundaries of current results and prospective controls.

The four scripts below retain the legacy live-API receipt lane. Their
credential resolution, schemas and proxy semantics differ from the new runner.

Live-API benchmarks for the documented TypeSafe patterns this package
implements. All four scripts use the real network and the real key, so
they are **not** part of the test suite.

## Requirements

- A real API key: `JEV_API_KEY` (preferred) or `TYPESAFE_API_KEY`, from the
  process environment or the project `.env`. Without a key all four
  scripts print `SKIP: JEV_API_KEY not set` and exit 0 — they never raise.
- Multi-provider: per-provider keys `JEV_API_KEY` / `JEFF_API_KEY` /
  `KEV_API_KEY` resolve per provider (registry defaults `localhost:8000`
  jeff, `localhost:8009` kev — see
  [`docs/models.md` §10](../docs/models.md#10-sibling-system-one-servers-jeff-and-kev)).
  A provider without its key prints `SKIP[<provider>]` and the run
  continues; missing all keys prints a global `SKIP` line and exits 0 —
  scripts never raise.
- The package importable (`uv run` handles the src layout).

## [`bench_batching.py`](bench_batching.py) — parallel-questions claim

Reproduces
[`docs/reference/cookbooks/parallel_questions.md`](../docs/reference/cookbooks/parallel_questions.md):
for each N in {5, 10, 20} it compares

- **batched** — one call carrying all N questions, vs
- **single** — N sequential single-question calls,

over the same short state paragraph (20 real questions, noul/choice/score mix;
each N uses the first N). It measures wall time (one round trip vs N) and
tokens (the state is re-sent N times). Historical receipts did not retain paired
answers and therefore do not establish answer equivalence.
The table reports mean wall seconds per strategy, the speedup ratio, total
tokens for each side, and the total-token ratio (historically named
`token_cost_ratio`). This is not a USD cost ratio; input/output prices and actual
charges require separate accounting.

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

## [`bench_jaggedness.py`](bench_jaggedness.py) — model jaggedness (uniformity of stochastic prompts)

Measures how far a provider's answers to **stochastic prompts** (coin flips,
six-sided rolls) deviate from their stated uniform distributions. Each
fixture is repeated `--repeats` times and the chosen labels feed:

- **uniformity deviation** — chi-square against uniform (with p-value) and
  total variation / max per-outcome deviation from 1/k;
- **degeneracy** — whether identical repeats always choose the same label;
  deterministic servers make the choice a point mass, which is itself the
  finding;
- **order rotation** — options are rotated across asks; reports position
  bias slope and argmax flips;
- **concurrent wobble** — a concurrent batch re-asked side by side,
  reporting max pairwise probability spread;
- **noul-vs-choice delta** — the same coin asked as a noul yes/no question
  vs a heads/tails choice; the cross-instrument gap is the
  `noul_choice_delta` figure.

```bash
uv run python benchmarks/bench_jaggedness.py --providers jeff,kev
# flags: --providers 'jeff,kev,jev' (comma list), --fixtures (subset),
# --repeats 50, --concurrent 32, --timeout, --model
```

**Caveat:** the numbers quantify deviation from the stated distribution,
NOT accuracy. Local self-hosted servers (jeff: temperature-scaled
sigmoids; kev: discriminative pointer head) behave differently from the hosted
jev endpoint.

## Output

New JSON receipts are exclusively written to unique UTC/UUID filenames under
`output/benchmarks/`:

- `output/benchmarks/batching_<UTC>_<UUID>.json`
- `output/benchmarks/patterns_<UTC>_<UUID>.json`
- `output/benchmarks/calibration_<UTC>_<UUID>.json`
- `output/benchmarks/jaggedness_<UTC>_<UUID>.json`

The directory is created with parents on first write (the writer lives in
[`_util.py`](_util.py)). Each payload records the model, run count, and
per-measurement numbers described above. The shared writer records receipt ID,
UTC generation time and the nearest-rank percentile method, rejects nonfinite
JSON and refuses overwrite. Old dated receipts remain unchanged. Their missing
runtime/cost/answer evidence stays unknown; newer receipt fields do not apply
retroactively.

### Committed receipts

One receipt per script is committed under `output/benchmarks/`
(historical receipts remain stable; a new run creates a new file):

| Script | Receipt | Headline numbers |
|---|---|---|
| [`bench_batching.py`](bench_batching.py) | [`batching_20260916.json`](../output/benchmarks/batching_20260916.json) | `jev-latest`, 2 runs; batch-vs-single speedup 3.98× / 8.77× / 18.55× at N=5/10/20; total-token ratio 2.80× → 4.22×, not reported USD savings. |
| [`bench_patterns.py`](bench_patterns.py) | [`patterns_20260916.json`](../output/benchmarks/patterns_20260916.json) | `jev-latest`, 6 runs; composite_score pipeline mean 0.154 s (p95 0.242 s), intent_routing mean 0.128 s (p95 0.152 s). |
| [`bench_calibration.py`](bench_calibration.py) | [`calibration_20260916.json`](../output/benchmarks/calibration_20260916.json) | `jev-latest`, 6 states × 5 repeats; ECE 0.073, Brier 0.0252, mean pairwise \|Δnoul\| 0.005, 0 dropped states (self-consistency proxy, not ground truth). |
| [`bench_jaggedness.py`](bench_jaggedness.py) | [`jaggedness_20260924.json`](../output/benchmarks/jaggedness_20260924.json) | jeff (GLiFormer) + kev-0.8b, 50 repeats × 32 concurrent × 2–7 orders per fixture; every fair-process fixture rejects uniform (coin chi² 50.0 / df 1, d6 chi² 250.0 / df 5, both p ≈ 0); both backends degenerate (50/50 one label); order shift up to 0.104 with one argmax flip each; jeff noul-vs-choice Δ 0.137, kev 0.011. |

End-to-end pattern timings include transport and composition; no isolated
composition-overhead baseline was recorded. Small samples do not establish a
service latency guarantee. Ground-truth calibration, cross-model quality,
reconciled hosted USD and measured local compute cost belong to the explicit
new experiment lane and require actual execution receipts.
