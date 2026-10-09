# Local serving and Mac study execution

Local serving belongs to a separate runtime environment. Keep daf-jev's core
environment for orchestration and analysis, and install each model's serving
dependencies in its own pinned checkout. Downloading weights, importing a
package, server readiness, capability probes and labeled evaluation are distinct
steps. Read [backend contracts](providers.md), [the experiment protocol](decision_benchmarking.md)
and [evidence custody](reproducibility.md) alongside this guide.

[Perplexity native preparation](perplexity_native.md) concerns a hosted API
contract. Its public local checkpoint has a separate 8,192-token branch limit
and repeated-state accounting; no local Perplexity Mac profile is accepted
here, and hosted bounds must not be transferred to an unverified local server.

## Initial profiles

The initial target machine is an Apple M5 with 16 GB of unified memory. These
profiles are fixed comparators, rather than models selected after test scoring.
The exact executable profile must retain the weights, tokenizer, runtime and
launch inventory; the table is a setup reference and does not establish a
completed comparative study.

| Profile | Runtime and extraction | Frozen setup choice | Material boundary |
| --- | --- | --- | --- |
| Jeff / GLiFormer | MPS, float32, eager attention; native System One answers | server `34b32f99a727c47b679adde33f4702a001e02979`; weights `d0a4e53d09cebe6bc963dd9be319d4279084bb2d` | 64 options; full 77/151-option tasks unsupported; Mac pilot admits at most 512 full input tokens |
| Kev 0.8B | MLX, bf16; native decision head | server `5e42a7a03f28134853dd3ff77461457e921e5ec1`; adapter `bf75a6a8848ea6960ff2ed108d9ed44c2941174f`; Qwen base `dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68` | state truncation disabled; complete serving-encoder input preflight required |
| Ollama Qwen3.5 0.8B | Ollama 0.40.0 MLX, mxfp8; generated typed values | immutable model manifest and tensor/tokenizer hashes | actual context 8,192; 128 output tokens reserved; no invented beliefs/confidence |
| Ollama Qwen3.5 4B | Ollama 0.40.0 MLX, nvfp4; generated typed values | immutable model manifest and tensor/tokenizer hashes | same actual context/output admission rule; one resident model at a time |

Jeff's 512-token bound is a predeclared hardware admission choice for eager
attention on this Mac. It is separate from the checkpoint's advertised context
and the processor's truncation cutoff. Do not relabel the model's context as 512,
or shorten a request until it passes. Keep complete option vocabularies and
instructions. A rejected input remains a planned unsupported cell with its
measured length, bound and reason.

