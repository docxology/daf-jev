# Hosted expansion: fixed obligations and admission

The expansion is a **non-executable plan**, with no new inference results. It
retains the original `first-authorized-hosted-usd25` allocation and its USD 25
total ceiling. The earlier Mercury validation probe returned HTTP 404 without
reported billing or a retained response body. That charge remains unknown;
numeric ledger totals of zero do not establish that it was free. All new
admission remains blocked. The [recorded hosted summary](../output/reports/hosted-pilot-20261008/summary.json)
and its original source identity remain separate from this proposal.

The [offline generator](../scripts/prepare_hosted_expansion.py) creates the
distinct `dafjev.hosted-expansion-obligation/1` format. It never opens a client,
reads credentials, sends a request, reconciles billing or creates a RunStore.
Do not pass this obligation projection to `benchmark run`. The current ledger
accounts one RunStore; a fresh store's empty ledger does not import an older
charge. Any future executor needs a reviewed shared-allocation guard that binds
the prior manifest, journal/head and billing evidence, permits only one admitted
executor, and refuses the retained unknown. A new plan cannot create another
USD 25 budget.

## Cohort and selection

The full cohort uses the exact retained packed inputs, complete vocabularies,
independent targets, split/group identities and question order. No option list
is reduced to fit an adapter. Every declared arm retains its complete planned
denominator, including unsupported, unbounded, failed and unattempted work.

| Evaluation view | Validation rows | Test rows | Test input groups |
| --- | ---: | ---: | ---: |
| BANKING77 fold 0 and official test | 2,001 | 3,080 | 3,079 |
| CLINC150 plus official OOS | 3,100 | 5,500 | 5,500 |
| Wine Quality grouped validation/test | 1,299 | 1,300 | 1,064 |
| Four synthetic V3 suites, each | 30 | 30 | 30 |
| Matched categorical order controls | 21 | 21 | 7 |
| BANKING77 selection folds 1–4 combined | 8,002 | 0 | — |

CLINC's official test contains 1,000 OOS examples. All five BANKING77 validation
views cover its 10,003 original training rows exactly once. Fixed remote
weights receive these validation requests without fitting on the other folds.
Any threshold, model or routing-policy selection must use validation outcomes
only; official test results are scored separately. That selection has not run.
Historical official-test exposure remains disclosed, so these are not newly
untouched holdouts. Canonical results and label-dependent leakage sensitivity
must remain separately identified.

Each arm has 24,564 primary quality cells, 12 validation capability probes,
500 additional warm cells and one graphical workflow: **25,077 planned cells**.
The freshly captured catalog has 16 entries. The declared Jev alias is
deduplicated under the executable metadata comparison; adding the pinned Qwen
chat comparator gives 16 arms and **401,232 planned cells**. This inventory
supersedes the older 15-arm projection only for future obligations; it does not
replace any old manifest or observation.

Timing uses 100 shared ordinary test examples overall and five additional
identical-input repetitions. Their retained pack hash is
`97a1865544f4d68d8daca638c64ae22e7257c975df06f371f6a5e982d31f0c4e`.
Matched controls and validation-fold-only views are excluded from timing. The
selector is label-free conditional on its frozen input pools; upstream grouped
stratification is part of the declared corpus protocol. Warm failures retain
their planned slots and are not replaced.

The 42 matched physical rows represent 14 semantic groups across validation
and test. These controls vary ordered prompt and schema together; they do not
isolate a prompt-position causal effect. Wine comparisons use raw bin-index
MAE/RMSE as the common scalar axis. Genuine native probability argmax-bin
accuracy remains a separate extraction axis. Generated scalars do not acquire
invented distributions, and probability provenance does not establish a
calibrated probability or Bayesian posterior interpretation.

## Tariffs and capability evidence

OpenRouter documents `POST /api/alpha/decisions` with typed Noul, Choice and
Score questions, state and provider routing. Its schema describes response
usage but does not establish an aggregate billable-input bound across state,
questions and options. Model context metadata alone therefore does not admit
positive-priced native requests. [Decisions API reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request).

| Tariff-admissible candidate | Current per-attempt reservation | Static applicable non-graph cells | Evidence limit |
| --- | ---: | ---: | --- |
| Mercury Decide `:free` | USD 0 | 25,076 | Earlier probe failed; success and full-input consumption unverified |
| Respan Span-01 Lite, each declared tier | USD 0 | 136 | Noul only; catalog context is unknown (`0`), not zero supported context |
| Together Tev1 4B | USD 0.001376256 | 305 | Adapter supports Choice with at most 24 options; BANK/CLINC remain unsupported |
| Qwen3.5-9B chat, `darkbloom/fp4` | USD 0.02103808 | 25,076 | Generative comparator; structured response and actual billing still unverified |

The other 11 profiles retain unavailable liability rather than a fabricated
token bound. Catalog capabilities are candidates, not empirical success.
Aliases/tiers are not automatically independent models. A single selected
validation probe per dataset cannot establish maximum context, option count,
batching, no-truncation behavior or calibration.

