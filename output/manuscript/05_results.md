# Results: Historical Measurements, CPU Comparators, and Execution Coverage {#sec:results}

This section separates historical native API measurements from later CPU comparator studies, partial local-model execution, an earlier failed hosted probe and new native hosted capability evidence. The historical batching benchmark implements the documented parallel-questions pattern [@typesafe2026patterns], alongside decision-pattern latency and self-consistency measurements. These historical receipts identify their requested model aliases, rather than a pinned weight identity. Every value below is injected from the explicitly selected benchmark outputs at render time; figures must use that same evidence selection. The batching and latency results reported here were recorded on 2026-09-16; the calibration results on 2026-09-16.

## Historical batching speedup and total-token use

The batching benchmark compares two strategies over the same state and question mix: one call carrying all questions in a batch, versus one sequential single-question call per question, repeated for each configured batch width over multiple measured runs. The retained historical receipts measure wall time and token usage. They do not retain paired answers, so they do not establish that batching left the decisions unchanged. The sequential strategy re-sends the state once per question, while batching shares a round trip and state transmission.

[@fig:batching] shows the measured speedup per batch width and the total-token ratio in separate panels.

![Batching speedup of the jev-latest model versus sequential single-question calls, measured by `benchmarks/bench_batching.py` on 2026-09-16 against the live API. Bars give the wall-time speedup of one batched call over one sequential call per question for each configured batch width (5, 10, and 20 questions per batch, tabulated in [@tbl:batching]); a separate panel shows the total-token ratio, sequential tokens divided by batched tokens. The sequential strategy re-sends the state paragraph once per question. Each bar is annotated with its measured value, and the rendered title carries the model identifier and run date read from the benchmark JSON itself. The takeaway: the speedup grows with batch width as the fixed per-call overhead amortizes, while the batched strategy uses fewer total tokens in this recorded workload.](../output/figures/batching_speedup.png){#fig:batching width=85%}

[@tbl:batching] tabulates the measured speedups. The speedup grows with batch width, as expected from the round-trip accounting: the fixed per-call overhead is amortized over more questions, and the state is transmitted once rather than once per question.

| Questions per batch | Wall-time speedup vs sequential |
|---------------------|---------------------------------|
| 5 | 3.98 |
| 10 | 8.77 |
| 20 | 18.55 |

: Wall-time speedup of one batched call versus one sequential call per question, per configured batch width, recorded by `benchmarks/bench_batching.py` against the jev-latest model on 2026-09-16. Values are injected from the benchmark JSON at render time. {#tbl:batching}

Recorded total-token use moves in the same direction. The recorded `token_cost_ratio` expresses the sequential strategy's token consumption relative to the batched strategy's: at the widest configured batch width the sequential strategy consumes 4.22 times the tokens of the batched call. This ratio measures total tokens, not reported USD. Input/output prices, provider surcharges and retries can differ; these historical receipts do not establish monetary savings.

## Historical decision-pipeline latency

The second benchmark measures end-to-end latency of two composition pipelines — the network call plus the local composition logic, exactly as an application would run them:

- **composite_score** — one `score` call, then `composite_score` over the answer, then a `confidence_gate` verdict;
- **intent_routing** — one `choice` call, then `route()` dispatching to a trivial handler.

Each pipeline is executed 6 times; [@tbl:latency] reports the median (p50) and tail (p95) wall times per pipeline, and [@fig:latency] plots them side by side.

![Median (p50) and tail (p95) end-to-end wall time per decision pipeline, measured by `benchmarks/bench_patterns.py` over 6 runs against the jev-latest model on 2026-09-16. Each pipeline group — composite scoring (one `score` call, then `composite_score` and a `confidence_gate` verdict) and intent routing (one `choice` call, then `route()` dispatch) — shows paired p50/p95 bars covering the full network round trip plus the local composition logic; values are tabulated in [@tbl:latency] and read from the benchmark JSON fields at figure-generation time. The bars describe these observed sessions. No isolated transport or composition baseline was recorded, so the figure does not estimate composition overhead or establish a service-level latency guarantee.](../output/figures/latency_percentiles.png){#fig:latency width=85%}

| Pipeline | Median wall time, p50 (s) | Tail wall time, p95 (s) |
|--------------------|---------------------------|-------------------------|
| composite_score | 0.133 | 0.242 |
| intent_routing | 0.129 | 0.152 |

: End-to-end wall time (network round trip plus local composition logic) per decision pipeline, median and tail over 6 runs recorded by `benchmarks/bench_patterns.py` against the jev-latest model on 2026-09-16. Values are injected from the benchmark JSON at render time. {#tbl:latency}

## Historical proxy-agreement and repeat stability

The third historical benchmark compares reported confidence with repeat agreement, rather than measuring decision correctness against an independent label. `benchmarks/bench_calibration.py` runs 6 short states 5 times each against the jev-latest model and scores choice answers under a *self-consistency proxy*: a sample counts as correct when it agrees with the modal choice across the repeats of the same state. Because a yes/no probability carries no per-sample label to agree with, noul answers are scored for repeat-to-repeat stability instead, via the mean absolute gap between every pair of repeated answers. No external ground truth is consulted anywhere in this benchmark — the correctness proxy is self-agreement, not verified outcomes.

[@tbl:calibration] reports the aggregate scores over the run, and [@fig:calibration] plots the reliability curve per confidence bucket.

| Metric | Value |
|--------|-------|
| Expected calibration error (choice, proxy) | 0.0730 |
| Brier score (choice, proxy) | 0.0252 |
| Mean pairwise noul gap | 0.0050 |

: Calibration summary over 6 states × 5 repeats recorded by `benchmarks/bench_calibration.py` against the jev-latest model on 2026-09-16. Choice correctness is a self-consistency proxy — agreement with the modal choice across repeats — not accuracy against ground truth; the mean pairwise noul gap measures repeat-to-repeat answer stability rather than correctness. Values are injected from the benchmark JSON at render time. {#tbl:calibration}

![Reliability diagram of choice-answer confidence under the self-consistency proxy, measured by `benchmarks/bench_calibration.py` over 6 states × 5 repeats against the jev-latest model on 2026-09-16. Each point is a confidence bucket plotting mean reported confidence against proxy accuracy, where proxy accuracy is agreement with the modal choice across repeats of the same state; the dashed diagonal marks perfect agreement between stated confidence and observed proxy accuracy. Because the proxy scores self-agreement rather than verified correctness, proximity to the diagonal indicates consistency between stated confidence and repeat-stable behaviour — not truthfulness about the world. Aggregate scores are tabulated in [@tbl:calibration].](../output/figures/calibration_reliability.png){#fig:calibration width=85%}

The expected calibration error of 0.0730 and the Brier score of 0.0252 describe reported choice confidence against modal self-agreement labels. The mean pairwise noul gap of 0.0050 describes repeat-to-repeat answer variation on the same states. These observations are limited to the retained workload and its self-consistency proxy. They do not establish probability calibration against independent ground truth, confidence ordering or internal coherence, and they do not determine a necessary or sufficient condition for deploying decision gates.

## Interpretation of the historical receipts

The retained observations support narrower conclusions. Batching reduced wall time and total-token use for this workload and requested model alias; paired answer equivalence and USD savings remain unmeasured. Pattern latency includes transport and composition together, so composition overhead cannot be isolated. Reported confidence and noul stability describe repeated self-agreement under the stated proxy, which can coexist with incorrect decisions. Ground-truth calibration, cross-model transfer and production routing quality require independent labeled evaluation.

## Completed CPU comparator studies

The selected offline comparison comprises 9 serial jobs with 93046 planned cells: 68894 completed and 24152 unsupported. It retains 68870 completed quality cells separately from other cell roles. Fixed training-frequency references, TF-IDF logistic regression and histogram gradient boosting provide reproducible comparators. Unsupported text/numeric task combinations remain visible; these jobs made no model-provider HTTP requests. Absence of API billing does not quantify local compute expense.

On the canonical final-train test views, fixed TF-IDF logistic regression achieves 87.69% accuracy on BANKING77 and 79.84% on CLINC150/OOS. These are supervised comparator results, not measurements of Jev, Kev, Jeff or a hosted chat model. Official tests had prior exposure in the research workflow; fixed settings and retained provenance make the evaluation auditable but do not create a new untouched holdout. CLINC aggregate accuracy is accompanied by a separate OOS detection audit; good overall intent classification does not establish reliable rejection of unseen intents.

![Canonical official-test accuracy of the applicable fixed CPU comparators after final train-plus-validation refitting, with retained grouped percentile intervals. Points and interval whiskers compare training-frequency references with the configured text classifier or numeric classifier; inapplicable task/backend pairs remain unsupported in the report. Intervals describe fixed evaluated predictions, not refitting uncertainty. Different datasets have different vocabularies and class distributions; their accuracies are not a common difficulty scale.](../output/figures/cpu_quality.png){#fig:cpu_quality width=90%}

On Wine, the numeric comparator's raw bin-index MAE is 0.2770, compared with 0.3319 for the training-frequency reference. Classification accuracy and scalar error need not rank these models identically: an argmax can favor a common category while its probability-weighted score is farther from the target index. The bins change the original grade target; these errors cannot be compared directly with published errors on the original grade scale [@cortez2009wine].

![Wine scalar MAE and RMSE in declared bin-index units for the canonical final-train numeric comparator and training-frequency reference. The MAE interval uses the retained grouped resamples; RMSE is a descriptive point estimate. Classification accuracy uses genuine probability argmax and answers a different question. The lowest bin has no source observations, while the highest bin is sparse; full-vocabulary macro F1 retains absent classes, and these observations do not establish extreme-grade performance.](../output/figures/wine_ordinal.png){#fig:wine_ordinal width=90%}

## Cohort sensitivity and training-fold validation

The leakage-clean sensitivity removes view-specific input-group overlaps and conflicting labels before a separate fit. It changes both the fitted data and, where exclusions apply, the evaluated cohort. Canonical and cleaned metrics therefore describe distinct treatments. Their differences do not isolate a causal effect of leakage, and separate confidence intervals are not a paired test of that effect. The canonical benchmark remains available as published; the sensitivity makes the exclusion convention inspectable.

![Canonical versus separately refitted leakage-clean accuracy and Brier loss for applicable CPU comparators, with evaluated group or row counts and descriptive metric differences disclosed. Cleaning can change training examples and test membership, so the contrast is a cohort-and-refit sensitivity rather than a paired causal comparison. Brier losses use the declared full-vocabulary convention and the same probability meanings within each comparator; lower values do not establish calibrated posteriors.](../output/figures/cohort_sensitivity.png){#fig:cohort_sensitivity width=95%}

BANKING77 training-fold rotations evaluate every original training example once as validation, while keeping the official test outside those selection jobs. The pooled out-of-fold interval resamples retained input groups with predictions fixed. Shared training examples across folds make model errors dependent; the interval excludes the variability of rerunning the fitting procedure [@bengio2004variance]. Neither the fold plot nor pooled interval is evidence for transferring a validation-selected gate to the later final refit.

![BANKING77 training-fold validation accuracy for the fixed classifier and training-frequency reference, with the pooled out-of-fold point estimate and its retained grouped percentile interval shown separately. Each original training row contributes a validation prediction once; fitted models have overlapping training sets. The interval concerns fixed pooled predictions and does not account for correlated training/refit uncertainty or establish a universal cross-validation variance estimate.](../output/figures/validation_folds.png){#fig:validation_folds width=95%}

Validation gates expose a further quality/coverage tradeoff. A stricter accepted subset can have lower observed error but less coverage; a policy selecting no eligible groups has zero acceptance and unavailable risk. The plotted Wilson bounds belong to recorded validation candidate selection. Adaptive threshold scanning and limited group counts prevent interpreting them as simultaneous deployment guarantees [@geifman2017selective]. No temperature scaling or other post-hoc probability recalibration is claimed by these gate results.

![Recorded validation gate coverage, observed accepted-group risk and Wilson upper bound for the fixed selection models. Group correctness requires all accepted decisions in the group to be correct. A gate with no eligible threshold is displayed as zero coverage with unavailable risk and bound, not perfect performance. Thresholds were selected adaptively on validation data; these bounds are descriptive and do not carry a simultaneous risk guarantee or transfer to final refits.](../output/figures/selective_validation.png){#fig:selective_validation width=95%}

## Partial local execution and historical hosted failure

The selected later native sensitivity study retains 2005 completed cells, alongside unsupported, failed, unresolved and future unattempted work. Its compact cohort and source differ from the full CPU comparison. Resource interruptions, inherited wall allowances and unknown operational windows prevented full execution. Completed native predictions remain descriptive evidence for their actual questions and settings; they do not establish completion of the proposed full matrix or support pooling different model cohorts into an unqualified ranking.

The earlier frozen hosted pilot has 18065 planned cells and made 1 actual HTTP attempt. It retains 1 failed, 19 unsupported and 18045 unattempted cells. The native Decisions capability probe returned a not-found response, with no resolved model/provider, usable prediction, tokens or charge available. No hosted quality, warm-repeat or graphical experiment ran. A separately observed public metadata response is not a successful decision request and does not identify the original failure cause.

The shared hosted allocation is USD 25. At that historical cut, 1 unknown-billing attempt stopped further admission. A later, independently reviewed exact-request tariff bound permits continuation while retaining the original UNKNOWN and the unchanged allowance. It does not supply a measured charge for the missing receipt. The earlier pilot used a serialized hosted request treatment; its timings do not describe the new concurrency treatment.

![Planned execution-status coverage for the selected completed CPU studies, partial native sensitivity study and halted hosted pilot. Completed, unsupported, failed, unresolved and unattempted cells retain their distinct meanings and full denominators. A started cell without a terminal outcome is unresolved. The panels bind different cohorts and source identities and compare execution coverage, not model accuracy or economic efficiency; the hatched historical full-hosted proposal remains unexecuted at its selected cut.](../output/figures/execution_coverage.png){#fig:execution_coverage width=95%}

## Native hosted capability evidence

The independently selected Jev study freezes 25077 cells across real datasets, synthetic controls and graphical tasks. Its selected capability phase records 12 successful probes and 12 physical requests, with USD 0.000556920 reported billing. Requests resolve to the pinned TypeSafe Jev revision through the documented Decisions endpoint. The full BANKING77 and CLINC option sets, the ordinal Wine task, and synthetic native primitives are exercised without changing vocabulary or substituting a generative model.

Each row in Figure [@fig:native_capabilities] represents an actual selected validation fixture. Repeated BANKING77 rows belong to distinct declared validation folds. These probes demonstrate that the particular complete requests succeeded; they do not measure a maximum option or context limit, classify the full official test sets, or establish a quality ranking. The selected cut retains 25065 future cells and no primary quality or warm-repeat result. Later work must select its own immutable terminal evidence before entering this manuscript.

![Native Jev capability probes at the selected terminal phase. Complete requested option sets, individual HTTP latency and provider-reported charges describe actual validation fixtures. Success does not establish model accuracy or maximum supported vocabulary/context boundaries. Separate validation folds retain their identities.](../output/figures/native_capabilities.png){#fig:native_capabilities width=95%}

The empirical contribution is consequently bounded: reproducible CPU references, retained historical API observations, inspectable failures of broader execution and successful native hosted validation probes. The new plots make probability interpretation, cohort changes, selection limits and missing execution visible. Successful software verification supports the implementation contract; it cannot fill an absent model-quality or billing observation.
