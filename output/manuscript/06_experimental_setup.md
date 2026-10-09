# Experimental Setup: Historical Receipts, Environment, and Data Provenance {#sec:experimental_setup}

The results in [@sec:results] combine separately selected historical API receipts, CPU studies and partial execution reports. This section distinguishes their protocols, data roles and identities from the current software/render environment. Reproduction preserves intent and provenance; it does not promise identical responses from a changing remote service.

## Software and documentation identities

The current package/render edition is daf-jev 0.7.2, generated under 3.10.20 on `macOS-27.0.1-arm64-arm-64bit`. Those values describe variable generation, not the historical benchmark execution environment. The old receipts lack a complete source, Python, hardware and dependency identity; those historical fields remain unknown. The package targets Python 3.10 or newer. Core runtime dependencies are `httpx` and `pyyaml`, with `tomli` on Python 3.10 and standard-library `tomllib` on newer Python. Optional supervised benchmarking uses scikit-learn and figure generation uses matplotlib/Pillow.

The model-level documentation claims in [@sec:jev_model] are grounded in a retained hash-manifested TypeSafe snapshot (708902db9820d9d8, 111 pages). That identifies source documentation bytes, not the model's weights or current hosted behavior.

## Historical benchmark configuration

The batching receipt compares one batched call with sequential single-question calls over a fixed synthetic paragraph and a mixed noul/choice/score question set. The retained widths are 5, 10 and 20. It records timings and token totals; answer equivalence and monetary savings were not independently measured.

The pattern receipt runs composite scoring and intent routing 6 times and records end-to-end wall time plus usage. It includes both network and composition work, without a separate overhead baseline. The calibration receipt runs 6 inline states 5 times against jev-latest, using modal self-agreement as its correctness proxy and pairwise noul gaps as stability. None of these inline states forms an independent ground-truth test corpus.

The command scripts expose their protocol through explicit arguments. `manuscript/config.yaml` records manuscript experiment settings; a render setting is not proof that a historical script consumed it. Actual run counts and settings must come from the selected receipt, with discrepancies rejected or explained. Legacy scripts resolve a key through their documented environment/.env chain and skip without a key; they are outside the offline test suite.

## Measurement and evidence selection

Historical wall times include transport, parsing and composition; retries and network conditions can influence them. They are observations, not conservative guarantees for future application latency. Token totals are response usage, not dollar charges. Where an old receipt does not declare its percentile estimator, the current nearest-rank helper cannot retroactively determine it.

The selected result files and their hashes bind prose and figures to one reviewed evidence set. The reproducible build timestamp is 2026-10-09T20:37:04Z; this pinned timestamp is neither the actual render time nor a benchmark execution date. Independently choosing the newest file for each benchmark cannot establish a common model/date/environment. Retained receipts remain unchanged when new experiments run.

## Dataset views and evaluation roles

The new run format records exact prepared dataset bytes, source/config hashes, explicit model profiles, probability/confidence provenance, seed, cell order, limits and every attempted request. Train fits baselines; validation selects policy thresholds; test evaluates the frozen decision rule. Prior test exposure remains disclosed and is not undone by this role assignment. Repeated timing cells retain their leakage group and are separated from initial quality cells. Hosted spend is admitted against a sourced conservative liability, then reconciled with reported charges; unknown cost remains unresolved. Local monetary expense requires additional rate/hardware measurement.

The detailed executable protocol is `docs/decision_benchmarking.md`. It supports synthetic controls and pinned BANKING77, CLINC150/OOS and Wine preparation. Catalog discovery is not hosted inference, adapter tests are not local weight execution, and offline policy replay is not executed end-to-end latency. The selected reports establish only the executions they retain; historical measurements do not establish acceptance of a later lane.

A later frozen Mac study exposed an expanded per-dataset timing selection instead of the requested globally bounded shared cohort. Execution stopped at a clean boundary; completed observations and future unattempted denominators remain in their original experimental identity. Corrected sampling and ordered prompt controls require a new prospective source/cohort and fresh input proofs. The declared task mixture must follow the protocol before predictions, rather than observed test accuracy or model success. Prior preparation, execution and teardown still consume the same cumulative profile allowance.

Probability origin, numerical validity, meaning and calibration are distinct evidence. Native compatibility scores, discriminative class estimates, training frequencies and analytical conditional beliefs must retain their own interpretations; unknown meaning stays unknown. Proper scores describe the supplied rows against the stated target, without establishing calibrated posteriors or empirical CPTs. Earlier synthetic variants are not matched causal permutations, and sorted chat presentation with rotated schema enums does not measure prompt-position sensitivity.

The real tasks come from primary public datasets. BANKING77 supplies fine-grained banking intents [@casanueva2020intent]; CLINC supplies intent classification with explicit out-of-scope examples [@larson2019oos]. Their official test splits are retained. Wine combines red and white physicochemical observations with an explicit wine-type feature [@cortez2009wine]. The benchmark projects original quality grades into ordered bins and reports the source-grade distribution and information loss separately. This projection is a new evaluation target, not a reproduction of the original paper's regression results.

Frozen fold packs bind complete original row inventories, grouping, assignments, algorithm, seed and preparation dependencies. Selection views omit the designated test split. Final-train views refit using the non-test training and validation data, retain test scoring, and contain no validation pool for transferring a policy fitted earlier. The protocol provides BANK training-fold rotations for fixed published HTTP models or fitted comparators on declared validation IDs; the selected completed rotations are CPU comparator jobs. An HTTP model is not retrained merely because its inputs carry fold metadata.

