# Reproducibility and evidence

Reproduction binds an experimental intent to exact source, inputs, settings,
attempts and results. It cannot make a stochastic hosted response bit-for-bit
repeatable. The evidence tier must match the claim: schema and local transport
tests, real local inference, hosted inference, labeled scientific comparison,
rendered paper and public release are distinct outcomes.

## Evidence inventory

| Artifact | Establishes | Does not establish |
| --- | --- | --- |
| hashed TypeSafe snapshot and offline verifier | retained documentation bytes and drift | current upstream behavior or model quality |
| unit tests with real local HTTP fixtures | parser/transport/lifecycle/accounting behavior | execution of model weights |
| prepared dataset/source manifest | exact inputs, labels, groups and splits | absence of training contamination |
| public model catalog snapshot | discovered IDs, descriptions and listed prices at fetch time | inference access or correct capability declarations |
| frozen run manifest/journal/receipts | exact planned cohort and observed attempts | successful unattempted arms or correctness without labels |
| offline report/policy replay | reduction of identified retained observations | a new model call or executed policy latency |
| token map/figure registry/PDF checks | rendered consistency and known source selection | deployment, archival publication or scientific generalization |

## Run custody

The benchmark run directory contains `manifest.json`, copied `inputs/`,
`events.jsonl` and a saved journal head. The manifest captures source file hashes
alongside git HEAD; a dirty source tree therefore has an explicit identity.
Dataset bytes are checked before execution, after execution and during report
reduction. Every journal event records sequence, previous hash and its own
canonical hash. The saved head rejects partial/truncated journals rather than
accepting the last parseable line. An exclusive lease prevents two local
executors from owning the same run concurrently.

Keep interrupted evidence intact. A missing terminal receipt is unresolved;
unknown charges are retained liabilities. Do not delete a failed cell, modify
predictions, repair a manifest or retry uncertain paid work to make the report
look complete. Plan a new run for changed code, prompts, models, inputs or
protocol. Current locking uses `fcntl` and has a Unix execution boundary.
Original lock device/inode identities are frozen for execution and resume;
a copied artifact can be verified without mutation through
`RunStore(..., read_only=True)`. Portable read-only inspection is not Windows
executor acceptance.

Execution freezes the package source hashes and dependencies in the manifest.
A source-bound benchmark plan/run currently requires this Git-backed source
checkout: `source_identity()` inventories `src/daf_jev/` and resolves its Git
HEAD. Installed-wheel execution has not been accepted and cannot substitute an
empty source inventory. The backend library interface is separate from this
executor boundary. Retained-source offline reduction imports its selected bytes
without starting a new plan or inference run.
A commit ID alone does not reconstruct uncommitted changes. Retain those exact
source bytes alongside a run before execution, with a hashed file inventory;
the initial Mac pilot also stores `source_snapshot/` and a journal event binding
its selection. Offline reproduction may import the retained source through
`PYTHONPATH=RUN_DIRECTORY/source_snapshot/src` in a matching isolated environment.
Verify the snapshot files against the manifest before importing. Reporting does
not grant a copied run executor ownership or permit replay of unknown requests.

Local deadlines include prediction, retry backoff and the whole graphical
workflow. Resume deducts completed resource windows, and an unclosed local
window stops admission because its consumed time is unknown. Interrupted HTTP
and graphical work retain cancelled receipts and partial state. Synchronous
baseline fitting is nonpreemptible by the asynchronous deadline; report its
observed duration and this limitation separately.

For local model receipts additionally retain server code and weight revisions,
tokenizer/quantization, runtime and hardware, setup/load intervals and a genuine
capability probe. For hosted receipts retain requested/resolved model/provider,
response ID, request hash, pricing snapshot, every retry, observed charges and
any unresolved attempt. Request hashes avoid putting credential values in
manifests, but prepared input copies and prediction rows can contain private
data. Review a run directory before public transfer; a hash is an identity, not
an anonymization mechanism.

## Retained scope correction and local execution boundaries

