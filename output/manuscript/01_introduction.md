# Introduction: From Generated Text to Typed Decisions {#sec:introduction}

Applications often need a bounded judgment at a particular point in their control flow: classify an intent, estimate whether a condition holds, or assign a rubric score. Free-form answers require an interpretation layer, but modern generative systems can also constrain their output to a grammar or JSON schema [@willard2023guided; @openrouter2026structured]. The research problem therefore extends beyond parsing. A valid output must still refer to the right task, preserve its complete answer vocabulary, communicate only the uncertainty it actually supports, and enter a policy whose quality and cost can be evaluated.

TypeSafe describes Jev as a System One model returning typed judgments and distributions, with reinforcement learning for calibrated decisions (RLCD) as a training objective [@typesafe2026systemone; @typesafe2026systemoneconcept]. That documented objective motivates an interface; it does not establish calibration on a new dataset. A generated label, a normalized compatibility distribution, a supervised class-probability estimate, and an analytical conditional probability are distinct outputs even when they share a JSON shape. This manuscript treats their origin, declared meaning and empirical validation as separate parts of the decision contract.

## The problem this package solves

The initial package implemented the native System One surface: typed questions, response validation, transport errors and pure composition. Its extension addresses a broader methodological need: compare local open-source runtimes, hosted decision endpoints, constrained chat models and fixed supervised references without silently making their outputs or experimental conditions equivalent. An orchestration layer must retain unsupported tasks and failed attempts, distinguish selection from evaluation, and account for unresolved costs before admitting more requests.

daf-jev provides four connected components:

- **Typed primitives**: ergonomic builders (`noul()`, `choice()`, `score()`) and a `QuestionSet` container, with strict request and response validation.
- **Provider adapters**: synchronous and asynchronous native clients, plus a benchmark backend boundary for native decisions, constrained generated values and local references. Capabilities and probability meanings remain explicit.
- **Composable policies**: pure functions over answers (`composite_score`, `confidence_gate`, `route`, `pick`), validation-selected gates and cascade replay. Policy selection and executed policy timing have separate evidence requirements.
- **A reproducible evaluation protocol**: frozen dataset views, question and option order, source/runtime identities, per-attempt receipts, planned denominators, cost admission and offline reports. Real HTTP and owned-process fixtures test failure paths without substituting a fixture result for model execution.

The contribution is a modular implementation and an auditable study design, rather than a new learning algorithm or a claim that one provider is universally superior. Following the multi-axis evaluation motivation of HELM [@liang2023helm], the protocol exposes quality, probability interpretation, selective coverage, reliability, latency and cost together. The selected evidence is heterogeneous: historical hosted measurements, completed CPU comparator studies, partial native execution and a failed hosted capability probe. Their boundaries are part of the results, not omissions to be concealed by reporting only successful predictions.

## Reader's guide

[@sec:jev_model] distinguishes native decision contracts from constrained generation and discusses probability semantics. [@sec:methodology] defines the modular implementation, metrics, selective policies and exact graphical inference. [@sec:integration_surfaces] describes its software interfaces. [@sec:results] separates historical observations from current selected comparator and execution evidence. [@sec:experimental_setup] records datasets, splits, controls and measurement units; [@sec:reproducibility] explains exact evidence selection and regeneration. [@sec:scope] relates the approach to forecasting, selective prediction, cost-aware cascades and benchmark-overlap research, and identifies the remaining limits.
