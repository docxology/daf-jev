# Full decision-model study

The full study separates software verification, model admission, validation
selection, official test scoring and publication. A frozen plan records the
entire requested matrix even when resources, unsupported capabilities or
credentials prevent execution. Read completed, failed, unsupported, unresolved
and unattempted counts together. A complete CPU baseline does not establish
local language-model or hosted acceptance.

Use the [benchmark commands](decision_benchmarking.md), [dataset contracts](datasets.md),
[backend semantics](providers.md) and [local serving recipes](local_serving.md).
Retain old manifests and observations. New software or dataset views receive a
new run; they do not replace historical measurements.

## Recorded results on 2026-10-08

The [selected CPU comparison](../output/reports/full-offline-20261008/full-offline-comparison.md)
and its [JSON](../output/reports/full-offline-20261008/full-offline-comparison.json)
and [standalone PDF](../output/reports/full-offline-20261008/full-offline-comparison-reviewed.pdf)
cover nine completed serial jobs: five BANKING validation rotations, CLINC/Wine
validation, canonical final refits, separately fitted leakage-clean refits and
synthetic mechanism checks. Their 93,046 planned cells comprise 68,894 completed
and 24,152 unsupported comparator/task cells, with no failed or unresolved cells
and no HTTP attempts. All nine reports were independently regenerated from
retained observations with identical JSON bytes.

The fixed text classifier scored 87.69% on BANKING77 and 79.84% on CLINC's full
151-way official test. Wine's structured classifier had bin-index scalar MAE
0.2770, compared with the prior's 0.3319; its probability-argmax bin accuracy was
75.31%, compared with 76.54% for the prior. The JSON retains grouped intervals,
full-vocabulary macro-F1, OOS detection, proper scores and denominators. These
results establish CPU comparator performance on the selected inputs. Prior test
exposure, overlap sensitivity and sparse extreme Wine bins remain disclosed.

The full native and hosted studies remain unfinished. Historical native
receipts retain their partial outcomes; new source and full-cohort proposals
cannot reuse those primaries. The hosted full proposal has 15 arms and 376,155
planned cells and remains unattempted. The separate pilot below made one failed
probe; its charge is unknown. The existing USD 25 allocation
does not guarantee completion, and paid native aggregate billing is still
unbounded. Model execution requires actual resource, capability, credential and
accounting admission; neither a frozen proposal nor a CPU result supplies that
evidence.

The newer [hosted expansion protocol](hosted_expansion.md) separately freezes
the refreshed catalog and complete quality cohorts. It preserves this pilot and
its accounting hold. Its larger planned sample size is a prospective obligation,
not a new result or a replacement for the earlier denominators.

The [study status ledger](../output/reports/full-offline-20261008/study-status-reviewed.json)
binds software checks, actual CPU denominators, historical partial native
outcomes, the stopped model-free preparation and unattempted proposals.
Complete raw observations and review receipts remain in the retained local
archive; the committed aggregate report is not a published raw-evidence bundle.

The [hosted proposal summary](../output/reports/full-offline-20261008/hosted-full-proposal-summary.json)
retains every arm's static compatibility counts and conditional reservation;
the [frozen cohort](../output/reports/full-offline-20261008/hosted-profile-cohort.json)
lists requested IDs, endpoints, catalog capabilities, pricing and sent settings.
For Qwen3.5 9B, the frozen bound is USD 0.02103808 per attempt: USD 527.55089408
for one attempt on each statically compatible non-graph cell, or USD
1,055.10178816 for two. These conservative liabilities are not expected bills;
lower reconciled charges can release reservations. Neither bound supplies a
new allocation. Runtime estimates for a complete native/hosted matrix remain
unavailable until compliant execution and lifecycle evidence are collected.

## First hosted pilot: failed probe and accounting hold

The [pilot report](../output/reports/hosted-pilot-20261008/summary.md),
[JSON aggregate](../output/reports/hosted-pilot-20261008/summary.json) and
[standalone PDF](../output/reports/hosted-pilot-20261008/summary-reviewed.pdf) select one
frozen five-arm manifest with 18,065 planned cells. The capability stage made
one actual request to `inception/mercury-decide:free` through the documented
Decisions endpoint on October 8 at 17:34:55 UTC. It returned HTTP 404 without a
reported charge, resolved model, provider or response ID. Its original response
body was not retained, so the failure cause remains unknown. Later public GET
observations are recorded separately and do not establish the POST failure cause.

