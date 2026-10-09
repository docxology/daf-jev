# Decision backends and provider orchestration

The provider registry and the benchmark backend interface serve different
purposes. The registry preserves the existing System One client API and its six
stable provider keys. The benchmark interface makes endpoint, model, output
semantics, capability limits, request settings, and accounting explicit for each
experimental arm. See [the architecture contract](ARCHITECTURE.md) for signatures
and [the benchmark protocol](decision_benchmarking.md) for execution.

## Two integration surfaces

| Surface | Input and output | Ownership | Appropriate use |
| --- | --- | --- | --- |
| `JevClient` / `AsyncJevClient` | `ask(state, questions)` → typed `SystemOneResponse` | caller normally closes; legacy `Evaluator` closes its async client at batch end | existing System One applications, CLI and MCP |
| `DecisionBackend` / `AsyncDecisionBackend` | `predict(DecisionRequest)` → `DecisionResult` | caller closes; runner closes the adapters it creates | explicit cross-model benchmarking and adapters |
| Pure policies and statistics | predictions, labeled rows or posterior sidecars → decisions/statistics | no model session | routing, calibration, replay and inference |

Registering a provider proves that configuration and dispatch exist. It does not
prove a server is available, that weights were loaded, or that an endpoint
supports the whole question vocabulary. A backend profile's `capabilities.evidence`
must distinguish declarations (`declared_unverified`), public catalog discovery
(`catalog_only`), and independently recorded runtime probes. Do not silently
promote a declaration after a successful import.

## Existing System One registry

