# Synthetic and real benchmark datasets

Prepared datasets use inline `dafjev.benchmark-dataset/1` by default, or the
opt-in packed `dafjev.benchmark-dataset/2`. An experiment consumes
explicit local prepared files; imports and synthetic generators never fetch
data. Fetching the allowlisted official sources is a separate action. The
dataset implementation is [benchmark_datasets.py](../src/daf_jev/benchmark_datasets.py).

## Dataset contract

`DatasetManifest` records name, version, source, license, SHA-256, label kind,
the complete ordered label vocabulary and metadata. Each `BenchmarkExample`
records an ID, leakage group, split (`train`, `validation`, `test`), state,
typed questions, target labels or probability distributions, and metadata.
Example IDs are unique; cross-split groups fail unless an official canonical
BANKING77/CLINC150 manifest explicitly declares their identities and leakage.
Targets and question IDs must match. Preparation validates source values and
vocabularies; nonfinite JSON fails instead of becoming a dropped evaluation row.

The prepared file records a digest of canonical examples as well as source-byte
provenance. `save_dataset` refuses an existing destination. Loading verifies the
example digest when present. A run copies and hashes the exact prepared bytes;
it checks those bytes again at execution and report time. Never overwrite a
prepared file to repair a run's provenance.

Example hashing streams the exact canonical JSON array one row at a time,
avoiding a second corpus-sized list/string during checksum validation. Writing
also streams examples and retains the same default pretty JSON bytes. Prepared
loading shares identical owned question definitions using an order-sensitive
key; rotated option lists remain distinct, and wire bytes and example digests
are preserved. Prepared mappings require string instructions and isolate their
criteria from input payloads. Arbitrary direct typed-question constructors can
still contain mutable structured instructions or externally backed mapping
proxies; the prepared-loader guarantee does not establish universal deep
immutability of those programmatic objects.

`save_dataset(dataset, path, packed=True)` writes format two. It shares a
`question_sets` table of native mappings across rows instead of repeating the
full label descriptions. Table identity preserves question-ID and criterion
insertion order. Every example has one `questions_ref`: a nonboolean integer
within that table. Inline `questions` and references cannot be mixed. Loading
validates every table definition, including unused definitions, and expands
references through the same public loader used by the runner and CLI.

Format two requires `expanded_examples_sha256` and
`order_sensitive_examples_sha256` over the expanded examples. The former uses
canonical sorted JSON; the latter uses compact unsorted UTF-8 JSON and retains
insertion order. These checks bind state, questions, targets, IDs, groups,
splits and metadata, including real datasets without synthetic-v3 metadata.
The expanded `BenchmarkDataset.to_dict()` remains format one; both encodings
produce identical native requests. Default format-one bytes and historical
prepared inputs remain unchanged. `--packed` is available on `dataset prepare`,
`dataset synthetic` and `dataset view`; use it for full-study corpora to reduce
input and frozen-manifest storage. Hash and retain the actual chosen encoding.

## Synthetic controls

`make_synthetic_dataset(kind="binary", seed=0, n=120,
matched_option_permutations=False)` supports four controls.
These are mechanism tests with known target rules, not substitutes for real
language tasks.

| Kind | Model-visible state | Target construction | Appropriate metrics |
| --- | --- | --- | --- |
| `binary` | amount, limit and enabled flag | approve iff enabled and amount ≤ limit | accuracy, binary Brier, log loss and calibration when probabilities exist |
| `categorical` | generated billing/account/technical text | declared generating category | macro-F1, confusion, proper scores when available |
| `ordinal` | points | fixed ordered bands | ordinal MAE/RMSE and ordinal confusion |
| `bayes` | observed signal in a declared generative model | exact analytical posterior distribution | soft-target Brier/log loss; synthetic oracle reveal experiments |

The generator hashes its kind, seed and size and records its rule/version.
Current prepared generation uses `dafjev.synthetic/3`, records
`generator_version: 3` and binds it into the source hash. Historical
`dafjev.synthetic/1` files with algorithm version two remain separate retained
inputs. The eight deterministic
variants cycle through plain records, a negation wrapper, an untrusted quoted
note, choice-order rotation, conflicting quoted evidence, and reference-context
padding at nominal 256, 2048 and 8192 characters. Actual final lengths are
recorded as `context_chars`; the padding targets are not exact final lengths.
Bayesian states retain authoritative JSON fields and place variants inside
`irrelevant_text`. The quoted/context text never changes the generating rule.