The report retains zero completed, one failed, 19 unsupported and 18,045
unattempted cells. No quality, warm-repeat or graphical inference ran. The
ledger stops admission with one unreconciled billing attempt. Its zero reported
and reserved totals do not establish zero actual billing. All five pilot arms
share the original USD 25 allocation; a different model, endpoint or plan cannot
reset it or bypass the hold.

This first pilot used frozen hosted concurrency one for serial billing
reconciliation. The general concurrency-four default is a separate throughput
treatment. The owned process closed cleanly, but process closure does not resolve
billing or establish inference quality. Further hosted execution requires actual
billing evidence for this attempt and the unchanged source, input and admission
checks. The pilot-source software verification recorded 1,519 passing unit tests and
93.15% combined line and branch coverage; its two live tests were collected only.

To recompute the selected run locally without inference, choose a fresh output
directory and use the retained archive:

```bash
mkdir .benchmarks/hosted-probe-reproduction
uv run --frozen --no-sync daf-jev benchmark report \
  .benchmarks/runs/c6ea2516-bb81-4079-b3f9-c509718541e9 \
  --output .benchmarks/hosted-probe-reproduction/report.json \
  --markdown .benchmarks/hosted-probe-reproduction/report.md \
  --pdf .benchmarks/hosted-probe-reproduction/report.pdf
```

This emits the core run report. The reviewed aggregate above additionally binds
the child-closure receipt, separate public metadata investigation, historical
studies and proposed matrix. Retain those selected inputs too; the public
aggregate alone is insufficient to reconstruct the complete local archive.
Execution also binds the inference Git commit. A later commit requires a new
frozen run linked to the prior journal and the same allocation; it cannot erase
the unknown charge or create another USD 25 budget. Offline reporting of this
recorded run remains available after source changes.

## Selection and evaluation inputs

The split seed is `20261007`. Retain the pinned original source files and export
the fold inventory from a fresh preparation. Fold assignments depend on the
recorded algorithm and dependency versions; a seed alone cannot identify them.
The prepared dataset and fold-pack hashes identify the actual assignments.

For BANKING77, use all five grouped training folds for validation. Each original
training row appears in exactly one validation fold. The official test rows
are absent from these selection views. Keep all 77 options. For CLINC, use the
published train and validation partitions, all 151 labels, and a separate OOS
reduction. For Wine, freeze an outer test fold, a different validation fold and
three training folds; keep identical feature records together and retain wine
type, original grade and the five declared bins.

```bash
uv run daf-jev benchmark dataset prepare --kind banking77 --source .benchmarks/data/banking77 \
  --seed 20261007 --packed --output .benchmarks/data/banking77-source.json
uv run daf-jev benchmark dataset folds --source .benchmarks/data/banking77-source.json \
  --output .benchmarks/banking77.folds.json
uv run daf-jev benchmark dataset view --source .benchmarks/data/banking77-source.json \
  --view selection --validation-fold 0 --packed --output .benchmarks/banking77.fold-0.selection.json
```

Repeat the selection view for folds 1–4. Plan these with `sampling: all`,
`execution_selection: {phase: quality}` and the explicitly chosen backends.
Quality-only selection does not require test timing examples. Use unchanged,
fixed hyperparameters for the reference classifiers. Out-of-fold observations
are one prediction per training example; overlapping fits are not independent
replications. Bootstrap independent input groups, rather than five fold means.

The optional packed encoding shares ordered question definitions while retaining
the complete vocabulary, examples and native request bytes. Use the public
loader for both encodings and retain their file hashes; inspect expanded
canonical and order-sensitive digests before admitting a run.

After freezing selection, `--view final_train` merges only the original
non-test train/validation rows for a separately identified final classifier.
It retains test for scoring and has no validation partition for fitting a
policy. A gate fitted on the earlier model cannot silently become a calibrated
gate for the refitted classifier. Policy calibration and final-model prediction
therefore need distinct, explicitly justified evidence.

Canonical results retain official rows. `--cohort leakage_clean` creates a
separate fitting and scoring view that excludes its declared overlapping and
conflicting input groups before training. The existing report's
`leakage_filtered` sensitivity only filters observation rows from its original
fit; these are different experiments. Neither changes the official result.
Disclose prior benchmark/test exposure and known or unknown pretraining overlap.
An official held-out split does not prove that its examples are new to a model
or to the researcher.

## Executable model cohort

