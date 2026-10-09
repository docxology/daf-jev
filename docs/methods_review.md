# Modular methods review

Review scope: typed decisions, composition, provider abstraction, evaluation,
failure isolation, graphical inference and reproducible benchmarking. The
review started from source commit
`51d98048e4b1bc09e6adc2310eb00586b06b7cab`; its offline baseline was 797
passing tests and 94.42% coverage. Those are historical baseline observations,
not current post-change acceptance counts. Current checks must bind the final
source and completed test receipt. No paid inference evidence follows from the
review itself.

## Method boundaries

| Layer | Method | Evidence boundary |
| --- | --- | --- |
| Questions and parsing | named typed questions; fail-closed response validation | valid shape/vocabulary/numbers, not correct judgment |
| Composition | expectation, distribution reweighting, gates and routing | deterministic policy over supplied answers, not calibration |
| Orchestration | clients, evaluator, decider, breakers, async elicitation | lifecycle/failure behavior and retained attempts |
| Graphical inference | discrete CPTs and exact variable elimination | exact inference conditional on the supplied factors |
| Backend adapters | native distributions, generated values, letter labels, prior/classifier | explicit probability and confidence provenance |
| Benchmarking | frozen datasets/cohort, durable attempts, labeled metrics | observed task quality, timing and charges for exact inputs |
| Publication | evidence selection, token variables, figures and renderer | consistent rendered artifacts, not generalization or release acceptance |

`compose.py`, calibration statistics, graph inference, model selection and
posterior policies are pure computation. Clients, evaluator, decider and
elicitation perform I/O through injected collaborators. This distinction helps
test deterministic logic independently while exercising real HTTP/session
behavior at the orchestration boundary.

## Reproduced defects and repairs

### Invalid numeric or incomplete native decisions

Malformed probabilities and confidence values could cross portions of the old
wire boundary and then be counted by higher-level routines. The parser now
rejects booleans masquerading as numbers, nonfinite/out-of-range probabilities
or confidence, malformed row mass and negative token counts. Client validation
binds answers to the exact requested IDs, types, choice vocabulary and score
legend/range. Native rounded rows retain their declared precision allowance
without normalization. This allowance does not widen CPT or posterior-sidecar
budgets. See [_types.py](../src/daf_jev/_types.py),
[client tests](../tests/unit/test_client.py),
[async client tests](../tests/unit/test_async_client.py) and
[type tests](../tests/unit/test_types.py).

Compose helpers and `ConfidenceGate` also validate thresholds and supplied
confidence. A manually constructed answer cannot bypass the contract by using
NaN, infinity, a boolean or confidence outside `[0,1]`. Preserve intentional
composition semantics: negative score weights remain permitted and void the
usual bounded-expectation guarantee. Jaggedness counts invalid replies as
errors; it does not turn malformed rows into a degeneracy finding. See
[compose tests](../tests/unit/test_compose.py) and
[jaggedness tests](../tests/unit/test_jaggedness.py).

### Impossible partially observed evidence

A two-root network with P(a=true)=0, queried with evidence `a=true` while b was
hidden, previously returned the observed one-hot row for a. That represented an
undefined posterior as certainty. Inference now checks evidence mass before
returning an observed-variable indicator, including partially and fully
observed cases. `query` and `posterior` raise `ValueError` on zero-probability
evidence. Possible evidence still returns the correct indicator. See
[graphical.py](../src/daf_jev/graphical.py) and
`test_query_rejects_impossible_partially_observed_evidence` in
[graphical method tests](../tests/unit/test_graphical_methods.py).

### Async elicitation lifecycle

Running pooled async clients through independent temporary event loops could
leave persistent connections tied to a closed loop. The new
`elicit_cpts_async` and `propose_structure_async` await requests on the caller's
loop and leave closure to the caller. Tests exercise a real persistent HTTP
connection across structure/CPT calls, errors and cancellation. Legacy sync
wrappers accept a fresh async client as a single-use bridge and close it within
their one loop, including failure; calling the bridge from a running loop is
rejected with guidance to use the async API. Sync-client ownership is unchanged.
See [elicitation source](../src/daf_jev/graphical_elicitation.py) and
[tests](../tests/unit/test_graphical_elicitation.py).

