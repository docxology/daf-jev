# Decision Interfaces: Native Judgments, Generated Values, and Probability Meaning {#sec:jev_model}

The original native interface is documented by TypeSafe's retained System One snapshot. Its statements about training, architecture and performance are vendor claims, distinguished here from the package's validation rules and selected measurements. The wider benchmark interface also supports generated values and supervised references; compatibility with that interface does not establish identical uncertainty semantics.

## The native decision contract

TypeSafe positions Jev as a component supplying narrow judgments to application-owned control flow [@typesafe2026systemone]. Its documented RLCD objective aims at calibrated decisions [@typesafe2026systemoneconcept]. The manuscript does not infer achieved calibration, correctness or deployment suitability from that objective. Third-party launch coverage remains historical commentary, rather than evidence for a model's present behavior [@register2026jev; @orcarouter2026jev].

A native request carries a state and caller-keyed questions. The documented primitives are [@typesafe2026apidocs; @typesafe2026primitives]:

- **`noul`**: a declared probability for a binary condition, optionally described by contrasting true/false criteria.
- **`choice`**: a selected label, a distribution over the complete named vocabulary, and a scalar confidence field.
- **`score`**: a possibly fractional rating over ordered level indices, with its level legend, distribution and confidence field.

Native clients validate response shape, finite numeric values and question compatibility. Benchmark adapters retain available usage and request identifiers in attempt receipts, including when later semantic parsing fails. These checks establish an admissible response under the stated contract; they do not establish that the selected label is correct. Missing usage, resolved provider or billing fields remain unavailable rather than being inferred from a successful status code.

## Documented isolation and backend capacity

TypeSafe describes questions as independently evaluated within a parallel request [@typesafe2026systemone; @typesafe2026patterns]. That supports the documented batching pattern, but independence is a provider claim to test when comparing actual runtimes. The package can express isolated questions without proving a backend's internal computation is isolated. A paired experiment with identical state, questions and options is needed to assess whether batching changes predictions.

Capacity is profile-specific: question count, complete option vocabulary, input size and supported primitive types must all fit. A broad catalog context field alone does not establish how a native server tokenizes multiple questions or bills their aggregate input. Oversized or uncertain inputs remain planned unsupported cells; the evaluation does not shorten states, drop rare classes or substitute another model to improve completion.

## Constrained generation is a separate instrument

Guided decoding can restrict a language model's output to a formal language [@willard2023guided]. The chat adapter supplies a strict per-request JSON schema containing all required question identifiers, full choice enumerations and numeric bounds. Official OpenRouter documentation describes structured outputs, while warning that support and enforcement depend on the selected endpoint [@openrouter2026structured]. The adapter therefore validates returned values itself.

A generated label or bounded scalar remains a generated value. No one-hot belief or confidence is manufactured from it. Token likelihoods, where available, concern token sequences and need an independently justified mapping before they can be treated as probabilities over decision outcomes. Native Decisions and generated chat also use distinct documented endpoints [@openrouter2026decisions]; catalog discovery and documentation availability do not prove a particular authenticated request will succeed.

## Probability validity, concentration and calibration

Numerical validity asks whether a distribution is finite, nonnegative and has the permitted total mass. Concentration asks how strongly that distribution favors particular outcomes. Calibration concerns its relationship to observed outcomes; a concentrated but systematically wrong forecast can be valid and poorly calibrated. Forecasting theory distinguishes calibration from sharpness and motivates evaluating both with proper scoring rules [@gneiting2007proper].

The benchmark retains declared meanings such as training-label frequency, estimated class probability and analytical conditional probability. A native row with undocumented meaning stays unknown. Its distribution can still be compared descriptively with a labeled target, but a numeric score does not convert compatibility weights into established posterior beliefs. Provider confidence fields and entropy-derived statistics likewise do not automatically estimate the probability that a selected decision is correct [@typesafe2026confidence; @guo2017calibration].

Historical self-agreement is narrower still. Repeating a wrong answer consistently produces a stable modal label. Agreement with that label measures repeat behavior, not correctness against an independent target. The historical reliability diagram in [@sec:results] is explicitly a proxy-agreement diagram. Application-owned gates require labeled validation for their actual loss and coverage objective, followed by evaluation of the frozen policy.