The native launch recipes and source references are in
[providers.md](providers.md#local-open-source-execution). Freeze Python and
package versions, device, precision, attention implementation, compilation,
warm-up settings, temperature, option limits and effective launch arguments.
Disable implicit credential use during offline local serving. Verify that the
server stays on loopback and does not delegate inference remotely.

## Ollama serving

Use a dedicated model directory and explicit loopback binding. The following
example runs in the serving environment; substitute an owned directory:

```bash
OLLAMA_HOST=127.0.0.1:11434 \
OLLAMA_MODELS=/absolute/path/to/owned-model-directory \
OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=8192 ollama serve
```

Acquire the two tags explicitly, then freeze their manifests, every tensor and
tokenizer/config file, licenses, executable SHA-256 and runtime package bytes.
A tag alone is mutable. Record the actual runner and quantization from retained
artifacts; do not assume a downloaded tag uses a particular GGUF or MLX path.
Ollama documents this interface in its
[OpenAI compatibility reference](https://docs.ollama.com/api/openai-compatibility).

For the MLX path, verify that the serving distribution contains
`libollama_xgrammar.dylib` beside the loaded MLX library. The inspected
[grammar initialization](https://github.com/ollama/ollama/blob/0d0720e51fb2fd9aa58781c3d720c06d720c2e7b/mlxrunner/grammar.go)
rejects structured requests with HTTP 501 when that subsystem is unavailable.
A matching version string and successful model load do not establish constrained
output support. Keep the failed capability receipts; do not remove the schema to
turn an unsupported arm into an accepted one.

If the installed distribution lacks a required library, prepare a complete
isolated serving distribution from an explicit release asset. Verify its retained
release metadata, archive checksum, executable and library inventory before a
new profile is frozen. Keep the previous runtime and receipts intact. Replacing
a runtime requires new admission proofs and a new study; it cannot repair an
already stopped study retrospectively.

Use `mode: chat` with the complete strict per-request typed schema and frozen
`options: {temperature: 0, max_tokens: 128, seed: 20261007,
reasoning_effort: none}`. Generated score values remain scalars, including
fractional values. Their common comparison with native Score outputs is ordinal
MAE/RMSE; classification extracted from a native probability row has different
semantics and must be disclosed separately.

Before each pass, verify that `/api/ps` is empty. Load exactly the requested
model, then verify its actual resident digest and context length. Record the
load request, response, elapsed interval and serving/child process identities.
Verify unloaded state before admitting another profile. An API success without
the requested digest/context is a failed setup, not accepted model execution.

## Complete-input admission

Character limits are insufficient to establish tokenizer or context limits.
Preflight the complete server input: state, all instructions and options,
special/template tokens and any prompt-injected schema. Keep order-sensitive
wire identities as well as canonical request hashes. Freeze the audit helper,
tokenizer/template/runtime identities and the rule before quality predictions.

For Jeff and Kev, the local pilot uses their pinned serving processor/encoder
without loading model weights to determine complete input lengths. For the
inspected Ollama MLX path, the strict schema is a separate output grammar and
the full rendered chat input is bounded conservatively using its byte-level BPE
and NFC normalization semantics. The allowance includes the output reserve.
This is an admission upper bound, not an exact serving token count or proof that
a downloaded binary was built from the inspected source. Retain those limits.
If the path, rendering or normalization cannot be bounded, mark the cell
unsupported before inference.
The inspected implementation is Ollama commit
`0d0720e51fb2fd9aa58781c3d720c06d720c2e7b`: its
[Qwen renderer](https://github.com/ollama/ollama/blob/0d0720e51fb2fd9aa58781c3d720c06d720c2e7b/model/renderers/qwen35.go),
[MLX grammar transport](https://github.com/ollama/ollama/blob/0d0720e51fb2fd9aa58781c3d720c06d720c2e7b/mlxrunner/client.go)
and [tokenizer](https://github.com/ollama/ollama/blob/0d0720e51fb2fd9aa58781c3d720c06d720c2e7b/mlxrunner/tokenizer/tokenizer_encode.go)
support that declared admission rule.

Graphical workflows need all possible child requests preflighted, including CPT
chunks, structure questions and evidence-conditioned re-asks. A status flag on
an audit is insufficient: compare actual body and wire-order hashes against the
frozen packet inventory. New state, options, questions or rendering require a
new declared experiment.

## Counterbalanced execution and resources

Freeze a seeded permutation of the explicitly selected, distinct profiles before
prediction. The initial comparison has four profiles; an admitted continuation
can select a smaller subset without replacing a model or resetting its allowance.
Run one current-study primary quality pass per profile, then five warm rounds
with the order shifted cyclically. Each resident pass closes its model/process
custody and owned cleanup before another profile loads. Graphical controls have
separate phase identities.
The [pass selector](decision_benchmarking.md#frozen-plan) preserves logical sample
IDs; it does not independently verify a prior primary run.

A study coordinator must bind every warm pass to the unchanged primary
manifest, journal/head, report, source/input/model identity and terminal outcomes.
Propagate primary unsupported outcomes. Missing or unresolved primary work
cannot become an admitted warm observation. Keep the primary and repetitions
separate for accuracy, and combine them by sample/question identity for stability.

The shared two-hour allowance per profile includes preflight, hashing/setup,
startup, every reload, calls/retries, graphical work, custody and teardown.
Separate child-run limits cannot multiply that allowance. Record the measured
components and retain unfinished passes. Local-to-local replay cannot establish
live latency without model-switch costs.

Record sampled runner/server peak RSS, wall intervals, free-disk observations
and polling resolution. RSS does not capture all Metal/unified-memory allocation.
The private pilot guardian samples its directly owned wrapper and verified
descendants, covering native-server startup and cleanup. The separately running
Ollama daemon is outside that ancestry: its startup/teardown memory peak remains
unavailable, while the SDK samples its serving PID during execution. Do not
present that execution-only observation as a whole-pass memory peak.
An OS physical-footprint observation may complement RSS when compressed or
unified memory makes RSS misleading. Retain the original tool output, exact
owned PID and process birth identity, observation interval and metric definition.
An OS-reported historical peak is a separate metric from continuously sampled
RSS or a Metal allocator peak. Profiling can affect concurrent inference;
disclose its overlap and keep it outside a warm-latency pass.
On macOS, Python's command-line launcher can start an application executable
and rewrite `argv[0]`. Retain the frozen launch file and arguments separately
from the actual OS executable, hash and observed command line. Verify process
birth, parent and the complete remaining arguments before profiling. An actual
executable first hashed during a measurement is evidence for that observation
interval; it cannot establish custody over earlier calls.
Use an owned process guard through startup and execution; the pilot's storage
boundary is 1 GiB free, checked every second. The guard sends at most one SIGINT
to its directly owned runner after checking PID, creation time and parent
identity. It does not kill unrelated processes or declare cleanup complete after
a timeout. An unclosed lifecycle, resource boundary, changed source/model bytes
or journal/head mismatch stops further study admission and preserves evidence.

### Guard failure semantics

The reviewed private guard recipes obtain direct-child ownership before fallible
path, clock or receipt validation. Receipt collisions and write failures stay
inside the cleanup-protected interval: they cannot bypass an exact-owned-child
cleanup attempt. Retain the original error alongside the measured exit receipt
where storage permits. If that receipt cannot be written, retain the available
diagnostic separately and keep durable closure unknown.

Only identity-verified live descendants contribute to sampled RSS. Terminal
exclusions record unavailable birth or RSS explicitly; do not substitute zero.
`ZombieProcess` is a subclass of `NoSuchProcess`, so exceptional zombie
observations must be handled before an absence branch. Reaping the direct child
does not close a known unresolved descendant. End the measured cleanup interval
after those final checks.

A malformed prior signal counter remains unknown and does not justify an
additional signal. Attempt a cooperative wait independently of counter
validation, retain a JSON-safe diagnostic, and preserve the hold. A valid prior
delivery prevents a second SIGINT. A nonterminating child can leave that wait
unbounded; the guard has no forced finite reap guarantee. Small real owned-process
fixtures cover these failure paths without establishing runtime preparation,
model startup or provider execution.

## Continuing within an existing allowance

An interrupted study keeps its original manifest, journal/head, unclosed window,
attempt receipts and unresolved cells. A fresh study cannot repair those records
or borrow its predecessor's primary predictions as repeats under changed source
or request semantics. Derive any remaining allowance from exact, independently
reviewed closed clock and process-cleanup receipts. Preserve prior setup and
execution charges; the new study adds measured required preparation, load,
reload, calls and cleanup to the same cumulative allowance. An unknown or
exhausted profile stays excluded even when another profile has a known balance.

The retained local coordinator is a private execution recipe, rather than an
installed SDK command or a portable serving system. Its operational contract is
to freeze the ordered dataset inputs, complete quality denominators, exact global
100-example timing pack, current source and request-builder hashes, model/runtime
inventory, input proofs, profile subset, cyclic schedule and existing clocks.
Training rows may remain in a prepared input; only its declared validation/test
rows become quality requests. Complete matched control groups remain separate
from timing selection. Newly changed source or request rendering invalidates
older input proofs before startup, even if the model weights are unchanged.

Resource admission precedes large input/runtime preflight. The continuation's
CPU-only preparation policy requires at least 4 GiB available RAM and 1 GiB free
disk before admitting an audit child, then samples the identity-verified child
and descendants every second against a 1 GiB aggregate RSS cap. A boundary
retains the preparation evidence and measured charge and holds later admission.
These are conservative operational choices for this machine, not SDK/model
context limits or evidence of a true memory peak. The guard sends at most one
SIGINT to its directly owned child; it does not guarantee a finite reap interval.
Unknown cleanup remains a hold.

One retained CPU-only native continuation attempt stopped during runtime
inventory when a descendant RSS observation became unavailable with
`ZombieProcess`. The outer guardian sent its single owned-child SIGINT; the
preparer exited, and independent checks later found the known owned processes
absent. No sampled RSS or disk cap exceedance was established. This observation
does not identify an OOM, a model failure or an unsafe model load.

Inventory output existed, but the inner guardian had no terminal exit receipt.
Tokenizer audits, the second native profile and a new study were not reached;
no model server was started and no prediction was requested. Retained closed
intervals support minimum elapsed charges only, not a current admissible balance.
The missing window stays unknown. A future attempt requires separately reviewed
sampling and clock reconciliation before fresh preparation can be admitted;
process absence alone does not authorize a retry or erase the charged attempt.

A conservative reconciliation may disclose overlapping elapsed time as padding,
but arithmetic agreement alone does not make a balance usable. Bind the original
receipts and unknown windows, review the allocation and its strict carry parser,
and admit it separately before fresh work. Do not relabel conservative padding
as an exact measured interval or use a source repair to close earlier history.

Current software verification describes only the source, tests and configuration
bound by its [verification evidence](reproducibility.md#retained-verification-for-exact-offline-regeneration).
A repaired guard or later SDK gate does not upgrade historical model receipts.
Changed source or runtime bytes need fresh custody and input proofs; model
admission and actual execution remain separate.

Model startup requires a separate review of its reserve against the retained
runtime and memory evidence. A downloaded model, a passing processor audit or
available disk above the guardian floor does not establish that its load is safe.
If resources or time do not admit the full frozen matrix, retain all unsupported,
failed, unresolved and unattempted cells and describe the result as partial.
Never shrink option vocabularies, omit difficult rows or increase an allowance
to turn that partial result into a completed study.

## Hosted-client monitoring boundary

The serial hosted pilot protocol freezes `hosted_concurrency: 1` and uses the
same shared USD 25 allocation, including probes, failed attempts and retries.
This differs from the planner and example recipe's `hosted_concurrency: 4`
default. Read the selected manifest for the actual setting; a replacement plan
does not create another allocation or authorize concurrent consumption of the
same budget. Follow the [attempt and spend contract](decision_benchmarking.md#attempt-lifecycle-and-spend)
for reservations, reported charges and unresolved liability.

The separate hosted-client guard declares at least 2 GiB available RAM and
1.25 GiB free disk before launch, including a 256 MiB incremental disk estimate.
The dispatcher must check that startup reserve before creating its owned child;
the monitor-only helper does not perform startup admission. During monitoring,
it samples verified-live child and descendant RSS against a 1 GiB cap and free
disk against a 1 GiB floor every second. These sampled bounds are operational
policies, not continuous resource guarantees. The helper permits `deadline=None`
because it does not implement native allowances or carry.

Passing its owned-process fixtures neither activates a hosted plan nor grants
credentials, provider capability acceptance or additional spending. Actual
hosted requests require the independently admitted manifest, its shared ledger
and retained attempt receipts. Keep hosted client resources and billing separate
from local model startup, runtime custody and cumulative native clocks.

Local monetary expense requires supplied energy/rental/amortization rates.
Absent rates stay unknown. Zero reported API billing is a separate fact.
Standalone reports select exact run evidence; follow
[reproducibility.md](reproducibility.md) before rendering or transferring it.