### Decider mapping latch and paid fallback evidence

Resetting consecutive failures immediately after transport success prevented
repeated answer-mapping failures from reaching the failure latch. Reset now
occurs only after successful mapping and cache storage. Responses already paid
for retain usage and request ID in events even when a gate rejects, mapping
fails, a hook raises or cache storage fails. The ledger records the successful
transport once. This preserves the existing reason taxonomy and fail-open
behavior. See [decider source](../src/daf_jev/decider.py) and
[tests](../tests/unit/test_decider.py).

### Awaited circuit-breaker outcomes

A synchronous wrapper around an async callable sees a coroutine before its
failure occurs. `CircuitBreaker.call_async` now awaits completion before
recording success. Any `BaseException`, including cancellation, records failure
and re-raises, releasing/reopening a half-open probe. Tests include a real
persistent HTTP client and a cancelled recovery probe. The breaker remains
opt-in and does not add implicit retries. See
[resilience source](../src/daf_jev/resilience.py) and
[tests](../tests/unit/test_resilience.py).

### Selected-state calibration counts

The old `--states` option changed receipt metadata while collection still used
the complete built-in state list. Collection now receives the selected states;
the receipt derives state and answer counts from completed execution. Positive
run, state and repeat counts are checked before credential resolution or
networking. The real HTTP regression selects one state and two repetitions,
observes exactly four requests (choice and noul per repetition), and checks
every sent state. See
[calibration collection](../benchmarks/bench_calibration.py) and
`test_calibration_selected_state_count_matches_actual_calls` in
[legacy benchmark tests](../tests/unit/test_legacy_benchmarks.py).

### Cross-writer journal and execution-deadline custody

A first real Kev run exposed a journal-cache defect: frozen nested profile
lists were tuples in the writer's cached event but arrays in the retained JSON.
A legitimate append through an independent store triggered a false prefix
mutation alarm. Appends now canonicalize owned events through the exact JSON
representation before caching. The independent head and prefix checks remain
enforced. A two-store regression admits an actual nested frozen profile, adds
an external event and reconciles its receipt successfully. See
`test_external_append_after_frozen_backend_profile_preserves_ledger_reconciliation`
in [store tests](../tests/unit/test_benchmark_store.py).

Local prediction, backoff, retries and multi-call graphical workflows share
the remaining profile deadline. Resume deducts retained resource windows; an
unfinished window makes consumed local time unknown and prevents further local
admission. Timed-out graphical work preserves completed and cancelled attempt
receipts and its partial workflow. Tests exercise delayed real HTTP handlers,
retry exhaustion, a mid-graph deadline and resume without another request; see
[runner tests](../tests/unit/test_benchmark_runner.py). Synchronous classifier
fitting remains nonpreemptible by this asynchronous deadline and is reported
as a limitation.

The first failed pilot's manifest, source snapshot, journal, model custody and
unresolved final request remain separate evidence. Its completed rows are not
substituted into the corrected pilot. Changing source requires a new manifest;
an unresolved request is never silently retried or retroactively completed.

### Prepared-data memory and decimal summaries

Prepared loading previously constructed duplicate full-vocabulary question
objects and materialized the complete example array repeatedly while hashing.
The repaired path shares validated owned questions with an order-sensitive key
and streams the exact canonical digest one example at a time. Regression tests
compare the previous whole-array digest, option rotations and emitted request
bytes. A retained real CLINC load completes with all published rows and its
original digest; the earlier bounded probe was stopped above its RSS ceiling,
so its eventual peak is unknown. Whole-file JSON decoding still has a substantial
memory peak. This improvement does not identify the cause of the separate native
run's interrupted journal publication or establish local model acceptance.

