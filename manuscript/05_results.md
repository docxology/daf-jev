# Results: Batching Economics, Pipeline Latency, and Confidence Calibration under Live-API Load {#sec:results}

This section reports the three live-API benchmarks that quantify the design claims of [@sec:methodology]: the batching benchmark, which reproduces the documented parallel-questions pattern [@typesafe2026patterns], the decision-pattern latency benchmark, and the self-consistency calibration benchmark. All run against the real {{BENCH_MODEL}} model; every value below is injected from the benchmark outputs at render time, and the figures are regenerated from the same JSON files, so prose, tables, and figures share one source of truth. The batching and latency results reported here were recorded on {{BENCH_DATE}}; the calibration results on {{BENCH_CALIB_DATE}}.

## Batching speedup and token cost

The batching benchmark compares two strategies over the same state and question mix: one call carrying all questions in a batch, versus one sequential single-question call per question, repeated for each configured batch width over multiple measured runs. The answers are unchanged by batching (the parallel-sampler semantics of [@sec:jev_model]); what changes is wall time — a single round trip versus one round trip per question — and token cost, because the sequential strategy re-sends the state once per question.

[@fig:batching] shows the measured speedup per batch width together with the token-cost ratio on a secondary axis.

![Batching speedup of the {{BENCH_MODEL}} model versus sequential single-question calls, measured by `benchmarks/bench_batching.py` on {{BENCH_DATE}} against the live API. Bars give the wall-time speedup of one batched call over one sequential call per question for each configured batch width ({{CONFIG_BATCHING_N5}}, {{CONFIG_BATCHING_N10}}, and {{CONFIG_BATCHING_N20}} questions per batch, tabulated in [@tbl:batching]); the secondary axis traces the token-cost ratio — sequential tokens divided by batched tokens — which rises above unity because the sequential strategy re-sends the state paragraph once per question. Each bar is annotated with its measured value, and the rendered title carries the model identifier and run date read from the benchmark JSON itself. The takeaway: the speedup grows with batch width as the fixed per-call overhead amortizes, while the batched strategy is simultaneously cheaper in tokens, not only faster.](../output/figures/batching_speedup.png){#fig:batching width=85%}

[@tbl:batching] tabulates the measured speedups. The speedup grows with batch width, as expected from the round-trip accounting: the fixed per-call overhead is amortized over more questions, and the state is transmitted once rather than once per question.

| Questions per batch | Wall-time speedup vs sequential |
|---------------------|---------------------------------|
| {{CONFIG_BATCHING_N5}} | {{BENCH_BATCHING_SPEEDUP_N5}} |
| {{CONFIG_BATCHING_N10}} | {{BENCH_BATCHING_SPEEDUP_N10}} |
| {{CONFIG_BATCHING_N20}} | {{BENCH_BATCHING_SPEEDUP_N20}} |

: Wall-time speedup of one batched call versus one sequential call per question, per configured batch width, recorded by `benchmarks/bench_batching.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:batching}

Token cost moves in the same direction. The recorded `token_cost_ratio` expresses the sequential strategy's token consumption relative to the batched strategy's: at the widest configured batch width the sequential strategy consumes {{BENCH_BATCHING_TOKEN_RATIO_N20}} times the tokens of the batched call. The state paragraph dominates the input tokens of a single-question call, so re-sending it per question makes the sequential strategy strictly more expensive in addition to being slower.

## Decision-pipeline latency

The second benchmark measures end-to-end latency of two composition pipelines — the network call plus the local composition logic, exactly as an application would run them:

- **composite_score** — one `score` call, then `composite_score` over the answer, then a `confidence_gate` verdict;
- **intent_routing** — one `choice` call, then `route()` dispatching to a trivial handler.

Each pipeline is executed {{BENCH_PATTERNS_RUNS}} times; [@tbl:latency] reports the median (p50) and tail (p95) wall times per pipeline, and [@fig:latency] plots them side by side.

![Median (p50) and tail (p95) end-to-end wall time per decision pipeline, measured by `benchmarks/bench_patterns.py` over {{BENCH_PATTERNS_RUNS}} runs against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Each pipeline group — composite scoring (one `score` call, then `composite_score` and a `confidence_gate` verdict) and intent routing (one `choice` call, then `route()` dispatch) — shows paired p50/p95 bars covering the full network round trip plus the local composition logic; values are tabulated in [@tbl:latency] and read from the benchmark JSON fields at figure-generation time. The takeaway: both pipelines sit within the model's millisecond-scale latency envelope, so the pure-logic composition layer adds no measurable latency beyond the network round trip and the gating policy can run inline on interactive request paths.](../output/figures/latency_percentiles.png){#fig:latency width=85%}

| Pipeline | Median wall time, p50 (s) | Tail wall time, p95 (s) |
|--------------------|---------------------------|-------------------------|
| composite_score | {{BENCH_PATTERNS_COMPOSITE_P50_S}} | {{BENCH_PATTERNS_COMPOSITE_P95_S}} |
| intent_routing | {{BENCH_PATTERNS_ROUTING_P50_S}} | {{BENCH_PATTERNS_ROUTING_P95_S}} |

: End-to-end wall time (network round trip plus local composition logic) per decision pipeline, median and tail over {{BENCH_PATTERNS_RUNS}} runs recorded by `benchmarks/bench_patterns.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:latency}