Ordinary variants are different generated examples, not matched
counterfactual permutations of one state. A variant name does not guarantee
an actual order change for binary or ordinal questions. Native criteria retain
their order; the original chat adapter sorted model-visible criteria while
its schema enum followed dataset order. Current chat serialization preserves
insertion order in prompt content and schema enums. State lengths and canonical wire hashes do
not establish prompt-position variation or its causal effect. Preserve the
actual presentation in historical reports.

The opt-in `matched_option_permutations=True` expands categorical or Bayes
Choice base fixtures into every cyclic rotation (three or two members per
group, respectively). It declares `control_design:
matched_cyclic_choice_order`, `control_role: quality_control` and
`timing_eligible: false`; matching controls do not enter the ordinary timing
sample. `n` counts generated base fixtures across all original splits. It is
not the number of admitted validation/test rows. A compact quality cohort must
retain complete selected groups and record omitted training groups separately.
Loading validates unchanged state, question instructions, key-to-description mapping,
targets/oracle, split and group across each complete cyclic permutation bundle.
Recompute the actual option order, ordered-question hash and semantic fixture
hash on load/admission; reject missing or duplicate permutations and stale
metadata. Version-three prepared files additionally verify
`order_sensitive_examples_sha256`; the canonical example digest sorts mapping
keys and cannot alone detect an order-only edit. Ordinal levels keep
their ordered meaning and must not be treated as freely permutable labels.
Prompt criteria and strict-schema enums co-vary in the chat control: this tests
the joint ordered presentation, not an isolated causal prompt-position effect.

```bash
uv run daf-jev benchmark dataset synthetic --kind categorical --samples 35 \
  --matched-option-permutations --seed 20261007 \
  --output .benchmarks/data/matched-categorical-v3-full.json
```

This creates 35 base fixtures and 105 physical rows across all original splits.
Its validation/test members comprise 14 complete groups and 42 physical rows;
training rows remain excluded from evaluation. A smaller prepared view must
recompute both example digests and retain the full source/projection identity.
The ordinary four-suite [reference recipe](../benchmarks/configs/synthetic.yaml)
uses 150 base fixtures per suite saved to new `*-v3.json` paths, providing enough
independent test groups for its exact global timing count.

Binary amount and limit are independent uniform integers from 0 through 999;
enabled is an independent equally likely boolean. The natural approval rate
is approximately 25%, rather than a deliberately balanced binary sample.
Report the realized label counts for the prepared seed and split. Synthetic
data alone does not establish that a model's training excluded the rule or
similar generated examples; training overlap remains unknown.

Splits follow the deterministic index rule: one fifth validation, one fifth
test, and the remaining examples train. The Bayesian target is a distribution;
the hidden simulated assignment used by an oracle policy is metadata rather
than prompt state. Scoring a soft target does not invent a hard correctness
label. Keep any oracle value out of the model-visible state and request text.

`RuleDecisionBackend(kind)` is a scoped reference for these four synthetic
grammars. It receives state and questions only, parses the anchored authoritative
record, ignores explicitly untrusted suffixes and rejects missing, malformed or
ambiguous fields and changed question contracts. It produces hard binary,
categorical or ordinal outputs without probability vectors or correctness
confidence. Only Bayes produces a formula-derived distribution with
`analytical_bayes_rule` provenance. The runner's `kind: rule` requires the
declared synthetic manifest; it is not a comparator for real corpora. The
[synthetic configuration](../benchmarks/configs/synthetic.yaml) pairs this
reference with a uniform control across all four tasks.

## Explicit fold inventories and fitting views

Fresh real preparation retains every row's `official_split`, and `fold_index`
for BANKING official training rows and all Wine rows. Default splits remain the
same. `dataset_fold_pack(dataset)` exports all original IDs/groups/assignments,
seed, algorithm/version/dependency versions and canonical plus ordered example
hashes. It does not split an already selected subset. Historical prepared files
remain loadable; rotating views require new files prepared from original bytes.