Canonical and leakage-clean views remain distinct. Input-group overlap and conflicting-label exclusion are view-specific, applied before a new fit when evaluating a fitted comparator. The exclusion rule can use labels; it is disclosed as a sensitivity analysis rather than a label-blind sampling procedure. It addresses overlap within these prepared splits, not possible overlap with a pretrained model's undisclosed training corpus.

## Synthetic controls and the sampling unit

Seeded synthetic tasks cover binary rules, categorical decisions, ordinal rubrics and analytical Bayes questions. Their state fields and generating rules define known labels or soft targets. Distractor, negation and context-length variants stress the parser/model contract, but an unmatched variant collection is not a causal experiment on those factors. Binary base-task prevalence follows its independent generating conditions rather than forced class balance.

Matched cyclic Choice controls keep state, instructions, semantic options, truth, split and input group fixed while rotating option order. Complete groups remain together, and the loader validates actual semantic and order hashes. They are quality controls and do not inflate the timing cohort. For chat, prompt order and schema enumeration vary jointly under the declared serializer; this treatment cannot isolate either mechanism alone. Earlier sorted chat prompts and earlier inert rotation metadata are preserved as limitations of their original studies.

The global timing pack selects ordinary test input groups deterministically from the ordered supplied pools, balancing declared task/dataset participation without reading targets. This target-free statement applies to the timing selector only. Upstream pilot pools were class- or grade-stratified using labels, so the entire pipeline is not outcome-blind. One physical example represents each selected ordinary group; repeated timing observations keep the same complete state and question vocabulary. Full-group matched controls and validation probes have separate identities and denominators.

## Timing, resource and economic treatments

Quality passes precede warm-repeat passes. A new serializer, probability contract or cohort requires a fresh primary under the new source; earlier primaries cannot serve as identical-input repetitions. Frozen cyclic profile schedules distribute repeat positions, but small repetition counts and sequential serving do not eliminate thermal, network or background-load effects. Reported request latency, SDK resource windows, startup/load time, owned cleanup time and whole-profile cumulative allowance are separately scoped.

The prospective native comparison recipe freezes Jev and Perplexity decision profiles, the same prepared inputs and timing sample pack, and seeded interleaving within one hosted schedule. Perplexity's primary documentation supplies separate interface and request limits [@perplexity2026decisions]; those declarations require actual endpoint probes. The earlier Jev-only run remains a separate exploratory execution. Model and protocol selection precedes inspection of completed test-quality results. Both arms share the existing total allowance; a prepared recipe, offline plan or successful capability fixture does not establish completion of the joint study or a physically immutable hosted checkpoint.

Local execution admits only a verified owned runtime and complete input within a frozen operational bound. A conservative complete-prompt upper bound is labeled differently from an exact tokenizer count. An operational hardware bound is not the model's advertised context limit. Sampled process RSS and an OS physical-footprint observation are different resource measures; neither establishes continuous Metal memory peaks. Primary-only diagnostic observers can affect latency, and no unmeasured correction is subtracted.

A hosted plan freezes endpoint, requested model, provider preferences, schema, token limits, tariffs, budget and concurrency before predictions. Probes, failures and retries consume the same allocation as quality calls. Paid native admission cannot use one catalog context length as an unverified aggregate billable-input ceiling; zero-priced catalog candidates still require response and billing reconciliation. A failed capability probe is retained without endpoint substitution or a new budget ledger. These restrictions can leave a large part of a frozen study unattempted, as the selected coverage figure shows.

The native Jev contract binds the documented state-plus-questions input window and input-only tariff [@openrouter2026jev]. TypeSafe routing, the endpoint declaration and the price ceiling are frozen with the manifest. The resulting per-attempt reservation is a conditional maximum exposure, rather than an observed bill or a guarantee that the provider enforces every declaration. Every retry requires a new reservation. A reported token or charge breach stops admission. Native capability probes establish only the fixtures actually retained; their success does not validate the declared maximum context.

The prospective expansion freezes complete validation and official-test obligations separately from the retained failed pilot. Figure [@fig:hosted_admission] distinguishes static task incompatibility, unavailable liability bounds and tariff-admissible candidates whose execution remains unverified. Its declaration of a large cohort does not establish completed samples, quality or an expected bill. This historical matrix predates the implemented Jev input contract and the reviewed bounded continuation. It remains a record of the earlier declaration, rather than the current executable cohort. The new native-only study uses the same shared allocation, pins TypeSafe routing and accounts for the held historical uncertainty separately from reported charges. A new run's empty ledger cannot replace a shared accounting import.

\begin{landscape}
\begin{figure}[p]
\centering
\includegraphics[width=\linewidth]{../output/reports/hosted-expansion-20261008/admission-matrix.pdf}
\caption{Prospective hosted admission matrix. Categories concern frozen task and accounting contracts, not observed model quality or endpoint acceptance. At this earlier source identity, the prior unresolved charge blocked new requests. Later Jev admission and validation probes are separately selected; this matrix retains its original plan and figure-source hashes.}
\label{fig:hosted_admission}
\end{figure}
\end{landscape}