## Calibration

Latency says nothing about whether the composed decisions are trustworthy, so the third benchmark measures how far the model's reported confidence tracks its own agreement behaviour. `benchmarks/bench_calibration.py` runs {{BENCH_CALIB_STATES}} short states {{BENCH_CALIB_REPEATS}} times each against the {{BENCH_CALIB_MODEL}} model and scores choice answers under a *self-consistency proxy*: a sample counts as correct when it agrees with the modal choice across the repeats of the same state. Because a yes/no probability carries no per-sample label to agree with, noul answers are scored for repeat-to-repeat stability instead, via the mean absolute gap between every pair of repeated answers. No external ground truth is consulted anywhere in this benchmark — the correctness proxy is self-agreement, not verified outcomes.

[@tbl:calibration] reports the aggregate scores over the run, and [@fig:calibration] plots the reliability curve per confidence bucket.

| Metric | Value |
|--------|-------|
| Expected calibration error (choice, proxy) | {{BENCH_CALIB_ECE}} |
| Brier score (choice, proxy) | {{BENCH_CALIB_BRIER}} |
| Mean pairwise noul gap | {{BENCH_CALIB_MEAN_GAP}} |

: Calibration summary over {{BENCH_CALIB_STATES}} states × {{BENCH_CALIB_REPEATS}} repeats recorded by `benchmarks/bench_calibration.py` against the {{BENCH_CALIB_MODEL}} model on {{BENCH_CALIB_DATE}}. Choice correctness is a self-consistency proxy — agreement with the modal choice across repeats — not accuracy against ground truth; the mean pairwise noul gap measures repeat-to-repeat answer stability rather than correctness. Values are injected from the benchmark JSON at render time. {#tbl:calibration}

![Reliability diagram of choice-answer confidence under the self-consistency proxy, measured by `benchmarks/bench_calibration.py` over {{BENCH_CALIB_STATES}} states × {{BENCH_CALIB_REPEATS}} repeats against the {{BENCH_CALIB_MODEL}} model on {{BENCH_CALIB_DATE}}. Each point is a confidence bucket plotting mean reported confidence against proxy accuracy, where proxy accuracy is agreement with the modal choice across repeats of the same state; the dashed diagonal marks perfect agreement between stated confidence and observed proxy accuracy. Because the proxy scores self-agreement rather than verified correctness, proximity to the diagonal indicates consistency between stated confidence and repeat-stable behaviour — not truthfulness about the world. Aggregate scores are tabulated in [@tbl:calibration].](../output/figures/calibration_reliability.png){#fig:calibration width=85%}

The expected calibration error of {{BENCH_CALIB_ECE}} and the Brier score of {{BENCH_CALIB_BRIER}} indicate that reported choice confidence is broadly consistent with the proxy labels, and the mean pairwise noul gap of {{BENCH_CALIB_MEAN_GAP}} shows that repeated noul answers on the same state are nearly identical. These claims extend exactly as far as the proxy does. Self-consistency can establish that the model is stable across repeats and that its confidence ordering is internally coherent; it cannot certify that the answers are correct about the world, because the proxy labels are generated by the same model whose calibration is being measured. The benchmark is therefore evidence of calibrated, repeatable decision behaviour under a reproducible proxy — a necessary, not sufficient, condition for deploying these gates on real decisions.

## Interpretation

Four observations tie the measurements back to the design rulings of [@sec:methodology]. First, the batching speedups in [@tbl:batching] confirm that the parallel-sampler semantics translate directly into wall-clock savings: the batched strategy is faster at every configured width, and the gap widens with width exactly as the round-trip accounting predicts. Second, the token-cost ratio above unity at the widest width — the sequential strategy's token consumption relative to the batched call's — shows that batching is not merely faster but cheaper, because the state is transmitted once — so the pattern documented in the primary source [@typesafe2026patterns] holds end to end for a third-party client implementation. Third, the pipeline latencies in [@tbl:latency] sit within the model's millisecond-scale latency envelope ([@sec:jev_model]): the pure-logic composition layer adds no measurable latency beyond the network round trip, which is precisely what allows confidence-gated routing to run inline on interactive request paths rather than in a background queue. Fourth, the calibration summary in [@tbl:calibration] supports the calibrated-decision premise of the confidence-gated patterns described in [@sec:methodology] — reported choice confidence aligns with repeat-stable behaviour, and noul answers are stable across repeats — under the self-consistency proxy semantics stated in the Calibration section, and only as far as those semantics extend.