`dataset_view(dataset, view="evaluation", validation_fold=None, test_fold=0,
cohort="canonical")` derives a new hashed projection of the complete source.
`selection` omits the designated test set. `evaluation` retains it.
`final_train` merges non-test training and validation rows into training and
retains test for scoring; it has no validation evidence for policy calibration.
Derived views cannot be projected again as if they were original sources.

BANKING validation folds 0–4 partition official training once. The same official
test remains outside every fit; do not score it five times during selection.
CLINC retains published splits and the exact `oos` label. Wine requires distinct
test and validation folds, defaulting to 0 and 1; three folds train. Final Wine
training uses all four non-test folds. Rotating Wine outer test is a separately
declared cross-validation treatment, not independent repeated test cohorts.

The optional `cohort="leakage_clean"` removes view-specific cross-split input
groups and conflicting independent-target groups from every split **before
fitting**. It preserves vocabulary and binds excluded counts/ID hashes, parent
source and fold pack. This differs from post-hoc leakage-filtered report rows
from an unchanged model. Cross-split inputs and conflicting target labels
participate in this prescribed sensitivity processing; it establishes neither
novel held-out evidence nor test-blind model selection. Keep the canonical
companion and prior test exposure explicit.

```bash
uv run daf-jev benchmark dataset prepare --kind banking77 --seed 20261007 \
  --source .benchmarks/raw/banking77 --output .benchmarks/full-study-inputs/banking77-source.json
uv run daf-jev benchmark dataset folds --source .benchmarks/full-study-inputs/banking77-source.json \
  --output .benchmarks/full-study-inputs/banking77-folds.json
uv run daf-jev benchmark dataset view --source .benchmarks/full-study-inputs/banking77-source.json \
  --view selection --validation-fold 0 --output .benchmarks/full-study-inputs/banking77-selection-fold0.json
uv run daf-jev benchmark dataset view --source .benchmarks/full-study-inputs/banking77-source.json \
  --view final_train --output .benchmarks/full-study-inputs/banking77-final-train.json
uv run daf-jev benchmark dataset view --source .benchmarks/full-study-inputs/banking77-source.json \
  --view final_train --cohort leakage_clean --output .benchmarks/full-study-inputs/banking77-final-clean.json
```

Repeat selection for folds 1–4. Prepare CLINC and Wine to separate new source
paths, then create their final-training/canonical and leakage-clean views using
the same commands without a validation fold. The [full offline recipe](../benchmarks/configs/full-offline.yaml),
[separately fitted sensitivity recipe](../benchmarks/configs/full-offline-leakage-clean.yaml)
and [BANKING fold recipes](../benchmarks/configs/banking77-selection-fold0.yaml)
use fixed comparators and quality-only execution. Final-training recipes disable
probes because merged validation labels cannot be calibration evidence.
Keep exact inputs/source snapshots and all planned denominators. Serialize CPU
profiles and declare thread limits; fitting is not preemptible by prediction
timeouts. Budget disk for prepared files, immutable run copies, journals and
reports while retaining the declared free-space floor and all old evidence.

## Pinned public datasets

The allowlist pins these upstream revisions and verifies exact file hashes.
Hashes and filenames live in `DATASET_SOURCES` in the implementation, avoiding a
second hand-maintained hash list in documentation.