`daf-jev providers` is keyless and performs no network call. The stable keys are
`jev`, `jeff`, `kev`, `localjev`, `openthai-systemone`, and `openrouter`. Their
default URLs, model aliases, credential precedence and historical caveats are
listed in [the README](../README.md#providers). The old `models` command expects
the TypeSafe listing shape; OpenRouter catalog discovery uses the separate,
explicit snapshot operation described below.

The legacy response dataclasses retain token usage and the TypeSafe request ID.
They do not constitute a dollar ledger for arbitrary providers. The benchmark
adapters retain provider/model resolution, response IDs and reported USD cost in
`CallReceipt`; use those receipts for hosted cost comparisons.
Its `request_hash` is a semantic canonical JSON SHA-256, not captured transport
bytes or standalone wire-order proof. Native permutation controls also require
ordered corpus/question hashes, cell/example identities and source custody.

## Output contracts

| Adapter mode | Required server contract | Probability evidence | Limitations |
| --- | --- | --- | --- |
| `systemone` | native `state`, named `questions`, and typed `answers` | provider distributions; declared rounding retained | complete requested IDs, types and vocabulary are validated |
| `chat` | OpenAI-style chat completion containing the requested JSON answer values | generated values only | label decisions have no invented probability vector or confidence; a generated noul scalar remains generated |
| `letter` | one standalone option letter mapped to the supplied choice label | label only | choice only, at most 24 options; explanations, unknown letters and incomplete completions fail |
| prior / classifier | deterministic local `predict` implementation | training-prior or classifier probabilities | fitted on the training split only; training and inference are separate measurements |

The generic chat adapter builds a complete per-request strict JSON schema from
its frozen typed questions. Every requested ID and `value` field is required,
extra fields are disallowed, choice values use the complete option-key enum,
noul values are numeric in `[0,1]`, and score values are numeric in
`[0, number_of_levels - 1]`. The request uses `response_format: json_schema`
with `strict: true` by default. A profile may explicitly override
`response_format`; that override is frozen with its effective settings and
does not bypass response validation. The hosted Qwen recipe uses the default
schema rather than overriding it with `json_object`.

This constrains answer structure; it does not turn generated text into
calibrated probabilities. The letter adapter cannot evaluate a
77-class task by dropping options until it fits. Unsupported cells remain visible
in the report. Any reduced-label task requires its own declared dataset and
cannot inherit the full-task name or accuracy claim.

Native System One rows commonly declare two decimal places. Parsing checks
finite values in `[0,1]`, the complete vocabulary, and row mass using the strict
`1e-6` budget plus half a rounding quantum per entry when every entry matches the
declared precision. The original probabilities are retained; they are never
renormalized. Full-precision classifier rows use the strict budget. Confidence
semantics travel with every prediction: concentration or raw entropy is not
empirical correctness probability. Domain calibration needs independent labels.

### Probability meaning and confidence

Record origin, meaning, rounding and validation evidence separately. The
interface's `probability_source` describes provenance; the separate appended
`probability_semantics` field on capabilities and predictions declares meaning.
It defaults to `None` for generic native adapters. A missing meaning stays
unknown. Schema validity, normalization by a serving implementation and native
wire compatibility cannot supply that evidence.

Report summaries retain declared meanings and unknown distribution counts.
Built-in references declare `uniform_reference_distribution`,
`training_label_frequency`, `estimated_class_probability` or
`analytical_conditional_probability` as appropriate. These names describe an
estimator or analytical construction; they do not certify held-out calibration.

| Output | Supported interpretation | Required additional evidence |
| --- | --- | --- |
| Unspecified native distribution | provider-defined numerical row | documented meaning, domain applicability and labeled calibration |
| Pinned Jeff distribution | independent sigmoid compatibility scores, temperature-transformed and normalized by its decoder | evidence for class-probability or conditional-factor interpretation |
| Pinned Kev distribution | temperature-scaled discriminative pointer-head class estimates | held-out task calibration and applicability to a stated conditional population |
| Training prior | smoothed empirical training-label frequencies | relevance of the training population to the evaluated population |
| Fitted classifier | estimated class probabilities under the fitted estimator | held-out calibration and distribution-transfer evidence |
| Analytical Bayes control | conditional probability under the disclosed generating model | validity of that model for any external population |
| Generated noul scalar | generated self-reported numerical judgment | an independently justified probability estimator and validation |
| Generated choice/score value | label or level only | no probability vector or confidence is supplied |

Jeff's `normalize` explicitly describes score renormalization rather than a
calibrated posterior. Its `score` uses the raw distribution while its reported
row is temperature-transformed. Kev's choice confidence is chance-adjusted
peakedness; its score confidence measures dispersion around the mode. These
statistics are distinct from P(correct). Source-backed definitions explain the
values without proving task calibration. See the pinned
[Jeff decoder](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/src/jeff/core/answers.py),
[Kev model](https://github.com/jaredpalmer/kev/blob/5e42a7a03f28134853dd3ff77461457e921e5ec1/kev/model.py)
and [Kev answer conversion](https://github.com/jaredpalmer/kev/blob/5e42a7a03f28134853dd3ff77461457e921e5ec1/kev/api.py).

The retained graphical experiment checks supplied numeric rows and provenance;
origin alone does not establish conditional-belief semantics. Its Brier and
posterior comparisons remain descriptive model-judgment comparisons against a
disclosed synthetic reference. Stronger factor, posterior or causal claims need
an explicitly justified interpretation and independent evidence.

## Local open-source execution

The package connects to an explicitly supplied loopback HTTP endpoint; it does
not install model weights or launch a serving runtime on import. Upstream
projects provide different servers and model heads:

- [jeff](https://github.com/logan-markewich/jeff) implements a GLiFormer-based
  System One server.
- [kev](https://github.com/jaredpalmer/kev) implements a compact decision model
  with a native decision head.
- [Tev1](https://github.com/togethercomputer/tev1) provides an experimental
  open-weight decision model and training recipe. Its upstream example returns
  an option letter through a chat completion; logprobs are model preferences,
  not calibrated confidence. This is a `letter` arm, not a native probability
  arm. [Upstream example](https://github.com/togethercomputer/tev1/blob/main/examples/decide.py)
  (reviewed 2026-10-07).

A generic local chat comparator can use a separately installed loopback Ollama
server and a pinned model artifact, with `mode: chat`. For the Boolean-thinking
Qwen profile, freeze `options: {temperature: 0, max_tokens: 512,
reasoning_effort: none}` to request disabled thinking through its compatibility
interface. Record `/api/show` supported thinking values/defaults: named-level
models can resolve unsupported values to their default. Retain the exact model
manifest, blob hashes and runtime identity;
a model tag alone does not establish immutable weights. Ollama documents chat
JSON-schema response formats and reasoning controls in its
[OpenAI compatibility reference](https://docs.ollama.com/api/openai-compatibility)
(reviewed 2026-10-07). This is a local generated-value comparator, not native
System One beliefs; its availability needs an actual loopback run receipt.

Before recording local model acceptance, retain a profile with the upstream
repository commit, weight revision and file hashes, weight and code licenses,
tokenizer revision, serving package versions, precision/quantization, effective
settings, option/context limits and hardware identity. Pin code and weights
separately: an MIT server license does not establish a model-weight license.
Record setup/load time and inference time separately. A loopback connection
alone says nothing about whether the server delegates to a remote model; inspect
the serving configuration and retain its network boundary as evidence.

Local verification progresses through: install and weight integrity → server
readiness → a complete-vocabulary capability probe → an actual prepared-dataset
run. A startup failure or unsupported hardware is a reported outcome. Adapter
tests against a local HTTP fixture establish transport behavior; they are not
model execution evidence. Current model acceptance must be read from an exact
run receipt, not inferred from the examples or the September historical results.

The reviewed setup recipes pin
[Jeff server commit `34b32f99a727c47b679adde33f4702a001e02979`](https://github.com/logan-markewich/jeff/tree/34b32f99a727c47b679adde33f4702a001e02979)
(Python 3.12) and
[Kev server commit `5e42a7a03f28134853dd3ff77461457e921e5ec1`](https://github.com/jaredpalmer/kev/tree/5e42a7a03f28134853dd3ff77461457e921e5ec1)
(Python 3.13). These are source
identities for the setup, not accepted accuracy or serving-performance results.
Use isolated environments and one resident model at a time on shared local
accelerators. Jeff supports an explicit MPS device and eager attention; the
small Kev profile uses the 0.8B `v1.0` checkpoint and MLX. Resolve a tag to a
commit and retain weight/tokenizer SHA-256 before inference; a mutable tag alone
is insufficient evidence. Commands below run inside each pinned upstream checkout:

```bash
# Jeff: install, then acquire an independently selected exact weight revision.
uv sync --locked --python 3.12
uv run hf download knowledgator/gliformer-large-v1 --revision WEIGHTS_REVISION \
  --local-dir models/gliformer-large-v1
JEFF_HOST=127.0.0.1 JEFF_PORT=8000 JEFF_DEVICE=mps JEFF_ATTN=eager \
  JEFF_MODEL=models/gliformer-large-v1 uv run jeff

# Kev: the small checkpoint; resolve v1.0 and its pinned base before acceptance.
uv sync --locked --extra serve --python 3.13
KEV_BACKEND=mlx uv run --extra serve python -m kev.serve \
  --run jaredpalmer/kev-0.8b@v1.0 --host 127.0.0.1 --port 8009
```

Supply a real resolved revision instead of `WEIGHTS_REVISION`. Inspect the
checkout's current serving settings rather than assuming a global installation.
Local inference can be verified through the explicit native backend with
`probability_rounding_digits=4` for these pinned server revisions, which serialize
four decimal places. Jeff's score expectation uses its untempered row while the
reported distribution uses temperature scaling, so do not assert that its score
equals the expectation of that reported row. Their confidence formulas describe
distribution concentration/dispersion and still require domain validation.
See [Jeff decoding](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/src/jeff/core/answers.py)
and [Kev decoding](https://github.com/jaredpalmer/kev/blob/5e42a7a03f28134853dd3ff77461457e921e5ec1/kev/api.py)
(source reviewed 2026-10-07).

## OpenRouter discovery and execution

The user-facing [decisions catalog](https://openrouter.ai/models?output_modalities=decisions)
is a discovery view. `snapshot_catalog(path)` explicitly fetches
`https://openrouter.ai/api/v1/models?output_modalities=decisions` and saves the
raw payload, source URL and UTC fetch time under `dafjev.model-catalog/1`.
No inference call occurs during discovery, dataset preparation, or run planning.
OpenRouter documents the model listing and its metadata separately from
inference. [Models API](https://openrouter.ai/docs/api/api-reference/models/get-models)
(reviewed 2026-10-07).

OpenRouter's native interface is
`POST https://openrouter.ai/api/alpha/decisions`, with canonical model IDs such as
`typesafe/jev-1.13`. Its documented response includes resolved model/provider,
response ID and reported cost alongside the typed answers.
[Native decisions endpoint](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request),
[Jev guide](https://openrouter.ai/docs/guides/community/jev)
(reviewed 2026-10-07). The legacy `jev-latest` registry alias is not the default
identity for a new OpenRouter experiment.

`catalog_profiles(path)` derives candidate profiles from a saved catalog and
keeps capabilities at `catalog_only`. It deduplicates an explicit direct alias
only when its canonical target is present and pricing, context, modalities,
routing and parameter metadata agree. Different-price or different-contract
variants, unknown equivalence and cyclic aliases remain visible. Requested alias
IDs and their prices are retained for those variants. Native candidates use
the decisions endpoint; Tev candidates use the chat endpoint and letter mode.
The catalog's decision modality therefore does not imply one universal wire
contract. OpenRouter describes Tev1 as returning one option letter through chat
completions. [Tev1 model description](https://openrouter.ai/models?output_modalities=decisions)
(reviewed 2026-10-07). These conversion rules are implementation assumptions
requiring endpoint-specific probes; future models require review rather than
automatic family-name inference.

Freeze an explicit cohort with canonical model IDs, source catalog hash/date,
endpoint, routing settings, context limit, full option limits and pricing source.
Aliases such as `*-latest` remain useful interactively but are insufficient
alone for a reproducible model identity. Retain both requested and resolved
model/provider IDs when returned. Routing fallback must be explicit, because
changing the provider can change both performance and price. Paid benchmark
admission freezes the sent provider price ceilings and requires supported
parameters with provider fallback disabled; catalog minimum prices alone are
insufficient to bound a routed request.

Benchmark credentials resolve only from the profile's named process environment
variable (normally `OPENROUTER_API_KEY`). The benchmark runner does not load
`.env` or fall back to another provider's key. Profiles store the variable name,
never its value. HTTP adapters reject URL credentials, query strings and
fragments, disable environment proxies and redirects, and restrict hosted URLs
to HTTPS OpenRouter endpoints. Local URLs are restricted to loopback, and local benchmark adapters are
keyless: a hosted credential supplied to a local adapter is rejected.

## Cost and evidence gates

Each HTTP attempt emits a receipt, including failed HTTP responses and semantic
parse failures. A price snapshot supports a conservative pre-call liability;
the response's reported charge supports observed spend. Unknown charges retain
their reservation and stop further hosted admission. Unsupported pricing
surcharges or an unbounded output charge make an arm ineligible for automatic
paid admission until an adequate bound is defined.

Local cost is unknown unless hardware amortization, energy/rental rate and the
measurement interval are supplied. Zero hosted spend for a local comparator is
not zero computational cost. Token totals remain a separate metric. Successful
catalog fetches, local unit tests, replay reports, executed model runs, and
publication-ready scientific comparisons are separate acceptance gates.