The retained expanded Mac study used a larger timing cohort: its legacy
per-dataset selector produced 368 shared timing IDs instead of the requested
100 examples overall. Primary quality and one additional round reached clean
execution boundaries before further admission was withdrawn. Retain the
original manifest, journal/head, all created run bindings, closed startup/load/
execution/shutdown windows and every future unattempted denominator. An
external additive stop receipt can bind that boundary without inventing a
terminal event or rewriting the frozen schedule. The original study remains
incomplete and must not auto-resume.

A corrected 100-example cohort is a prospective experiment with a new accepted
source, frozen global sampling rule, selected-ID pack and input proofs. Its task
mixture must be specified from the protocol and available prepared inputs,
without using observed model accuracy, confidence or test outcomes. Repeated
calls must match its own primary's exact presentation; older sorted chat prompts
cannot serve as identical-prompt baselines for a later ordered serializer.
Preserve old measurements as a separate expanded cohort rather than relabeling
them as the corrected protocol. All consumed preparation, setup, inference and
teardown time carries forward in the same cumulative profile allowance; a new
manifest does not reset the clock.

Carry exact closed execution charges, including conservatively allocated
runtime preparation, without refunds. Measure new required profile inventory,
input proofs, launch/load, prediction and teardown windows separately and add
them to the inherited allowance. General documentation, code design and report
drafting are engineering work, not measured model-profile execution. A wall-clock
upper bound for that work must not silently become an inference-time charge.

Current planning freezes a target-free global timing pack with exact counts
and a separate declared quality-control cohort. New synthetic files validate
order-sensitive example identities and complete matched groups; current chat
prompts preserve insertion order. Those changes require fresh source/input
acceptance and fresh runtime/input proofs. Implementation and offline validation
are distinct from any subsequent native or hosted execution acceptance.

The subsequent local study used its own corrected source, global pack, ordered
presentations and primary runs. All four primary passes and four complete warm
rounds closed. Kev also completed its fifth warm pass. The fifth Qwen 4B pass
crossed the frozen one-GiB free-disk boundary: the guardian delivered one SIGINT
to its directly owned runner, retained a canceled attempt, and the coordinator
stopped further admission. Jeff and Qwen 0.8B's fifth passes stayed unattempted.
This is partial execution of the requested five-round protocol. It cannot be
reported as a complete five-repeat comparison.

The interrupted model was unloaded, the owned runner/model processes exited,
and the empty serving daemon was subsequently stopped by its owner. Those
process observations establish a cleanup boundary; they do not manufacture a
`pass_finished` event or resolve the raw coordinator window. The canceled
request has an attempt receipt but no terminal prediction outcome, so its cell
remains **unresolved**. Preserve completed, unsupported, failed, unresolved and
unattempted cells separately, including both future passes. Keep original
journal/head bytes intact and obtain an independent stopped-run custody,
conservative-clock and report review before admitting comparative results.
No retry, resume, budget reset or model substitution repairs this history.