| Dataset | Source and license | Questions and vocabulary | Split policy |
| --- | --- | --- | --- |
| BANKING77 | [PolyAI task-specific datasets](https://github.com/PolyAI-LDN/task-specific-datasets/tree/57ec275d8078af65b7731c2a98be812d844a6d6b), CC BY 4.0 | bank intent; all 77 categories | official test retained; grouped stratified fold from official train becomes validation |
| CLINC150 including OOS | [CLINC OOS evaluation](https://github.com/clinc/oos-eval/tree/828f8093932c8fe6ca7936c3d2e52903b1c523de), CC BY 3.0 | 150 in-domain intents plus OOS | official train/validation/test and OOS partitions retained |
| Wine Quality | [UCI Wine Quality](https://archive.ics.uci.edu/dataset/186/wine+quality), CC BY 4.0 | red/white type and 11 physicochemical features → five ordered quality bins | grouped stratified five-fold split: first test, second validation, remaining train |

Wine Quality uses both red and white source files, bound independently by
SHA-256. The upstream sensory grade is 0–10; the adapter declares bins 0–2,
3–4, 5–6, 7–8 and 9–10 as score indices 0–4. Original grades remain target-side
metadata for the audit, rather than model-visible target values. Ordinal
MAE/RMSE measure errors in bin indices, not original grade points. The report
audits original-grade histograms and empirical conditional entropy
H(original grade | bin), in bits, to describe information lost by binning.
That entropy is not model prediction error. The source's feature, target and
license metadata were reviewed on 2026-10-07.

These source references establish dataset provenance. They do not establish
that any candidate model's pretraining or fine-tuning excluded the data. Record
training overlap as unknown unless independently supported. Real public data
can be easy to obtain while remaining contaminated as a model-comparison test.

`fetch_dataset(kind, destination, timeout=30)` downloads only allowlisted HTTPS
files, checks the final source host, limits response size, verifies pinned
SHA-256 and refuses to replace different existing bytes. It writes a
`dafjev.dataset-sources/1` source manifest. Existing files are rehashed rather
than trusted. `load_dataset(path, kind=..., seed=..., expected_sha256=...)`
prepares local files. A fixture without the official manifest and exact pinned
bytes is marked as fixture/unverified source, not as an official acquisition.

## Leakage controls and sampling

Text grouping hashes whitespace-normalized, case-folded text. Canonical intent
cohorts retain all published rows, including explicitly declared cross-split
overlaps and conflicting-label groups. Preparation records duplicate, overlap
and conflict identities/counts. Separate `duplicate_sensitivity_cohort` flags
exclude overlapping or conflicting groups; `unique_input_sensitivity_cohort`
flags select singleton inputs. The report retains canonical and leakage-filtered
metrics instead of silently rewriting official splits. Wine grouping hashes the
full feature/type state and keeps each group in one fold. These checks catch
exact normalized duplicates; they do not prove absence of paraphrases,
near-duplicates or model-training overlap.

Grouped stratified preparation uses an explicit seed and requires sufficient
independent groups per class. The optional scikit-learn dependency is needed for
these split operations and fitted baselines, not for importing the core package.
Complete vocabulary is retained even when an evaluation subset contains few
examples per class.

`pilot_samples` selects a deterministic bounded subset per split and intent
class, with a separate OOS limit. Wine is capped per split/type and apportioned
across bins according to their observed proportions, rather than forced into
equal bin counts. Sampling metadata records selection parameters and split
counts. A sampled pilot is not the original population distribution: report its
sampling policy alongside macro-F1,
accuracy and calibration. Repeated timing calls reuse examples and retain their
group IDs; they must not inflate independent statistical sample counts.

The requested warm protocol selects 100 physical examples globally across the
test task cohorts, before capability or outcome filtering, and shares that pack
across models and five additional rounds. Matched bundles count every physical
row toward the total. The earlier per-dataset selector produced an expanded
368-ID cohort; its retained evidence stays separate. See the
[sampling and compatibility rules](decision_benchmarking.md#shared-timing-cohort-and-the-retained-scope-deviation).

## Separation of roles

- Train fits the prior, TF-IDF/logistic and structured classifiers.
- Validation supplies calibration observations and chooses policy thresholds.
- Test measures the frozen model and policy. Test labels must not determine
  model selection, threshold search or preprocessing vocabulary.
- Timing repetitions measure repeated execution; quality and repeat phases are
  reported separately.

Any task variant, prompt revision, vocabulary change, split change or sampling
change requires a new prepared identity and experiment plan. Keep raw public
data and run directories outside tracked public artifacts unless their license,
privacy and intended publication have been reviewed. Reports can retain hashes,
source citations and aggregate counts without copying private input corpora.

## Acceptance checklist

Dataset acceptance requires exact source bytes/license/revision, prepared digest,
complete vocabulary, declared split/sampling policy and explicit duplicate
overlap/conflict audit. Declared canonical leakage needs separate sensitivity
results; it cannot establish uncontaminated held-out performance.
Scientific acceptance additionally needs sufficient independent test groups,
documented label quality and a candid training-overlap assessment. A successful
loader or local fixture test establishes schema behavior only.
