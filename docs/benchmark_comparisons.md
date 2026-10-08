# Paired cohort comparisons

`daf_jev.benchmark_comparisons` compares fixed primary predictions offline.
It neither contacts a model nor reconciles billing. The caller selects verified
input/source artifacts before reduction; the pure API does not attest their
external custody or infer dataset identity from coincident example IDs.

```python
compare_predictions(
    left_rows, right_rows,
    left_binding=left_binding, right_binding=right_binding,
    labels=complete_vocabulary, label_kind="categorical",
    bootstrap_samples=2000, seed=0,
)
```

Each arm binding requires `backend_id`, `inference_source_sha256`, `dataset_id`,
`dataset_index`, `prepared_dataset_sha256`, `split`, `phase="quality"`,
`cohort_sha256`, and `hard_prediction_rule`. The dataset/index/prepared-input,
split/phase and complete cohort identities must match. Backend and inference
source identities are retained separately and may differ; a new reporter does
not relabel the inference source. Vocabulary and label kind must be taken from
the verified input artifact, not inferred from observed outcomes.

Each planned decision row requires `example_id`, `question_id`, `group_id`,
`input_sha256`, `target`, explicit `status`, frozen boolean `applicable`, `split`,
`phase="quality"`, and integer `repeat=0`. Status is one of completed, failed,
unsupported, unattempted or unresolved. Completed rows need a prediction or an
explicit abstention, and cannot contain an error. Inapplicable rows cannot have
attempted outcomes. Include the entire planned decision inventory, even if an
arm is entirely unsupported or unattempted. Warm repetitions are a different
analysis and cannot inflate primary independent-group counts.

`input_sha256` must bind the complete model-independent state and question
instructions/criteria with their frozen insertion order. For example, SHA256
over UTF-8 JSON containing the state and an ordered list of `[question_id,
question.to_wire()]` pairs preserves option order. Use a declared, identical
serialization recipe for both arms. This fingerprint binds the frozen request
material; it is not an HTTP response, transport-wire or server-tokenization
attestation. `comparison_cohort_hash(rows)` hashes the full target/group/input
inventory in canonical example/question order, so arrival order does not affect
it. Duplicate identities reject. A saved binding's cohort hash must match the
entire supplied inventory; omitting failed rows or supplying different targets,
groups or inputs rejects.

The result retains full planned status counts, planned independent groups,
joint applicable decisions, joint valid outcomes and conditional coverage.
Accuracy, full-vocabulary macro-F1, sum-form multiclass Brier and raw ordinal
MAE have separate joint measurement denominators. Missing distributions remain
unavailable for Brier; soft probability targets receive no hard accuracy or
macro-F1. Binary targets are hard true/false or zero/one; fractional soft targets
require an explicit complete probability mapping. Declared native row-rounding
allowances preserve the original numbers without renormalization. Failed,
unsupported, unattempted and unresolved partial values are ignored for scoring
while their identities and statuses remain in the planned denominator.

All differences are **right minus left**. Accuracy and macro-F1 use fractions;
accuracy also reports `difference_pp` in percentage points. Brier uses the sum
of squared probability errors; ordinal MAE uses the declared bin coordinates,
without rounding the reported scalar. Positive accuracy/F1 deltas favor the
right arm; negative loss deltas favor it. The caller declares the actual hard
prediction rule: `reported_label`, `scalar_exact` or `probability_argmax`.
Mismatched rules suppress accuracy and macro-F1 deltas, including native
ordinal probability argmax versus generated exact scalar accuracy. Their raw
ordinal MAE can still be compared on the common declared numeric coordinates.
Argmax ties retain the consumed probability mapping's insertion order, matching
the existing metric reducer; canonical identity hashing does not reorder an
outcome distribution before scoring it.

The bootstrap draws independent input groups with replacement, using the same
group multiplicities for both arms. All decisions and matched permutations in
a group travel together. Additive metrics use paired row differences and a
row-weighted cluster ratio. Macro-F1 recomputes the full-vocabulary confusion
totals on every draw, retaining absent classes in the macro denominator.
Percentile endpoints use the existing nearest-rank convention. Empty metrics
are unavailable; one group retains a point but has no interval. A percentile
interval is not required to contain the original point estimate.

These are descriptive 95% intervals over retained fixed predictions, conditional
on joint measurements. They do not establish refit uncertainty, valid optional
stopping, a selected-threshold population risk guarantee, or a multiple-comparison
guarantee. Unknown probability semantics remain explicit and do not become
calibration, posterior or probability-of-correctness claims. The module creates
no cost or latency frontier; replayed routing is not an executed cascade.

[Koehn's paired resampling design](https://aclanthology.org/W04-3250/) motivates
sharing test samples, while [Bengio and Grandvalet](https://www.jmlr.org/papers/v5/grandvalet04a.html)
explain why overlapping fitted folds need separate uncertainty treatment.
[Howard et al.](https://arxiv.org/html/1810.08240v8) provide sequentially valid
methods under stated conditions; an ordinary percentile bootstrap does not
inherit their guarantees.
