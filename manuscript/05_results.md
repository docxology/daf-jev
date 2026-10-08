# Results: Historical Measurements, CPU Comparators, and Execution Coverage {#sec:results}

This section separates historical native API measurements from later CPU comparator studies, partial local-model execution and a halted hosted probe. The historical batching benchmark implements the documented parallel-questions pattern [@typesafe2026patterns], alongside decision-pattern latency and self-consistency measurements. These historical receipts identify their requested model aliases, rather than a pinned weight identity. Every value below is injected from the explicitly selected benchmark outputs at render time; figures must use that same evidence selection. The batching and latency results reported here were recorded on {{BENCH_DATE}}; the calibration results on {{BENCH_CALIB_DATE}}.

## Historical batching speedup and total-token use

The batching benchmark compares two strategies over the same state and question mix: one call carrying all questions in a batch, versus one sequential single-question call per question, repeated for each configured batch width over multiple measured runs. The retained historical receipts measure wall time and token usage. They do not retain paired answers, so they do not establish that batching left the decisions unchanged. The sequential strategy re-sends the state once per question, while batching shares a round trip and state transmission.

[@fig:batching] shows the measured speedup per batch width and the total-token ratio in separate panels.

![Batching speedup of the {{BENCH_MODEL}} model versus sequential single-question calls, measured by `benchmarks/bench_batching.py` on {{BENCH_DATE}} against the live API. Bars give the wall-time speedup of one batched call over one sequential call per question for each configured batch width ({{CONFIG_BATCHING_N5}}, {{CONFIG_BATCHING_N10}}, and {{CONFIG_BATCHING_N20}} questions per batch, tabulated in [@tbl:batching]); a separate panel shows the total-token ratio, sequential tokens divided by batched tokens. The sequential strategy re-sends the state paragraph once per question. Each bar is annotated with its measured value, and the rendered title carries the model identifier and run date read from the benchmark JSON itself. The takeaway: the speedup grows with batch width as the fixed per-call overhead amortizes, while the batched strategy uses fewer total tokens in this recorded workload.](../output/figures/batching_speedup.png){#fig:batching width=85%}

[@tbl:batching] tabulates the measured speedups. The speedup grows with batch width, as expected from the round-trip accounting: the fixed per-call overhead is amortized over more questions, and the state is transmitted once rather than once per question.

| Questions per batch | Wall-time speedup vs sequential |
|---------------------|---------------------------------|
| {{CONFIG_BATCHING_N5}} | {{BENCH_BATCHING_SPEEDUP_N5}} |
| {{CONFIG_BATCHING_N10}} | {{BENCH_BATCHING_SPEEDUP_N10}} |
| {{CONFIG_BATCHING_N20}} | {{BENCH_BATCHING_SPEEDUP_N20}} |

: Wall-time speedup of one batched call versus one sequential call per question, per configured batch width, recorded by `benchmarks/bench_batching.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:batching}

Recorded total-token use moves in the same direction. The recorded `token_cost_ratio` expresses the sequential strategy's token consumption relative to the batched strategy's: at the widest configured batch width the sequential strategy consumes {{BENCH_BATCHING_TOKEN_RATIO_N20}} times the tokens of the batched call. This ratio measures total tokens, not reported USD. Input/output prices, provider surcharges and retries can differ; these historical receipts do not establish monetary savings.

## Historical decision-pipeline latency

The second benchmark measures end-to-end latency of two composition pipelines — the network call plus the local composition logic, exactly as an application would run them:

- **composite_score** — one `score` call, then `composite_score` over the answer, then a `confidence_gate` verdict;
- **intent_routing** — one `choice` call, then `route()` dispatching to a trivial handler.

Each pipeline is executed {{BENCH_PATTERNS_RUNS}} times; [@tbl:latency] reports the median (p50) and tail (p95) wall times per pipeline, and [@fig:latency] plots them side by side.

![Median (p50) and tail (p95) end-to-end wall time per decision pipeline, measured by `benchmarks/bench_patterns.py` over {{BENCH_PATTERNS_RUNS}} runs against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Each pipeline group — composite scoring (one `score` call, then `composite_score` and a `confidence_gate` verdict) and intent routing (one `choice` call, then `route()` dispatch) — shows paired p50/p95 bars covering the full network round trip plus the local composition logic; values are tabulated in [@tbl:latency] and read from the benchmark JSON fields at figure-generation time. The bars describe these observed sessions. No isolated transport or composition baseline was recorded, so the figure does not estimate composition overhead or establish a service-level latency guarantee.](../output/figures/latency_percentiles.png){#fig:latency width=85%}

| Pipeline | Median wall time, p50 (s) | Tail wall time, p95 (s) |
|--------------------|---------------------------|-------------------------|
| composite_score | {{BENCH_PATTERNS_COMPOSITE_P50_S}} | {{BENCH_PATTERNS_COMPOSITE_P95_S}} |
| intent_routing | {{BENCH_PATTERNS_ROUTING_P50_S}} | {{BENCH_PATTERNS_ROUTING_P95_S}} |

: End-to-end wall time (network round trip plus local composition logic) per decision pipeline, median and tail over {{BENCH_PATTERNS_RUNS}} runs recorded by `benchmarks/bench_patterns.py` against the {{BENCH_MODEL}} model on {{BENCH_DATE}}. Values are injected from the benchmark JSON at render time. {#tbl:latency}

## Historical proxy-agreement and repeat stability

The third historical benchmark compares reported confidence with repeat agreement, rather than measuring decision correctness against an independent label. `benchmarks/bench_calibration.py` runs {{BENCH_CALIB_STATES}} short states {{BENCH_CALIB_REPEATS}} times each against the {{BENCH_CALIB_MODEL}} model and scores choice answers under a *self-consistency proxy*: a sample counts as correct when it agrees with the modal choice across the repeats of the same state. Because a yes/no probability carries no per-sample label to agree with, noul answers are scored for repeat-to-repeat stability instead, via the mean absolute gap between every pair of repeated answers. No external ground truth is consulted anywhere in this benchmark — the correctness proxy is self-agreement, not verified outcomes.

[@tbl:calibration] reports the aggregate scores over the run, and [@fig:calibration] plots the reliability curve per confidence bucket.

| Metric | Value |
|--------|-------|
| Expected calibration error (choice, proxy) | {{BENCH_CALIB_ECE}} |
| Brier score (choice, proxy) | {{BENCH_CALIB_BRIER}} |
| Mean pairwise noul gap | {{BENCH_CALIB_MEAN_GAP}} |

: Calibration summary over {{BENCH_CALIB_STATES}} states × {{BENCH_CALIB_REPEATS}} repeats recorded by `benchmarks/bench_calibration.py` against the {{BENCH_CALIB_MODEL}} model on {{BENCH_CALIB_DATE}}. Choice correctness is a self-consistency proxy — agreement with the modal choice across repeats — not accuracy against ground truth; the mean pairwise noul gap measures repeat-to-repeat answer stability rather than correctness. Values are injected from the benchmark JSON at render time. {#tbl:calibration}

![Reliability diagram of choice-answer confidence under the self-consistency proxy, measured by `benchmarks/bench_calibration.py` over {{BENCH_CALIB_STATES}} states × {{BENCH_CALIB_REPEATS}} repeats against the {{BENCH_CALIB_MODEL}} model on {{BENCH_CALIB_DATE}}. Each point is a confidence bucket plotting mean reported confidence against proxy accuracy, where proxy accuracy is agreement with the modal choice across repeats of the same state; the dashed diagonal marks perfect agreement between stated confidence and observed proxy accuracy. Because the proxy scores self-agreement rather than verified correctness, proximity to the diagonal indicates consistency between stated confidence and repeat-stable behaviour — not truthfulness about the world. Aggregate scores are tabulated in [@tbl:calibration].](../output/figures/calibration_reliability.png){#fig:calibration width=85%}

The expected calibration error of {{BENCH_CALIB_ECE}} and the Brier score of {{BENCH_CALIB_BRIER}} describe reported choice confidence against modal self-agreement labels. The mean pairwise noul gap of {{BENCH_CALIB_MEAN_GAP}} describes repeat-to-repeat answer variation on the same states. These observations are limited to the retained workload and its self-consistency proxy. They do not establish probability calibration against independent ground truth, confidence ordering or internal coherence, and they do not determine a necessary or sufficient condition for deploying decision gates.

## Interpretation of the historical receipts

The retained observations support narrower conclusions. Batching reduced wall time and total-token use for this workload and requested model alias; paired answer equivalence and USD savings remain unmeasured. Pattern latency includes transport and composition together, so composition overhead cannot be isolated. Reported confidence and noul stability describe repeated self-agreement under the stated proxy, which can coexist with incorrect decisions. Ground-truth calibration, cross-model transfer and production routing quality require independent labeled evaluation.

## Completed CPU comparator studies

The selected offline comparison comprises {{STUDY_CPU_JOBS}} serial jobs with {{STUDY_CPU_PLANNED}} planned cells: {{STUDY_CPU_COMPLETED}} completed and {{STUDY_CPU_UNSUPPORTED}} unsupported. It retains {{STUDY_CPU_QUALITY}} completed quality cells separately from other cell roles. Fixed training-frequency references, TF-IDF logistic regression and histogram gradient boosting provide reproducible comparators. Unsupported text/numeric task combinations remain visible; these jobs made no model-provider HTTP requests. Absence of API billing does not quantify local compute expense.

On the canonical final-train test views, fixed TF-IDF logistic regression achieves {{STUDY_BANK_ACCURACY_PCT}}% accuracy on BANKING77 and {{STUDY_CLINC_ACCURACY_PCT}}% on CLINC150/OOS. These are supervised comparator results, not measurements of Jev, Kev, Jeff or a hosted chat model. Official tests had prior exposure in the research workflow; fixed settings and retained provenance make the evaluation auditable but do not create a new untouched holdout. CLINC aggregate accuracy is accompanied by a separate OOS detection audit; good overall intent classification does not establish reliable rejection of unseen intents.

![Canonical official-test accuracy of the applicable fixed CPU comparators after final train-plus-validation refitting, with retained grouped percentile intervals. Points and interval whiskers compare training-frequency references with the configured text classifier or numeric classifier; inapplicable task/backend pairs remain unsupported in the report. Intervals describe fixed evaluated predictions, not refitting uncertainty. Different datasets have different vocabularies and class distributions; their accuracies are not a common difficulty scale.](../output/figures/cpu_quality.png){#fig:cpu_quality width=90%}

On Wine, the numeric comparator's raw bin-index MAE is {{STUDY_WINE_MAE}}, compared with {{STUDY_WINE_PRIOR_MAE}} for the training-frequency reference. Classification accuracy and scalar error need not rank these models identically: an argmax can favor a common category while its probability-weighted score is farther from the target index. The bins change the original grade target; these errors cannot be compared directly with published errors on the original grade scale [@cortez2009wine].

![Wine scalar MAE and RMSE in declared bin-index units for the canonical final-train numeric comparator and training-frequency reference. The MAE interval uses the retained grouped resamples; RMSE is a descriptive point estimate. Classification accuracy uses genuine probability argmax and answers a different question. The lowest bin has no source observations, while the highest bin is sparse; full-vocabulary macro F1 retains absent classes, and these observations do not establish extreme-grade performance.](../output/figures/wine_ordinal.png){#fig:wine_ordinal width=90%}

## Cohort sensitivity and training-fold validation

The leakage-clean sensitivity removes view-specific input-group overlaps and conflicting labels before a separate fit. It changes both the fitted data and, where exclusions apply, the evaluated cohort. Canonical and cleaned metrics therefore describe distinct treatments. Their differences do not isolate a causal effect of leakage, and separate confidence intervals are not a paired test of that effect. The canonical benchmark remains available as published; the sensitivity makes the exclusion convention inspectable.

![Canonical versus separately refitted leakage-clean accuracy and Brier loss for applicable CPU comparators, with evaluated group or row counts and descriptive metric differences disclosed. Cleaning can change training examples and test membership, so the contrast is a cohort-and-refit sensitivity rather than a paired causal comparison. Brier losses use the declared full-vocabulary convention and the same probability meanings within each comparator; lower values do not establish calibrated posteriors.](../output/figures/cohort_sensitivity.png){#fig:cohort_sensitivity width=95%}

BANKING77 training-fold rotations evaluate every original training example once as validation, while keeping the official test outside those selection jobs. The pooled out-of-fold interval resamples retained input groups with predictions fixed. Shared training examples across folds make model errors dependent; the interval excludes the variability of rerunning the fitting procedure [@bengio2004variance]. Neither the fold plot nor pooled interval is evidence for transferring a validation-selected gate to the later final refit.

![BANKING77 training-fold validation accuracy for the fixed classifier and training-frequency reference, with the pooled out-of-fold point estimate and its retained grouped percentile interval shown separately. Each original training row contributes a validation prediction once; fitted models have overlapping training sets. The interval concerns fixed pooled predictions and does not account for correlated training/refit uncertainty or establish a universal cross-validation variance estimate.](../output/figures/validation_folds.png){#fig:validation_folds width=95%}

Validation gates expose a further quality/coverage tradeoff. A stricter accepted subset can have lower observed error but less coverage; a policy selecting no eligible groups has zero acceptance and unavailable risk. The plotted Wilson bounds belong to recorded validation candidate selection. Adaptive threshold scanning and limited group counts prevent interpreting them as simultaneous deployment guarantees [@geifman2017selective]. No temperature scaling or other post-hoc probability recalibration is claimed by these gate results.

![Recorded validation gate coverage, observed accepted-group risk and Wilson upper bound for the fixed selection models. Group correctness requires all accepted decisions in the group to be correct. A gate with no eligible threshold is displayed as zero coverage with unavailable risk and bound, not perfect performance. Thresholds were selected adaptively on validation data; these bounds are descriptive and do not carry a simultaneous risk guarantee or transfer to final refits.](../output/figures/selective_validation.png){#fig:selective_validation width=95%}

## Partial native execution and a halted hosted probe

The selected later native sensitivity study retains {{STUDY_NATIVE_COMPLETED}} completed cells, alongside unsupported, failed, unresolved and future unattempted work. Its compact cohort and source differ from the full CPU comparison. Resource interruptions, inherited wall allowances and unknown operational windows prevented full execution. Completed native predictions remain descriptive evidence for their actual questions and settings; they do not establish completion of the proposed full matrix or support pooling different model cohorts into an unqualified ranking.

The frozen hosted pilot has {{STUDY_HOSTED_PLANNED}} planned cells and made {{STUDY_HOSTED_ATTEMPTS}} actual HTTP attempt. It retains {{STUDY_HOSTED_FAILED}} failed, {{STUDY_HOSTED_UNSUPPORTED}} unsupported and {{STUDY_HOSTED_UNATTEMPTED}} unattempted cells. The native Decisions capability probe returned a not-found response, with no resolved model/provider, usable prediction, tokens or charge available. No hosted quality, warm-repeat or graphical experiment ran. A separately observed public metadata response is not a successful decision request and does not identify the original failure cause.

The shared hosted allocation is USD {{STUDY_HOSTED_LIMIT_USD}}; {{STUDY_HOSTED_UNRESOLVED_BILLING}} unknown-billing attempt stops further admission. Reported and reserved zero totals are bookkeeping observations, not proof of zero actual charge. The frozen pilot uses a serialized hosted request treatment; a higher general concurrency default would be a different latency/throughput experiment.

![Planned execution-status coverage for the selected completed CPU studies, partial native sensitivity study and halted hosted pilot. Completed, unsupported, failed, unresolved and unattempted cells retain their distinct meanings and full denominators. A started cell without a terminal outcome is unresolved. The panels bind different cohorts and source identities and compare execution coverage, not model accuracy or economic efficiency; the hatched full-hosted proposal remains unexecuted.](../output/figures/execution_coverage.png){#fig:execution_coverage width=95%}

The empirical contribution is consequently bounded: reproducible CPU references, retained historical API observations and inspectable failures of broader execution. The new plots make probability interpretation, cohort changes, selection limits and missing execution visible. Successful software verification supports the implementation contract; it cannot fill an absent model-quality or billing observation.