Freeze the exact local runtime, server revision, weights, tokenizer, license,
precision, quantization, prompt/schema, decoding settings and launch arguments.
Serve one local model at a time on loopback. Verify full option vocabularies and
context packets before loading it. Record startup separately and charge
preparation, load, residence, execution and owned cleanup to its cumulative
profile allowance. A fresh process or source revision does not reset that
allowance. An unclosed window remains unknown and blocks automatic resume.

Freeze the complete public OpenRouter catalog before evaluating the test set.
Keep routing/pricing variants separate; deduplicate only evidenced equivalent
aliases. Use the Decisions endpoint for new native adapters and an explicit
chat or letter adapter for exceptions. Record requested and resolved model,
provider, endpoint, response ID, usage and reported billing per attempt.
Discovery is not an authenticated capability test.

A native option limit below 77 or 151 makes the corresponding full intent task
unsupported. Preserve the original question; do not shorten it or route it to
a substitute model. A capability probe covers its retained fixture only. A
model needs evidence for the actual task contract before its quality cells are
admitted. Unsupported and failed selected timing IDs retain their denominators.

## Timing, costs and continuation

The primary timing treatment is 100 shared ordinary physical test examples
overall, selected without targets or backend-success filtering, plus five
additional repetitions. Matched option-order controls are quality-only. A full
study needs a fresh shared pack from its full prepared inputs; the compact
pilot's pack is a different cohort. Rotate local order across rounds and retain
all reload costs. Interleave hosted arms using the frozen seed. Keep cold
startup, warm request latency, stability and accuracy separate.

The initially authorized hosted allocation is USD 25 in total, including
probes, failures and retries. Replacement plans do not create additional
allocations. Only one independently admitted execution plan may consume that
allocation unless a reviewed shared ledger enforces the aggregate ceiling.
A fixed larger study can admit attempts progressively within this allocation:
settled reported charges release unused reservation. Exhausting the allocation
preserves the remaining cells as unattempted. A guarantee of complete execution
requires enough authorized funding for its declared worst-case liability;
expenditure beyond USD 25 requires a separately supplied budget. A configuration
value alone is not spending authorization.

Reserve bounded liability before every actual attempt and reconcile reported
cost afterward. Native tariff rates and one catalog context length do not
establish an aggregate token bound across questions/options. Such paid native
cells remain unavailable until a supported billing contract is established.
Zero-tariff and bounded chat candidates still need actual capability probes,
credentials and retained receipts. Unknown charges stop admission. Local wall
time and sampled memory are observations; local monetary expense remains
unknown without supplied rates.

Resume only demonstrably unattempted work in the original run. Retain canceled
and unresolved attempts. A continuation must bind old journals, input/model
identity, prior quality and cumulative clocks before scheduling fresh work.
Check disk and memory before preparation and model admission, and preserve
unfinished cells when limits are reached. Do not infer a time refund from an
absent process or an interrupted call.

## Reports and acceptance

For the next independently funded and admitted study, proposed precision targets
are a 95% interval half-width of at most 0.02 for intent accuracy, 0.05 for OOS
precision/recall, and 0.03 bin-index units for Wine scalar MAE. Freeze these
targets in that study's manifest before prediction; they were not preregistered
targets for the completed CPU runs. Evaluate achieved width with the declared
grouped resampling. Small or absent classes, input dependence and uncertainty
from fitting can prevent a target from being met. Keep an unmet target explicit;
do not increase the sample size after inspecting test performance or report
fixed-prediction intervals as uncertainty over repeated model training.

Reduce selected immutable manifests and observations offline. Report official
quality, OOS detection, ordinal/bin information loss, valid-distribution proper
scores, calibration, failure and coverage, latency, throughput and accounting
provenance. Use nearest-rank latency percentiles and 2,000 sample-grouped
bootstrap resamples. Missing distributions or costs produce unavailable
metrics; exact zero probability on the true label can produce infinite log
loss. Do not fabricate beliefs from hard labels.

Fit model choices and abstention/cascade gates using validation evidence only.
The declared gate criterion is a 95% Wilson upper error bound of 5%; no eligible
threshold gives zero eligible coverage. A search over thresholds does not
establish an independent error guarantee. Policy replay supports quality and
routing estimates. Only executed workflows establish end-to-end cascade
latency, including model switching where required.

Before claiming a full comparative study, verify real execution for each
admitted model, all planned denominators, independent backend/accounting and
lifecycle reviews, retained source gates with coverage at least 90%, dataset
and model identities, cost closure and deterministic offline regeneration.
Select report/manuscript inputs explicitly. Rendered documentation must have no
unresolved tokens, citations or references. Publishing is a separate action.

