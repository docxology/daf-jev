# Perplexity native decision preparation

The package prepares one separate Perplexity native decision profile through
OpenRouter's Decisions endpoint. Actual Perplexity hosted execution, model
quality, latency, precision and calibration are **UNATTEMPTED/UNKNOWN**. The
existing Jev capability evidence cannot establish Perplexity acceptance.

The [Perplexity quickstart](https://docs.perplexity.ai/docs/decisions/quickstart)
and [request/response reference](https://docs.perplexity.ai/api-reference/decisions-post)
document `pplx-decider-v1.1-27b`. The retained
[OpenRouter endpoint metadata](https://openrouter.ai/api/v1/models/perplexity/pplx-decider-v1.1-27b/endpoints)
identifies `perplexity/pplx-decider-v1.1-27b` and provider tag `perplexity`.
Public checkpoint/runtime capabilities are separate from the hosted API.

| Declared hosted limit | Executable contract |
| --- | --- |
| Input under 262,144 tokens, including state, images and every question | Code-owned maximum 262,143 total input tokens |
| 1–128 questions | `max_questions: 128` |
| 1–255 Choice options | `max_options: 255`; full 77/151 vocabularies retained |
| 1–10 Score levels | `max_score_levels: 10`; existing wire protocol requires at least two |
| USD 0.02 per million input tokens; free output; no request fee | Exact input tariff/ceiling; zero completion/request/image/cache premiums |
| 32 MiB request body | Provider-declared boundary; no local body-limit acceptance claim |

The explicit selector is
`openrouter-perplexity-pplx-decider-v1.1-27b-input262143/1`. It selects a
code-owned descriptor rather than trusting a caller's token bound or catalog
context. The route sends only `provider.only: [perplexity]`,
`allow_fallbacks: false`, `require_parameters: true`, and fixed price ceilings;
no auxiliary services, prompt controls or output generation settings are
enabled. Strict `1e-6` row mass validation and null rounding are consumer
protocols, not measured Perplexity precision. Invalid/incomplete rows remain
failures without normalization. Probability meaning and calibration stay unknown.

The maximum conditional reservation is **USD 0.00524286 per actual attempt**.
It is not an expected bill. Each retry needs separate admission; the existing
USD 25 allocation covers all models, probes, failures and retries. These
templates create no allowance and cannot bypass unresolved billing.

The observer retains and reconciles receipts before latching a contract stop.
Input usage above 262,143, cost above reported input usage times the pinned
tariff, or missing billed input usage stops further admission. Successful
responses must resolve to the exact namespace, documented short model, or
discovered canonical `perplexity/pplx-decider-v1.1-27b-20261006`, and
provider `Perplexity` or `perplexity`; missing/other identities fail closed.
The short name comes from the direct API's documented echo; actual OpenRouter
resolution conventions remain unverified. The canonical literal is bound to
catalog SHA-256 `594c20ac042cd08ee79e6f5fed8a8dd87a50f47a510903115c77cc3097f959be`
and endpoint SHA-256 `514320287e5e45d6845c89fa48cd5273a7c01e6f1bf7447584994350a55a9e0c`
in the frozen descriptor. Discovery establishes a known identifier, not
physically served weights. No other date suffix or latest alias is inferred.
The inherited durable stop reason is
`native_input_contract_breach`; retained per-run `breach_dimension` specifies
the violation. Failed HTTP responses may lack model/provider identity, while
unknown charges remain unresolved under the existing accounting policy.

## Frozen recipes and admission

The [pilot template](../benchmarks/configs/native-perplexity-pilot.yaml) uses
the three canonical real datasets and pilot pools. The
[full template](../benchmarks/configs/native-perplexity-full.yaml) uses the
held twelve-dataset V3 preparation: canonical real views, four independently
labeled synthetic families, matched categorical order controls, and four
additional BANKING validation folds (fold zero is in the primary source view).
No prepared corpus or hosted observations are included in these templates.

Bind the existing allocation explicitly and supply the exact retained prepared
inputs. Before planning, refresh and retain the catalog/provider/doc snapshots,
bind their checksums and preserve the shared timing sample pack across arms.
The template records the October 9 primary-source SHA-256 values; refreshing
them requires a new frozen manifest. Catalog revision, weights/tokenizer,
license, hosted precision and quantization need explicit retained inventory or
unknown values. A catalog slug is not proof of the physically served revision.

Use seed 20261007, one primary prediction per quality example, 100 shared timing
examples and five additional repetitions, concurrency four, 60-second timeouts
and at most two separately admitted transport attempts. Capability probes must
retain full BANKING77/CLINC151/Wine-five vocabularies before quality. Complete
ordinary outcomes, matched controls and failed/unsupported/unattempted cells
remain separate denominators. A source template or loopback regression is not
a successful hosted probe.

The optional graphical phase uses the existing frozen reference/oracle,
32-row CPT chunks, eight-node exact-search limit, edge penalty 1.0 and three
reveals. Native origin alone does not establish conditional factor semantics;
graphical comparisons remain descriptive unless that meaning is supported.
Validation-only policies and executed workflow latency retain their existing
boundaries. See [datasets](datasets.md), [native study](native_hosted_study.md),
[metrics](decision_benchmarking.md) and [shared accounting](shared_allocations.md).

## Prospective joint native comparison

The [joint full-study template](../benchmarks/configs/native-comparison-full.yaml)
declares the Jev and Perplexity profiles on the same twelve retained input
views, seed 20261007 and 100 shared timing examples with five extra repetitions.
It interleaves both hosted arms in the frozen schedule, with global concurrency
four, 60-second per-call timeouts and at most two separately admitted attempts.
The runner freezes its existing graphical protocol for each arm. Requests use
complete native vocabularies; no generated-chat arm or substitute is introduced.
An inference-free plan check on the retained V3 inputs and shared timing pack
derives 50,154 planned cells: 24 capability probes, 49,128 quality cells,
1,000 warm repetitions and two graphical cells. Each arm has the same 25,077
cell obligation. These are planned cells, not completed predictions or a count
of billable requests; graphical cells can invoke multiple requests. New input
bytes require newly derived denominators.

Freeze this joint manifest before reviewing completed test-quality performance
or selecting a model from it. The existing Jev-only execution is exploratory
evidence under its own source, cohort and timing treatment; it is not one arm
of a retrospectively randomized joint study. New joint quality predictions
must be generated under the joint protocol. Preserve its model identities,
shared sample pack, denominators, failures and allowance rather than importing
earlier primaries as new repetitions. Paired comparisons still require complete
matched evidence and the declared probability/ordinal semantics.

The joint recipe remains preparation, not an executable allocation binding.
Both models share the existing USD 25 total authorization, including prior
reported charges, held historical uncertainty, probes and retries. The recipe
creates no budget, contains no allocation path or credential, and promises no
full-study completion. Actual Perplexity hosted acceptance remains UNATTEMPTED.

## Local and hosted evidence boundary

No local Perplexity model is installed or accepted by this preparation. The
public checkpoint's [inspected local preparation](https://huggingface.co/perplexity-ai/pplx-decider-v1.1-27b/blob/6195aa55a72ae21e503c8a60198f7b390d42adb5/source/src/autojev/model.py)
has a separate 8,192-token default branch limit, and its
[server](https://huggingface.co/perplexity-ai/pplx-decider-v1.1-27b/blob/6195aa55a72ae21e503c8a60198f7b390d42adb5/source/src/autojev/server.py)
adds repeated-state token counts; those mechanics cannot establish the
hosted request-wide guarantee. Local serving would require its own isolated
runtime, source/weight/tokenizer hashes, license, loopback transport, input
admission and actual Mac receipts. See [local serving](local_serving.md).