Currency summaries previously converted decimal receipt strings into floats
before aggregation, and replay added float-valued costs as floats. Aggregation,
ratios, replay, liability calculations and ledger accounting now use a fresh
precision-50 decimal context. Monetary outputs retain decimal strings, unknown
charges remain unknown, and consumed known values are checked before unknown
propagation. Multi-question reports apportion retained request billing in exact
`1E-18` USD units and disclose the rule; the original charge remains authoritative
in its receipt and ledger. Regressions test exact totals, tiny charges, hostile
caller contexts, invalid consumed costs and per-question conservation.

### Full-fold selection, storage and hosted admission

Full validation previously lacked a retained inventory for rotating the other
BANKING training folds. Fresh preparation now records original split and grouped
fold identities, algorithm versions and dependency versions. Separate selection
views omit designated test rows; final-training views merge non-test rows and
provide no validation partition for fitting a gate. A leakage-clean companion
excludes its declared overlapping/conflicting groups before fitting. It remains
a separately named sensitivity experiment, with input and target participation
disclosed. See [dataset contracts](datasets.md#explicit-fold-inventories-and-fitting-views)
and [full-study protocol](full_study.md).

Quality-only plans without an explicit timing treatment now bind an empty pack,
rather than requiring held-out test examples. Unknown sampling values fail before
creating a run. Graphical execution rejects a backend lacking the Choice
primitive before transport. The corresponding real HTTP and offline regressions
are in [runner tests](../tests/unit/test_benchmark_runner.py).

An opt-in packed prepared format shares ordered question definitions. The public
loader expands it to the same immutable examples, complete vocabulary and native
request bytes, with required canonical and order-sensitive checksums. Default
format-one bytes remain unchanged. Real native/chat loopback comparisons and
malformed reference/order regressions cover the new boundary; they establish
serialization behavior, not model-weight execution. See
[dataset tests](../tests/unit/test_benchmark_datasets.py).

Hosted execution now recomputes liability against the actual frozen provider
settings in every HTTP mode. A saved liability mismatch or a route that would
need newly added price/fallback constraints refuses admission before backend
creation or weak cascade work. A constrained working copy cannot bound an
unconstrained actual request. Independent stale-manifest/resume checks exercise
this refusal without contacting a hosted service. This is a prospective safeguard,
not a finding of historical overcharging or undercharging.

## Graphical elicitation objective

Pairwise structure proposal is a model-judgment heuristic, not causal discovery
from sampled data. For a pair whose chosen option is a direction, its gain is
`log(p_edge) - log(p_no_edge)`. Exact ordering search maximizes the sum of gains
over order-compatible chosen edges minus `edge_penalty * edge_count`, with a
deterministic tie break. It searches orderings, not all arbitrary edge subsets:
all compatible candidates are retained for each scored ordering. Above
`exact_limit`, the greedy approximation admits positive penalized-gain edges
while avoiding cycles. These procedures have different search spaces and must
not be described as identical optimizers.

The returned proposal has edges but no CPTs; it is not a validated probabilistic
network until elicitation supplies every row. CPT probabilities are model
judgments about the stated population/context, not measured empirical
frequencies. Exact inference is mathematically exact for those factors, while
factor accuracy, calibration and causal interpretation need external evidence.

The new bounded [graphical benchmark](../src/daf_jev/benchmark_graphical.py)
provides a different control: the model receives an explicit generative graph,
reconstructs its factors, and is scored against analytical soft truth. It also
proposes edges and acquires at most three synthetic observations from an
independent reference sample, recomputing coupled posterior marginals after
each reveal. It records original model receipts and strict conversion failures;
synthetic observation costs are separate units. Its deterministic oracle tests
establish the experiment's behavior, not actual model quality.

## Corrected documentation claims

The following limits apply to the unchanged historical receipts:

- Batching retained timing/token totals but did not retain paired answers, so
  unchanged decisions were not measured. New answer comparisons must remain a
  separate result.
- Total-token ratios do not establish dollar savings. Input/output prices,
  provider surcharges, retries and missing cost fields matter.
- End-to-end pattern latency had no isolated transport/composition baseline,
  so it did not measure negligible composition overhead.
- Modal self-agreement calibration is a proxy. It can be stable and wrong;
  ground-truth accuracy calibration requires independent labels.
- Historical receipts lacked a complete runtime environment. Current render
  variables cannot supply that environment retrospectively.
- News/explanatory articles establish coverage, not the existence of software
  registries, routers or evaluation harnesses. Related-work prose now names
  primary software sources where software behavior is discussed.

## Benchmark extension and remaining gates

The new interfaces add frozen dataset/source identities, synthetic controls,
real-task preparation, local supervised comparators, explicit HTTP modes,
durable attempt/accounting journals, partial-denominator reports, grouped
uncertainty and policy replay. The command workflow is in
[decision_benchmarking.md](decision_benchmarking.md). Unit-tested adapters and
an offline baseline run are different from actual local model execution; public
catalog acquisition is different from hosted inference.

Before comparing local and hosted decision models, retain genuine weight/server
readiness, complete-vocabulary probes, prepared-data runs, requested/resolved
model identity and all attempt charges. Test thresholds must be frozen from
validation. Reports require adequate independent groups and failure denominators.
Local monetary expense, model training overlap, coupled re-ask execution and
policy latency remain unknown unless separately measured. Unsupported arms are
findings rather than hidden exclusions.

Before a scientific or release claim, independently review exact source/input/
output identities, selected evidence, uncertainty and cost reconciliation; run
current aggregate checks, validate rendered artifacts and verify any intended
public commit/deposit. This review does not establish a new published release,
a general model ranking or a universal calibrated-confidence guarantee.

## Retained timing scope and probability interpretation

The expanded Mac study's planner applied `timing_samples` within each dataset.
Its 368 shared timing IDs therefore exceeded the requested 100 physical examples
overall. Primary quality and an additional round reached clean boundaries;
further admission was withdrawn without changing the manifest, journal/head,
executed measurements or future unattempted denominators. The remaining planned
rounds are incomplete. An external additive stop receipt binds that outcome;
it is not a repaired plan or an invented terminal event.

Current source implements the prospective correction through
`benchmark_sampling.timing_sample_pack`: exact ordinary physical test-example
count, one seeded representative per dataset/input group and deterministic
dataset/task round-robin balance. The enclosing ordered input inventory binds
dataset indices to prepared bytes. Timing selection is target-free conditional
on that supplied pool; upstream class/OOS/Wine pilot stratification uses declared
targets. Separately counted complete matched bundles are quality controls and
never additional timing IDs. New timing selection
must not use test labels, observed model quality, confidence or intersections
of successful profiles. Unsupported and failed selected examples remain in the
shared denominator. A new source/cohort needs its own primary/input proofs,
with all prior wall consumption carried forward; it cannot call changed prompts
identical repetitions of the old primary. See
[the detailed timing rules](decision_benchmarking.md#shared-timing-cohort-and-the-retained-scope-deviation).

Actual corrected-cohort execution reached four closed primaries and four closed
warm rounds. Kev's fifth round also closed. During Qwen 4B's fifth round the
storage guardian recorded free disk below its fixed one-GiB threshold and sent
one SIGINT to its owned runner. The canceled request retained an attempt receipt
without a terminal cell outcome; that cell remains unresolved. Model unload and
process exit were observed, while the original coordinator window stays raw
and unclosed. No further Jeff or Qwen 0.8B fifth-round calls were admitted.
Known transport failures, unsupported inputs, that unresolved outcome and every
future unattempted cell stay in the denominators. This operational resource stop
is not a model-quality selection or evidence of complete five-repeat acceptance;
independent final custody, conservative accounting and reporting remain required.

The retained probability fields also describe provenance rather than a complete
meaning contract. Numeric row validation and a non-null native source do not
prove conditional beliefs, calibrated posteriors or CPT semantics. Jeff's
pinned decoder supplies transformed, normalized compatibility scores; Kev
supplies discriminative class estimates. Proper losses and half-L1 variation
are descriptive comparisons of these retained values with the stated target.
Keep unknown meanings explicit; stronger interpretation requires a documented
definition, applicability and independent calibration evidence. Current source
appends validated `probability_semantics` fields and retains unknown meaning
counts in metrics and repeatability. Graphical records explicitly name a
normalized surrogate-factor interpretation. These are new source contracts,
not retroactive properties of the preserved runs. See
[provider definitions](providers.md#probability-meaning-and-confidence).

## Audit reproduction appendix

The first source-frozen Mac study also exposed a synthetic-control limitation.
Its native adapter preserves choice-criteria insertion order. Its chat adapter
uses recursively sorted JSON for the model-visible prompt, while the strict
schema's option enum keeps the dataset order. Consequently, different full wire
hashes do not prove different prompt positions: those chat rows vary grammar
enum order with a fixed sorted presentation. They establish no prompt-position
sensitivity or zero-effect result. Generated variants also use distinct examples,
rather than matched counterfactual permutations; binary/ordinal variant names
can describe a control that has no actual option permutation. Preserve those
receipts and their actual presentation. Ordered presentation and matched
permutation controls require a new source/cohort after the frozen execution,
with their own regression and inference evidence.

The updated chat serializer preserves insertion order; its canonical semantic
receipt hash remains separate from ordered presentation evidence. Version-three
ordinary and matched prepared files verify order-sensitive example digests,
and matched loading verifies actual cyclic groups and unchanged semantics.
`test_benchmark_protocol_v3.py` exercises exact global selection, five-round
denominators, insufficient-pool refusal before artifact creation, real HTTP
prompt/enum order, stale/incomplete controls, unknown meaning, billing failures
and legacy report compatibility. `_json.py` rejects duplicate keys and
nonstandard constants; decoder recursion failures follow the malformed-response
path without imposing a fixed depth limit. `test_strict_json.py` drives native
sync/async clients through real loopback HTTP responses. Passing these source
regressions does not establish execution acceptance for a new model cohort.

These pointers identify the repaired boundaries and executable regressions in
the current source. Line numbers describe this implementation; use the named
symbols and tests after subsequent edits. The original review's commit remains
the pre-repair identity above. Reproducing a malformed response uses the real
loopback HTTP fixtures and requires no API key or model weights.

| Finding | Repaired boundary | Reproduction evidence and expected outcome |
| --- | --- | --- |
| Invalid numbers and request/answer mismatch | `_types.py:388`, `parse_response`; client response validation | `test_client.py:722`, `test_ask_rejects_invalid_response_without_retry`: invalid HTTP replies fail after one attempt in both client modes |
| Invalid composition mass or confidence | `compose.py:43`, `composite_score`; `compose.py:124`, `confidence_gate`; `compose.py:237`, `tiered_gate` | `test_compose.py`: invalid mass/nonfinite confidence is rejected; intentional negative weights retain their documented behavior |
| Certainty under impossible evidence | `graphical.py:452`, `posterior`; `graphical.py:473`, `query` | `test_graphical_methods.py:312`, `test_query_rejects_impossible_partially_observed_evidence`: observed and hidden queries raise on zero-mass evidence |
| Async clients bound to a closed private loop | `graphical_elicitation.py:477`, `elicit_cpts_async`; `graphical_elicitation.py:686`, `propose_structure_async` | `test_graphical_elicitation.py:280` and `:362`: persistent caller-loop reuse and caller-owned cleanup after cancellation |
| Mapping failures fail to latch | `decider.py:317`, `decide` | `test_decider.py:282` and `:300`: repeated mapping failures latch; complete pipeline success resets the counter |
| Calibration metadata diverges from requests | `bench_calibration.py:75`, `collect_answers` | `test_legacy_benchmarks.py:14` and `:35`: selected-state request counts match execution; invalid counts fail before networking |
| Async breaker records unawaited success | `resilience.py:121`, `call_async` | `test_resilience.py:99` and `:135`: cancelled half-open probes release ownership; actual HTTP completion determines the result |
| Cross-writer frozen-list journal mismatch | `benchmark_store.py`, canonical append/cache boundary | `test_benchmark_store.py:367`: a second store appends and reconciles an actual frozen nested profile without weakening custody checks |

For the focused battery, run:

```bash
uv run pytest tests/unit/test_client.py tests/unit/test_compose.py \
  tests/unit/test_graphical_methods.py tests/unit/test_graphical_elicitation.py \
  tests/unit/test_decider.py tests/unit/test_legacy_benchmarks.py \
  tests/unit/test_resilience.py tests/unit/test_benchmark_store.py
```

Aggregate acceptance still requires the complete configured unit suite,
coverage, Ruff, Mypy and snapshot verification. A focused rerun cannot replace
those receipts. Earlier infrastructure-failed pilots remain separate incident
evidence. Later scoped partial comparisons retain their own failed, unsupported,
unresolved and unattempted denominators; no historical receipt is rewritten to
match a newer implementation.

### Continuation: frozen inputs, missing arms and verification reuse

The next source review reproduced ambiguity in stored billing/source JSON,
configuration parsing, same-family dataset identity and partial cascades. It
also added retained verification so exact offline manuscript regeneration no
longer depends on ephemeral raw coverage. The following pointers describe the
current repair; source/test line positions may move, so preserve the named
regressions and exact source identity with each gate.

| Reproduced finding | Current boundary | Focused regression and expected outcome |
| --- | --- | --- |
| Duplicate stored charge, manifest or journal keys could silently select the last value | [_json.strict_json_loads](../src/daf_jev/_json.py#L26), [RunStore intake](../src/daf_jev/benchmark_store.py#L119), [catalog/gate planning](../src/daf_jev/benchmark_runner.py#L295) | [store tests](../tests/unit/test_benchmark_store.py#L450) and [cohort reporting tests](../tests/unit/test_benchmark_cohort_reporting.py#L183): outer/nested/escaped duplicates and nonstandard constants reject without rewriting retained bytes or releasing a contradictory charge |
| Literal YAML duplicate or merge-colliding keys could shadow frozen budgets/options; aliases and nonfinite safe-loader containers remained ambiguous | [_yaml.strict_yaml_loads](../src/daf_jev/_yaml.py#L42) | [strict YAML tests](../tests/unit/test_strict_yaml.py#L22): reject duplicate mappings, alias references, unsafe tags and nonfinite numbers in lists, sets and tuple-bearing collections; preserve normal literal order and global PyYAML behavior; invalid config creates no run |
| A standard exponent could overflow float parsing, while an extreme Decimal exponent raised outside the receipt error path | [_json number callback](../src/daf_jev/_json.py#L37), [HTTP receipt intake](../src/daf_jev/decision_backends.py#L275) | [strict JSON tests](../tests/unit/test_strict_json.py#L43): float overflow and Decimal precision failure become `ValueError`; a genuine HTTP attempt receives its malformed-response receipt. Finite Decimal values remain exact, with billing bounds enforced separately |
| Native successful-response decoding hid a strict overflow diagnostic behind a later raw-text type error | [client response intake](../src/daf_jev/client.py#L85) | [strict JSON tests](../tests/unit/test_strict_json.py#L99) and [graphical tests](../tests/unit/test_benchmark_graphical.py): malformed successful responses preserve the decoder failure; malformed HTTP errors retain raw bodies and status exceptions. Independent real sync/async loopback calls also verify valid follow-up responses and finalized backend receipts |
| Same-family prepared datasets collided in gate/replay lookup; wholly unavailable arms disappeared from quality summaries | [gate identity](../src/daf_jev/benchmark_runner.py#L270), [report dataset identity](../src/daf_jev/benchmark_runner.py#L825) | [cohort reporting tests](../tests/unit/test_benchmark_cohort_reporting.py#L54): config ID/index/prepared SHA bind each arm and validation gate, duplicate/empty IDs reject new plans, legacy aliases reduce by index, and missing arms retain planned decisions/cells/statuses with unavailable quality metrics |
| A hosted admission stop after completed weak work looked wholly unattempted, and cascades escaped the local weak deadline | [cascade partial evidence](../src/daf_jev/benchmark_workflows.py#L88), [runner timeout/admission outcomes](../src/daf_jev/benchmark_runner.py#L703) | [workflow tests](../tests/unit/test_benchmark_workflows.py#L124) and [runner tests](../tests/unit/test_benchmark_runner.py#L736): retain weak predictions and child receipts after strong refusal, distinguish no-child admission from partial failure, cancel a slow weak call within its cumulative allowance, and issue no implicit strong call or retry |
| Family-only publication labels or a non-null probability source could obscure input identity and unknown meaning | [publication identity](../src/daf_jev/benchmark_publication.py#L20), [backend meaning fields](../src/daf_jev/decision_backends.py#L43) | [publication tests](../tests/unit/test_benchmark_models_publication.py#L71), [cohort reporting tests](../tests/unit/test_benchmark_cohort_reporting.py#L54) and [protocol tests](../tests/unit/test_benchmark_protocol_v3.py): retain configuration IDs and exact inputs, explicit unknown meaning, and unavailable quality/cost. Provenance does not establish calibration or posterior meaning |
| Ephemeral coverage forced fresh collection during regeneration; malformed XML roots or negative suite offsets could inflate retained test counts; a dangling selection fell back to unselected behavior | [verification capture](../scripts/capture_verification.py#L25), [native JUnit validation](../src/daf_jev/evidence.py#L125), [selected verification](../src/daf_jev/evidence.py#L156) | [evidence tests](../tests/unit/test_evidence.py#L68): genuine unit coverage/JUnit plus live collection regenerate offline with exact before/after/current Python/config identity. Invalid roots/per-suite counts, stale records, symlinks and malformed explicit selections fail even in draft; failed captures retain outputs and remove only owned raw data |

Historical benchmark bytes now reach figures and manuscript variables through
one verified read, using `selected_benchmark_bytes`/`bound_bytes`. The path-based
compatibility functions do not establish the same consumption boundary for a
later caller read. A real miniature capture confirms selected regeneration
performs no new pytest collection; intentionally failed unit and identity
captures preserve their diagnostics and earlier raw coverage inputs. Live test
collection remains distinct from live execution. See the
[retained-verification recipe](reproducibility.md#retained-verification-for-exact-offline-regeneration).

A further finance review found no independent guarantee that one catalog
context length bounds aggregate native prompt billing across a request's state,
questions and options. The [liability calculation](../src/daf_jev/benchmark_runner.py#L204)
now retains paid native liability as
unavailable and rechecks admission for older stored numeric reservations;
all-zero admitted tariffs remain zero. This is a missing-bound finding, not a
proved historical undercharge. Chat context/output reservations remain
conditional on enforced limits and tariffs. The
[native admission regressions](../tests/unit/test_benchmark_native_admission.py)
exercise new plans, legacy direct profiles and cascade refusal before weak work.
See the
[admission contract](decision_benchmarking.md#attempt-lifecycle-and-spend).

Native live-collection evidence also needs a complete terminal footer. The
reader accepts one final quiet or paired verbose pytest footer, rejecting
missing, truncated, multiple or conflicting footers. Genuine miniature captures
exercise repository verbose options while retaining earlier parser-incompatible
captures unchanged; no live tests execute during capture.

These repairs describe current reducer/parser source. The local model responses
were produced under their separately frozen inference source; a new gate or
offline reducer cannot retrospectively upgrade those responses, complete a
stopped round, resolve an unknown attempt or establish hosted access. Earlier
reports and PDFs remain preserved. Independent local review receipts are kept
privately with the exact fixture/source hashes; they are not a publication or
scientific acceptance claim. Current aggregate counts and coverage must come
from the newly completed selected gate rather than being hardcoded here.