## Reproduce the nine offline CPU jobs

Run these recipes serially from the repository root. They reproduce the fixed
comparator treatments; new source, dependency or input bytes receive new
manifests and run UUIDs. They do not overwrite or resume the recorded studies.
The measured environment used Python 3.14.4, scikit-learn 1.9.1, NumPy 2.5.3,
SciPy 1.18.1, joblib 1.6.0, threadpoolctl 3.7.0, psutil 7.2.2, httpx 0.28.1 and
PyYAML 6.0.3. Retain `uv.lock` and `pyproject.toml` with the SDK source snapshot;
check the installed versions rather than treating dependency ranges as pins.
Python 3.10 remains the minimum package requirement, not the measured runtime.

```bash
uv sync --frozen --python 3.14.4 --extra benchmark --extra figures
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
```

Set these variables before starting Python. They were actual process environment
controls in the CPU jobs; a config's `artifact` metadata alone does not enforce
thread limits. The fixed text pipeline is TF-IDF plus logistic regression
(`C=1`, `max_iter=2000`, seed `20261007`); the structured Wine pipeline is
DictVectorizer plus HistGradientBoostingClassifier (`max_iter=100`, same seed).
No model or hyperparameter search occurs in these recipes. The `benchmark`
extra supplies supervised fitting and resource sampling; `figures` supplies PDF
export. Dependency installation may need network access. All preparation and
execution commands below use already retained dataset source bytes and need no
API key or model server.