Qwen's captured endpoint rates are USD 0.08 per million prompt tokens and USD
0.13 per million completion tokens. Its current reservation uses the entire
262,144-token context and a 512-token output ceiling. Tev uses 32,768 context
tokens, an eight-token output ceiling and USD 0.042 per million prompt tokens.
The provider and actual sent `max_price`, disabled fallback and required
parameters are frozen. Those ceilings filter provider prices; they are not
actual charges. [Provider routing and price ceilings](https://openrouter.ai/docs/guides/routing/provider-selection).

Serial/dynamically reserved execution can declare the full cohort and stop
before further admission when the shared balance is exhausted. It does not
require reserving the sum of every possible future request at once. For scale,
Qwen's full non-graph one-attempt ceiling is USD 527.55089408, or twice that if
every cell takes two attempts. These are underwriting ceilings, not cost
forecasts. Ignoring the unresolved prior charge, USD 25 could underwrite at
most 1,188 Qwen attempts at that maximum, or 594 two-attempt cells. Actual
progress may be larger if reported charges are lower; completion is not
guaranteed. Concurrency four increases simultaneous reservation and changes
latency conditions, so timing comparisons must declare that load.

Exact tokenizer files/chat templates and provider accounting transformations
are not identified by catalog tokenizer-family names. An offline token count
cannot silently replace the conservative input bound. A smaller bound needs
an exact pinned contract, full-question/schema/state audit, and adversarial
no-truncation checks. Clef's official guide documents silent truncation of
state text after roughly 2,000 tokens on Workers AI; its advertised context
does not establish complete input consumption. [Clef limits](https://openrouter.ai/docs/guides/community/multimodal-decisions).

Free variants have conditional account quotas, described as 20 requests per
minute and 50 or 1,000 per day depending on purchased-credit history, with
possible endpoint/account exemptions. The applicable account counters and
provider capacity remain unverified; a zero tariff does not guarantee a
same-day full study. [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits).

## Billing unblock evidence

Successful complete responses expose usage and reported account cost. The
authenticated generation-metadata endpoint can return total cost and request
identity when a generation ID is known. The original failed probe retained no
such ID. Aggregated key/day/model activity corroborates spending, but cannot
alone attribute an unretained individual response or prove its absence from a
provider invoice. Management-key analytics and dashboard exports are separate
authorized read surfaces; they grant no inference or reconciliation authority.
[Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting),
[generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation),
[activity export](https://openrouter.ai/docs/cookbook/administration/activity-export).

A future admission review must bind exact billing evidence or an independently
defensible liability bound for the original unknown attempt. A chosen reserve
does not establish that bound. The evidence must bind the single allocation,
all concurrent reservations, current
source/Git identity, frozen endpoint tariffs and the new cohort. Preserve the
old unknown receipt and body omission. Neither a new key, a new run directory,
a later public GET nor a catalogue zero price resolves that receipt.

## Offline reproduction

Prepare the [full-study inputs](full_study.md) first. Supply the frozen catalog
wrapper (`dafjev.model-catalog/1`), Qwen endpoint JSON, prepared dataset fragment
and recorded hosted summary with their exact SHA-256 values:

```bash
uv run python scripts/prepare_hosted_expansion.py \
  --catalog INPUTS/catalog.json --catalog-sha256 CATALOG_SHA256 \
  --endpoints INPUTS/qwen-endpoints.json --endpoints-sha256 ENDPOINTS_SHA256 \
  --fragment INPUTS/datasets.fragment.json --fragment-sha256 FRAGMENT_SHA256 \
  --prior-summary output/reports/hosted-pilot-20261008/summary.json \
  --prior-summary-sha256 19189e91902469e9e3de3f62119c26cec20e923983fad03b75e3f8ef0a19d524 \
  --out-dir NEW_OUTPUT_DIRECTORY --figures
```

The raw corpus remains a separately acquired/local input archive. The output
binds each prepared input SHA and exact sorted cell-ID digests by phase, while
retaining only IDs/counts/settings in the public plan. Missing, changed,
symlinked, malformed or differently sampled inputs fail closed. A symlinked
output ancestor is rejected before creating any output artifact. The source
and generator bytes are checked before and after reduction. Reproduction
creates a new directory and does not overwrite old evidence. The admission
matrix is a static plan visualization; it contains no inference measurements.
The optional `--figures` flag requires `uv sync --extra figures` and emits
`admission-matrix.json`, `.svg`, `.pdf` and `.png` beside `plan.json`. The fixed
figure metadata date identifies this projection edition, not an inference or
measurement time. Source metadata distinguishes committed bytes from any dirty
working tree; the release projection is generated only after its source commit.
Rendering resets plotting defaults in a scoped context, preserves caller
settings, and fixes image row order; ambient themes cannot change matrix bytes.
