# Methodology: The Layered Architecture of a Composable Decision Toolkit {#sec:methodology}

{{PACKAGE_NAME}} is organized as a strict layering: an ergonomic surface (CLI, MCP server, scripts, benchmarks) on top of pure-logic composition, on top of primitives and wire types, on top of explicit transport and backend boundaries. The core native client and the additive benchmark adapters retain separate request lifecycles. [@fig:architecture] shows the module graph. The layering is enforced by convention: the composition and primitive modules import no I/O machinery, so every decision pattern is testable against constructed answers without a network stand-in. The ergonomic surface itself — CLI subcommands, MCP tools, an agent skill, and worked examples — is the subject of [@sec:integration_surfaces]; this section covers the layers those surfaces delegate to.

![Package layer diagram for {{PACKAGE_NAME}}, drawn from the module graph of `src/daf_jev/`. The application layer — the CLI (`src/daf_jev/cli.py`) and the thin orchestration scripts (`scripts/`, `benchmarks/`) — delegates downward to the logic layer, where `compose.py` (pure decision patterns) and `primitives.py` (typed question builders and the `QuestionSet` container) sit over the wire dataclasses of `_types.py`. `client.py` and `_http.py` implement the core native transport, with `_retry.py` providing the pure retry policy and `_errors.py` the typed exception hierarchy; `models.py` and `config.py` enter as side inputs, and `evaluate.py` is the batch harness. The key structural takeaway is the enforced dependency direction: composition and primitives import no I/O machinery, so every decision pattern is testable against constructed answers without a network stand-in. Boxes are named modules only; no measured values appear in this schematic.](../output/figures/architecture.png){#fig:architecture width=85%}

## Layered architecture

The layers, bottom-up:

- **Transport** (`_http.py`) — a minimal `Transport` protocol with a synchronous and an asynchronous `httpx` implementation. It knows nothing about decisions; it posts JSON to a path and returns the raw response.
- **Client** (`client.py`) — `JevClient` / `AsyncJevClient` resolve the API key from the environment (injected mapping, process environment, then a `.env` file, in that precedence order via `config.py`), build the request for a state plus a mapping of questions, apply the retry policy, and map HTTP status classes onto the typed exception hierarchy of `_errors.py`. The retry policy itself (`_retry.py`) is a *pure* function of the attempt number and an optional server-supplied retry hint — exponential backoff with a base, a cap, and jitter, with the hint winning when present — so its timing behavior is unit-testable without sleeping.
- **Wire types** (`_types.py`) — frozen dataclasses for the three question types and the three answer types, a strict parser that rejects unknown answer shapes, a usage record, and the top-level response object with cached per-type views (`nouls`, `choices`, `scores`).
- **Primitives** (`primitives.py`) — the ergonomic builders `noul()`, `choice()`, `score()` and the `QuestionSet` mapping container with additive composition (`add`, `merge`, `to_wire`). No I/O.
- **Composition** (`compose.py`) — pure functions over answers, described below. No I/O; network access happens only through a client injected by the caller for multi-call helpers.
- **Harness** (`evaluate.py`) — the batch `Evaluator`, described below.

## Typed primitives

![The three question primitives of the System One surface and the typed answer shapes {{PACKAGE_NAME}} parses them into, drawn as a schematic of the wire contract ([@sec:jev_model]). A `noul` question yields a declared yes/no probability; a `choice` question yields a selected label, a full probability distribution over the named options, and a scalar confidence; a `score` question yields a probability-weighted score over ordered levels together with the level legend, the level distribution, and a confidence. The takeaway is that the builders in `primitives.py` map one-to-one onto these shapes with strict, eager validation — score criteria must carry at least two ordered levels, choice criteria must be non-empty, and the answer-side parser rejects any payload outside the discriminated union — so downstream composition code can pattern-match on answers without defensive parsing. The diagram carries no measured data.](../output/figures/primitives_overview.png){#fig:primitives width=85%}

The builders in [@fig:primitives] map one-to-one onto the wire contract of [@sec:jev_model]. Validation is strict and eager: score criteria must carry at least two ordered levels, choice criteria must be non-empty, and the answer-side parser rejects unsupported types and malformed required answer fields. Builders validate requests, and the runtime parser validates received answers before downstream composition. This removes shape guessing without turning a valid answer into a correctness guarantee.

## Composable decision patterns

The composition layer implements the documented TypeSafe patterns as pure functions [@typesafe2026patterns]:

- **`composite_score(answer, weights=None)`** — the expected level index under the supplied distribution, optionally reweighted by finite caller-supplied weights with positive total weight and nonzero weighted mass. Negative weights are deliberately allowed but remove the bounded-index guarantee; reweighting is not a learned utility model. This turns an ordinal rating into a comparable scalar without a second model call.
- **`confidence_gate(answer, threshold, below)`** — returns the answer's primary value when its confidence meets the caller's threshold, and the `below` verdict otherwise. The threshold is owned by the calling code, never by the package.
- **`route(answer, handlers, min_confidence, fallback)`** — dispatches to the handler registered for a `choice` answer's label, gated on a minimum confidence with an optional fallback handler; `pick` fans the same dispatch across every answer in a mapping.

**Batching fan-out and the Evaluator.** Under the documented native parallel-question contract ([@sec:jev_model]), batching a fixed question set can amortize transport/state overhead within backend capacity. It does not by itself prove decision equivalence or minimum monetary cost. The `Evaluator` in `evaluate.py` inverts the axis: it holds the question set fixed and runs it over *many states*, concurrently — through a thread pool for the synchronous client or `asyncio` with a semaphore for the asynchronous client. Per-state failures never abort the batch; they are captured into the evaluation record alongside the answers and the measured latency, so one malformed state remains an explicit failure rather than discarding the whole batch. The historical benchmark scripts drive clients directly; the application Evaluator is a distinct convenience harness. Its default async batch lifecycle closes the client at batch end.

**Confidence-gated routing.** [@fig:confidence] illustrates the three-band policy that `confidence_gate` and `route` implement: answers whose confidence clears the upper band are automated, mid-band answers are routed to review, and answers below the lower band are escalated. The boundary markers in the figure are *example thresholds* — the semantics are the bands, not any particular cut points, which remain policy owned by the caller.

![Parametric illustration of confidence-gated routing as implemented by `confidence_gate()` and `route()` in `src/daf_jev/compose.py` ([@sec:methodology]). The horizontal axis is the model-reported confidence on the unit interval; the three horizontal bands assign an action per confidence region — automate above the upper boundary, route to review in the middle band, escalate below the lower boundary. The boundary markers are annotated as example thresholds: the semantics are the bands, not any particular cut points, and the actual thresholds remain policy owned by the caller. This figure is parametric and carries no measured data; [@sec:results] reports end-to-end latency and a self-agreement proxy; domain safety and correctness calibration require independent labeled validation.](../output/figures/confidence_bands.png){#fig:confidence width=80%}

## Design rulings

Four rulings shaped the codebase and are worth stating as contracts:

1. **Pure logic, injected I/O.** Everything under `compose.py`, `primitives.py`, `_types.py`, and `_retry.py` performs no I/O; network access uses explicit clients or backend adapters, with parameterized transport and lifecycle seams for deterministic tests.
2. **Real stand-ins, no mocks.** The test suite drives the real HTTP transport against a real local HTTP server fixture rather than patching client internals, so retry, timeout, and error-mapping behavior is exercised end to end.
3. **Pure retry policy.** The configured attempt, retry hint, cap and jitter determine a delay without sleeping; disabling jitter gives deterministic timing tests, and both native clients use the same policy.
4. **Snapshotted documentation.** The bundled documentation snapshot carries a manifest of per-page content hashes and a snapshot identifier, and a CLI subcommand re-hashes the tree to detect drift ([@sec:reproducibility]). Prose claims about the model are therefore checkable against an immutable, verified source rather than a moving website.

## Backend, task and policy abstractions

The benchmark backend receives a state and frozen typed questions, and returns predictions plus an attempt receipt. A profile declares primitive support, option and input limits, authentication scope, output provenance and probability meaning. The runner combines a backend profile, dataset view and protocol into immutable cells. A cell is the scheduling unit; it can contain multiple question-level decisions and multiple actual requests, as in a graphical experiment or cascade. These units must not be substituted for one another when reporting coverage or cost.

Native distributions are validated under their declared precision, without silent renormalization. Label-only outputs remain label-only. The deterministic rule reference reads authoritative synthetic state fields rather than target metadata; its ordinary labels acquire no invented beliefs. An analytical Bayes reference can return a genuine conditional distribution with analytical provenance. Fixed class-frequency and fitted supervised baselines declare their own probability meanings. Unsupported task/backend pairs remain in the planned matrix.

## Quality metrics and uncertainty

Hard-label classification uses accuracy and macro F1 over the complete declared vocabulary. Out-of-scope detection is also reported separately when the task contains an explicit OOS class. An ordinal rubric has two relevant readings: a selected category and a scalar level index. Classification accuracy uses a supplied distribution's argmax where available; MAE and RMSE evaluate the raw scalar in bin-index units. Averaging indices presumes a spacing convention and does not establish application utility or distance on the original physical measurement scale.

For a genuine distribution $p$ and hard label $y$, multiclass Brier loss is

$$
B(p,y)=\sum_{k=1}^{K}\left(p_k-\mathbf{1}\{y=k\}\right)^2.
$$

For a binary event, the separately named binary Brier loss is $(p_{\mathrm{true}}-y)^2$. The multiclass expression is twice the binary expression for an exact two-class simplex. This convention must be declared when comparing reported scores. Brier loss descends from probabilistic forecast verification [@brier1950verification]; strict propriety provides an incentive to report the true distribution in expectation under its assumptions [@gneiting2007proper]. It does not guarantee that a particular model has learned that distribution. The implementation also evaluates natural-logarithmic loss in nats, retaining infinite loss when a supplied probability assigns zero mass to a realized target rather than silently clipping it.

Reliability tables and expected calibration error summarize confidence/outcome correspondence using declared bins [@guo2017calibration]. Binning, sample size and the correctness target affect that summary. In the historical benchmark, the target is modal repeat agreement. In supervised evaluation it is an independent label. Those quantities have different interpretations even when the same formula is applied. Missing probabilities or confidence yield unavailable probability metrics, not fabricated zeros.

Uncertainty intervals resample input groups, keeping repeated or matched physical rows together. The selected CPU intervals use retained grouped percentile draws on fixed predictions. They describe resampling variation for that evaluated prediction set; they do not include model refitting, shared-training dependence across folds, model-selection uncertainty or a future deployment shift. Overlapping training sets make cross-validation errors dependent [@bengio2004variance]. The report therefore avoids treating pooled out-of-fold intervals as a universal variance estimate for the learning procedure.

The bootstrap substitutes an empirical sampling world for an unknown population; its usefulness depends on that approximation and the statistic's behavior [@efron2003second]. The prospective paired comparison reducer binds both arms to the same prepared inputs, planned decisions, targets and groups. It resamples the two arms together and recomputes macro-F1 for every draw. It retains the full execution denominators alongside conditional comparisons, rejects unmatched cohorts and suppresses incompatible ordinal decision rules. Missing probability forecasts remain unavailable. These intervals concern the fixed observed pairs; budget-dependent missingness does not acquire a random-sampling justification through bootstrapping.

Larger test sets can improve discrimination between systems, but repeated calls on the same input do not supply new independent task examples. NLP experiments show that detectable differences also depend on paired output correlation and that within-corpus significance need not transfer across domains [@bergkirkpatrick2012significance]. We therefore preregister complete quality cohorts separately from repeated latency/stability panels and preserve incomplete coverage, rather than treating a target call count as an achieved precision guarantee.

## Selective prediction and cascades

Let $a_\tau(x)$ indicate acceptance at confidence threshold $\tau$, and let $\ell(\hat y,y)$ be decision loss. Selective coverage and risk are

$$
C(\tau)=\mathbb{E}[a_\tau(X)],\qquad
R(\tau)=\frac{\mathbb{E}[a_\tau(X)\ell(\hat Y,Y)]}{C(\tau)}
$$

when coverage is positive. This separates how often a policy answers from how often its accepted answers are wrong. Rejection without a defined fallback is not a correct decision. Selective classification research supplies algorithms with risk guarantees under specified sampling and selection assumptions [@geifman2017selective]; those guarantees do not follow from a generic confidence cutoff.

Here, candidate thresholds are selected on validation groups using a recorded Wilson upper bound, which requires sufficient groups for the selected risk target. An accepted group is correct only when all its accepted decisions are correct. Scanning candidate thresholds on the same validation data makes the retained bound a descriptive selection rule, not a simultaneous distribution-free risk guarantee. A gate with no eligible threshold accepts nothing and has unavailable accepted risk. Test evaluation applies the frozen selected policy; a final refit changes the underlying model and cannot inherit a prior gate without new validation.

A weak/strong cascade invokes the strong backend only where the weak policy rejects. Cost-aware cascade research motivates joint quality and expenditure objectives [@chen2024frugalgpt], but a route's advantage must be measured under its actual invocation rule. Offline replay uses retained weak and strong predictions to score a counterfactual policy. It does not establish executed cascade latency, serving contention, batching behavior or actual avoided charges. Executed cascades retain each child attempt, including partial failure or budget rejection after the weak call.

## Exact graphical inference and elicited factors

The graphical layer represents finite discrete variables, a directed acyclic graph and complete conditional probability tables. Exact variable elimination computes

$$
P(q\mid e)=\frac{\sum_z\prod_i P(x_i\mid \mathrm{pa}_i)}{P(e)},
$$

where the numerator fixes query and evidence assignments and sums hidden variables. Zero-probability evidence has no conditional distribution and raises an error. Exactness concerns the calculation under the supplied factorization, not whether the graph or factors describe the world. Elimination order and induced width can make computation expensive even for a modest number of variables [@dechter1999bucket].

Async model-injected elicitation asks for every conditional row and can propose edges under a bounded search objective. The reference experiment discloses a known generative Bayes model and independently samples a hidden assignment. Returned beliefs are interpreted as normalized surrogate factors under that reference protocol; factor Brier error and posterior discrepancies are diagnostic comparisons, not evidence of learned causal structure or calibrated empirical CPTs. A structure proposal remains a graph proposal, without causal identification.

Evidence acquisition reveals an unobserved variable selected by its current marginal entropy, conditions the coupled posterior, and records the assignment, trajectory and fixed observation cost. Maximum current entropy is a heuristic; expected information gain asks how possible observations change uncertainty, and decision value additionally depends on downstream loss and cost [@mackay1992active]. The implemented rule does not optimize either objective. Optional model re-asks after each reveal are separately receipted, and a backend lacking genuine belief rows cannot be converted to a graphical factor by inventing one-hot probabilities.

## Reliability and cost accounting

Reports retain completed, failed, unsupported, unresolved and unattempted cells. A started cell without a terminal outcome is unresolved. Planned coverage uses the entire frozen obligation; attempted-outcome coverage describes the observed subset. Quality among successful predictions is consequently accompanied by the planned status distribution, so a difficult or unsupported arm cannot disappear from the denominator.

Token counts, reported API charges, reserved liability and local economic cost are different measurements. Known API charges are summed exactly, with unknown charge preserved as unknown. Admission requires a conservative sourced liability; a native catalog context length alone is insufficient to bound aggregate billable input across questions. A nominally free model does not make a response with missing billing metadata reconciled. A separately reviewed continuation may retain a finished historical unknown charge under an exact request-specific upper bound; the held bound consumes the existing allowance and remains distinct from reported charges. Unfinished transport, malformed accounting, overcharges and new unreviewed uncertainty still stop admission. Local hardware, energy and setup cost require a separately declared rate or measurement, and cannot be inferred from absent API billing.

External billing recovery adds an independently reviewed charge record for an exactly identified finished attempt while preserving its original unknown receipt. Generation metadata requires the original response identity; an account total, a model name or a missing activity row cannot establish the charge for a particular request. A provider statement must bind the complete retained attempt identity. Document hashes and reviewer declarations preserve custody but do not themselves authenticate the provider. Reports distinguish originally reported charges from externally verified charges and their combined effective total. A recovered charge exceeding its original reservation is fully debited and keeps admission stopped; reconciliation does not erase an inadequate liability bound. Bounded continuation is a separate operation: it preserves the unknown charge, freezes independent upper-bound evidence and its exact attempt identity, and holds the bound against the unchanged allocation. It supplies no measured cost or quality result.

Resource guards, cumulative allowances and owned cleanup constrain execution rather than model quality. A cancellation receipt can prove an attempt was interrupted without proving a final model outcome or charge. Raw unresolved windows remain unresolved; an additive nonrefundable allocation convention, if separately approved, must not be described as exact elapsed-time recovery or a rigorous upper bound on an unknown descendant. This distinction allows continuation designs to retain their uncertainty honestly.