Use a fresh output namespace. The recipes resolve their dataset paths relative
to `benchmarks/configs/`, pointing at `.benchmarks/full-study-inputs/`. If those
outputs already exist, make new recipe copies with a new input namespace;
exclusive writers deliberately refuse replacement. Fetching pinned public
sources is a separate explicit step described in [datasets](datasets.md#pinned-public-datasets).

```bash
mkdir -p .benchmarks/full-study-inputs .benchmarks/full-study-runs .benchmarks/full-study-reports
for kind in banking77 clinc150 wine; do
  uv run --frozen --no-sync daf-jev benchmark dataset prepare --kind "$kind" \
    --source ".benchmarks/raw/$kind" --seed 20261007 --packed \
    --output ".benchmarks/full-study-inputs/$kind-source.json"
  uv run --frozen --no-sync daf-jev benchmark dataset folds \
    --source ".benchmarks/full-study-inputs/$kind-source.json" \
    --output ".benchmarks/full-study-inputs/$kind-folds.json"
done
for fold in 0 1 2 3 4; do
  uv run --frozen --no-sync daf-jev benchmark dataset view \
    --source .benchmarks/full-study-inputs/banking77-source.json \
    --view selection --validation-fold "$fold" --packed \
    --output ".benchmarks/full-study-inputs/banking77-selection-fold$fold.json"
done
for kind in clinc150 wine; do
  uv run --frozen --no-sync daf-jev benchmark dataset view \
    --source ".benchmarks/full-study-inputs/$kind-source.json" \
    --view selection --packed \
    --output ".benchmarks/full-study-inputs/$kind-selection.json"
done
for kind in banking77 clinc150 wine; do
  uv run --frozen --no-sync daf-jev benchmark dataset view \
    --source ".benchmarks/full-study-inputs/$kind-source.json" \
    --view final_train --packed \
    --output ".benchmarks/full-study-inputs/$kind-final-train.json"
  uv run --frozen --no-sync daf-jev benchmark dataset view \
    --source ".benchmarks/full-study-inputs/$kind-source.json" \
    --view final_train --cohort leakage_clean --packed \
    --output ".benchmarks/full-study-inputs/$kind-final-clean.json"
done
for kind in binary categorical ordinal bayes; do
  uv run --frozen --no-sync daf-jev benchmark dataset synthetic --kind "$kind" \
    --samples 150 --seed 20261007 --packed \
    --output ".benchmarks/full-study-inputs/synthetic-$kind-v3.json"
done
uv run --frozen --no-sync daf-jev benchmark dataset synthetic --kind categorical \
  --samples 35 --matched-option-permutations --seed 20261007 --packed \
  --output .benchmarks/full-study-inputs/synthetic-categorical-matched-v3.json
```

The packed files declare `dafjev.benchmark-dataset/2`, a SHA-256 of expanded
canonical examples and a separate order-sensitive examples digest. Retain each
exact file SHA-256 as well as its manifest, source revision/license/checksums,
fold-pack hash, algorithm/dependency versions and seed. Canonical and ordered
digests identify different aspects of the same expanded input; they do not
replace its file hash. Packed loading preserves native question IDs, complete
options, state, targets and order. It changes storage encoding, not task scope.

| Order | Recipe | Fitting and scoring scope |
| --- | --- | --- |
| 1–5 | [BANK fold 0](../benchmarks/configs/banking77-selection-fold0.yaml), [1](../benchmarks/configs/banking77-selection-fold1.yaml), [2](../benchmarks/configs/banking77-selection-fold2.yaml), [3](../benchmarks/configs/banking77-selection-fold3.yaml), [4](../benchmarks/configs/banking77-selection-fold4.yaml) | Prior and C1 fit four grouped training folds; score the remaining validation fold. Official test is omitted. |
| 6 | [CLINC/Wine selection](../benchmarks/configs/clinc-wine-selection.yaml) | Prior plus applicable C1/HGB fit original training rows; score published CLINC validation and Wine validation fold 1. Test is omitted. |
| 7 | [Canonical final fit](../benchmarks/configs/full-offline.yaml) | Fresh fits on merged non-test train/validation; score all official/grouped test rows. No validation gate fitting. |
| 8 | [Leakage-clean final fit](../benchmarks/configs/full-offline-leakage-clean.yaml) | Separate fits and test scoring after the declared input-group/conflicting-label exclusions. Keep canonical results alongside this sensitivity. |
| 9 | [Synthetic v3 quality](../benchmarks/configs/synthetic-v3-quality.yaml) | Uniform and exact analytical/rule references on independent synthetic truth; four 150-fixture suites plus 35 categorical base fixtures with complete cyclic permutations. |

Each recipe selects only quality and its declared capability probes, with no
warm or graphical observations and no test timing pack. All backend/dataset
arms remain planned, including intentionally unsupported classifier/task pairs.
The matched suite contains 105 physical rows: 63 train, 21 validation and 21
test. Its 42 scored rows are 14 complete groups, not 42 independent fixtures.
The references do not fit those train rows. Wine keeps test fold 0, validation
fold 1 and the other three folds for initial fitting. BANK out-of-fold scoring
covers each of the 10,003 original training rows once per applicable backend;
overlapping training fits do not establish independent model replications.

Plan one recipe, record the returned directory and manifest hash, inspect its
inputs/cell denominators, then execute that exact directory before planning the
next recipe. For example:

```bash
uv run --frozen --no-sync daf-jev benchmark plan \
  --config benchmarks/configs/banking77-selection-fold0.yaml \
  --out-dir .benchmarks/full-study-runs
# Substitute the UUID directory returned above; do not select the newest run.
uv run --frozen --no-sync daf-jev benchmark run .benchmarks/full-study-runs/RUN_UUID
uv run --frozen --no-sync daf-jev benchmark report .benchmarks/full-study-runs/RUN_UUID \
  --output .benchmarks/full-study-reports/banking77-fold0.json \
  --markdown .benchmarks/full-study-reports/banking77-fold0.md \
  --pdf .benchmarks/full-study-reports/banking77-fold0.pdf
```

Repeat with each table entry and distinct output names. Keep a selected-run
inventory mapping each recipe to its exact UUID, config/input/source hashes,
manifest hash and final head/journal/report hashes. Record training counts and
fit settings, thread environment, resource observations and every interruption.
Serial execution includes fitting, prediction and reductions; fitting is not
preemptible by a prediction timeout. Before each job, budget immutable input
copies, manifests, journals and reports as well as a retained free-space floor.
The measured jobs used a 1 GiB floor plus prospective receipt allocation; this
portable CLI sequence does not itself implement their external disk guard.
Inspect resource headroom before starting a job rather than deleting old evidence.

Regenerate each explicitly selected report twice into fresh output paths and
compare its JSON bytes while keeping source, inputs, manifest and journal held.
The SDK report uses 2,000 group-bootstrap resamples. A cross-fold reduction must
also verify that validation ID sets are disjoint and their union equals the
original BANK training IDs; repeated rows or five fold means are not substitutes
for that check. Validation-only gate evidence belongs to its original fitted
model, and is not transferred to the final refit. Prior official-test exposure,
label-dependent leakage sensitivity processing and unknown pretraining overlap
remain explicit. These recipes establish offline comparator evidence; they do
not grant native, hosted, funding, scientific or publication acceptance.