Source and rounding provenance also do not establish probability meaning.
Unknown native semantics stay unknown, and numerical Brier/half-L1 reductions
of retained rows remain descriptive. Synthetic option variants do not establish
matched causal prompt-order effects. Any stronger interpretation needs its own
documented definition, validated cohort and independent acceptance. See the
[probability guide](providers.md#probability-meaning-and-confidence) and
[timing protocol](decision_benchmarking.md#shared-timing-cohort-and-the-retained-scope-deviation).

## Historical receipt limits

The committed September benchmark JSONs remain evidence for their recorded
model alias, date, configuration, timings, tokens and proxy statistics. They do
not record all software/hardware identities or dollar charges. Historical
batching results do not retain the paired answers necessary to prove answer
equivalence. Pattern latency includes the network and local composition together
and has no isolated baseline for composition overhead. Historical calibration
uses modal self-agreement, not independent ground truth.

Package version describes the current source tree. With selected verification,
Python and platform describe the recorded verification environment; otherwise
they describe variable generation. Do not attribute either environment to
historical model execution unless the receipt records it.
Do not merge independently selected “latest” files into an apparently single
model/date/environment cohort. Keep old receipts intact and state unknown
fields; a newer schema cannot retrospectively manufacture missing evidence.

## Documentation snapshot

The [snapshot manifest](reference/MANIFEST.json) records each page's URL, size and
SHA-256. Offline verification checks the exact retained tree:

```bash
uv run daf-jev docs-verify
uv run python scripts/scrape_docs.py --check --manifest docs/reference/MANIFEST.json
```

Without `--manifest`, `scripts/scrape_docs.py --check` fetches upstream pages and
compares them against disk. Plain scrape rewrites the snapshot and prunes pages
not in the fresh manifest; it is a network/mutation action. Do not hand-edit
snapshot pages to resolve drift. The source-checkout verifier is anchored to the
repository; installed package copies do not carry the whole snapshot by default.

## Tests

```bash
uv sync --extra dev --extra figures --extra benchmark
uv run ruff check src tests benchmarks scripts
uv run mypy src/daf_jev
uv run pytest tests/unit --cov=src
```

Use repository configuration and current CI to determine required checks.
The CI matrix declares Python 3.10 and 3.14 checks with development, figure and
benchmark extras. A local gate on one interpreter does not establish the other
matrix job or remote CI success.
Tests drive real transports through an ephemeral loopback HTTP server; they do
not monkeypatch package behavior. Live tests require a separately supplied
process-environment key and retain their `live` marker. A skipped live test is
not live acceptance. Generated test counts and coverage must refer to a completed
check of the current source; prior results are not a current-tree guarantee.

### Retained verification for exact offline regeneration

Use the native capture to retain unit execution/branch coverage and live test
collection in a fresh directory inside the checkout:

```bash
uv run python scripts/capture_verification.py --out-dir .benchmarks/verification-new
```

This runs the real unit pytest command with coverage JSON and JUnit, then
collects live tests without executing them. It retains command logs and a
`dafjev.verification-evidence/1` record, including failed captures. Only raw
coverage owned by that fresh capture is removed; earlier inputs are preserved.
It neither updates publication selection nor publishes anything. Prepare the
repository extras first; this capture is a local source gate, not a model run.

Select the completed `verification.json` by adding its relative path and exact
SHA-256 to the optional `verification` entry in `manuscript/evidence.json`:

```json
{
  "verification": {
    "path": ".benchmarks/verification-new/verification.json",
    "sha256": "<exact SHA-256 of verification.json>"
  }
}
```

This is a fragment of the existing `dafjev.publication-evidence/1` selection;
keep its historical benchmark selection intact and use the actual hash.
Selection is deliberate and does not authorize a newer model result, funding,
execution or release. The parser checks every selected artifact and requires
the exact before/after/current inventory: all source, test and script Python
files, plus pyproject, lockfile, manuscript experiment configuration and CI
workflow. File additions/removals also change identity. Publication selection
itself is excluded so choosing the completed capture does not invalidate it.
This inventory identifies the declared Python/configuration inputs; it is not
an inventory of every installed dependency, non-Python fixture asset or serving
runtime. Model/runtime custody remains a separate protocol.

With this selection, variable regeneration reads the retained native exports
without pytest collection or raw `.coverage`. Unit count means passing,
unskipped execution; live count means collection only. Python/platform come
from the recorded verification environment. Malformed, incomplete or stale
explicit verification fails even with `--allow-draft`; no automatic fallback
to current collection or old raw data is allowed. Hash-bound exports are
retained check evidence, not continuous source attestation or live acceptance.

Without an explicit verification selection, the historical collection/raw-data
path remains supported. For that path, keep fresh ephemeral `.coverage` through
token/evidence custody, then remove it. Missing/stale data or `N/A` is unavailable
measurement, not permission to substitute a remembered result. A layout-only
rerender may reuse the unchanged, already validated saved map.

## Manuscript and figures

Measured manuscript values remain `{{TOKEN}}` placeholders. A reviewed evidence
selection must bind the exact result files used by both variables and figures.
`manuscript/evidence.json` declares `dafjev.publication-evidence/1` and binds
selected paths to file hashes. Missing or changed inputs fail; reviewing model,
date and protocol compatibility remains necessary. The
historical paper and new benchmark-run reports are separate evidence schemas;
new arm reports are not silently injected into old result tokens.

From the repository checkout:

```bash
uv sync --extra figures
uv run python scripts/generate_figures.py --include-study
uv run python scripts/z_generate_manuscript_variables.py
uv run python scripts/render_pdf.py --output output/pdf/reproduction.pdf
```

The standalone variable script writes `output/data/manuscript_variables.json`;
the in-repository renderer resolves manuscript tokens using that map and writes
the selected fresh PDF path. It refuses to overwrite an existing output; choose
a new path for a rerun. Token-substituted `output/manuscript/` sections
belong to the optional external template integration; they are not a prerequisite
for the standalone renderer. Rendering requires the documented Pandoc/TeX
toolchain: Pandoc, XeLaTeX, BibTeX, the declared TeX packages, Times New Roman,
Menlo, and `latinmodern-math.otf`. Fonts and compiler versions are reproduction
inputs, not bundled package dependencies. The release reproduction record binds
the source-build commit, its `SOURCE_DATE_EPOCH`, saved variables, selected
evidence, figures and toolchain. Exact same-host reproduction uses that source
commit with the released evidence/figure/map inputs overlaid; the later artifact
commit has a different HEAD timestamp. Cross-platform PDF byte equality is not
established. The renderer rejects unresolved bibliography entries, references,
unloadable images and overfull vertical boxes. Use `--artifacts-dir DIR` with a
fresh directory to retain intermediate TeX and logs for review. Inspect every
section heading, representative prose and page layout as well as unresolved
tokens and citations: a successful typesetting exit alone does not establish
content completeness. A layout-only rerender may reuse the exact saved variable
map. `GENERATION_TIMESTAMP` is the pinned reproducible build timestamp; record
actual render time separately. `--allow-draft` produces draft sentinels for missing inputs and must
not be used as final measured evidence. `--install` replaces the root PDF and is
an explicit additional action.

## Publication gates

Local tests and rendered artifacts can be complete while model execution or a
scientific comparison is still pending. A publication candidate needs exact
source/input/result hashes, sufficient independent labeled holdouts, fixed
policies, failure denominators, cost reconciliation and all material limitations.
An archival release additionally needs the intended version metadata, verified
remote commit/tag identity, reviewed release files and a confirmed published
record. Historical DOI metadata is a dated record; it does not prove the current
working tree has been published. See [methods review](methods_review.md) for
the reproduced defects and remaining scientific gates.

## Selected empirical figures and manuscript scholarship

The expanded working manuscript selects two retained public aggregates through
`manuscript/evidence.json` `study_summaries`: the CPU comparison and the hosted
continuation summary. Each selection has an exact relative path and SHA-256.
The hosted summary carries the older native cohort with its separate identity.
These sources remain historical execution evidence after software changes;
selecting them does not repeat model inference or upgrade partial studies.

```bash
uv run python scripts/generate_figures.py --include-study
uv run python scripts/z_generate_manuscript_variables.py
uv run python scripts/render_pdf.py --output output/pdf/expanded-reproduction-new.pdf \
    --artifacts-dir .benchmarks/expanded-reproduction-build-new
```

The figure command appends six empirical figures to the seven legacy entries.
All figures have PNG and vector PDF copies. Each empirical figure also has a
`.data.json` companion recording exact input hashes, the plotted observations
and interpretive scope. No model, calibration fit, resampling or hosted call
runs during figure generation. Missing or changed selected inputs fail; newer
unselected files cannot replace them. The default legacy API still renders
seven figures. A study `--only NAME` invocation requires `--include-study`.

CPU accuracy intervals resample input groups for fixed predictions. They do not
include refitting uncertainty. BANKING77 folds have overlapping training fits;
their spread is descriptive. Leakage-filtered sensitivity changes both cohort
and fitting, so its displayed changes have no paired or causal interval. Wine
MAE/RMSE use bin indices; original-grade information loss and sparse bin counts
are separate quantities. Validation gates retain zero eligible coverage and
unavailable risk when no threshold qualifies; adaptively chosen Wilson bounds
are not simultaneous deployment guarantees. Coverage figures retain separate
CPU, older-native, hosted-pilot and proposed-full-study denominators.

The bibliography connects these interpretations to primary work on proper
scoring, calibration, selective prediction, orchestration, constrained decoding,
benchmark design and contamination. Provider documentation establishes declared
interfaces, and cannot establish achieved quality. The standalone render gates
remain necessary alongside visual, citation and full-text completeness review.
