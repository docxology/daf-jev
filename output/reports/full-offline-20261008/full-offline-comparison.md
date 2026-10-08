# Full offline comparison

Nine serial CPU jobs evaluated fixed references and supervised baselines under accepted source 9b69c7c0. All source, input, manifest, journal/head and output bindings remain in the selected JSON. This candidate contains relative repository paths and aggregate metrics, without raw prompts or private absolute paths.

Planned cells: 93046; completed: 68894; unsupported: 24152; failed/unresolved: 0. No HTTP attempts or supplied API billing; local monetary expense is unknown.

The five BANK validation rotations and published/grouped CLINC/Wine validation job precede final train+validation refits. Hyperparameters were fixed. Official tests had prior exposure; no new held-out, test-driven selection or gate-transfer claim is made.

## Canonical official test and separately refitted clean sensitivity

| Cohort | Dataset | Comparator | Valid / planned | Groups | Accuracy | Macro F1 | Raw ordinal MAE / RMSE |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| canonical | clinc150 | prior | 5500 / 5500 | 5500 | 0.181818 | 0.002038 | unavailable / unavailable |
| canonical | clinc150 | wine-hist-gradient-boosting | 0 / 5500 | 0 | unavailable | unavailable | unavailable / unavailable |
| canonical | clinc150 | tfidf-logistic-C1 | 5500 / 5500 | 5500 | 0.798364 | 0.845058 | unavailable / unavailable |
| canonical | wine | prior | 1300 / 1300 | 1064 | 0.765385 | 0.173420 | 0.331866 / 0.459700 |
| canonical | banking77 | tfidf-logistic-C1 | 3080 / 3080 | 3079 | 0.876948 | 0.876885 | unavailable / unavailable |
| canonical | banking77 | wine-hist-gradient-boosting | 0 / 3080 | 0 | unavailable | unavailable | unavailable / unavailable |
| canonical | wine | wine-hist-gradient-boosting | 1300 / 1300 | 1064 | 0.753077 | 0.301982 | 0.276985 / 0.459780 |
| canonical | banking77 | prior | 3080 / 3080 | 3079 | 0.012987 | 0.000333 | unavailable / unavailable |
| canonical | wine | tfidf-logistic-C1 | 0 / 1300 | 0 | unavailable | unavailable | unavailable / unavailable |
| prefit-clean | clinc150 | prior | 5498 / 5498 | 5498 | 0.181884 | 0.002038 | unavailable / unavailable |
| prefit-clean | clinc150 | wine-hist-gradient-boosting | 0 / 5498 | 0 | unavailable | unavailable | unavailable / unavailable |
| prefit-clean | clinc150 | tfidf-logistic-C1 | 5498 / 5498 | 5498 | 0.797745 | 0.844511 | unavailable / unavailable |
| prefit-clean | wine | prior | 1300 / 1300 | 1064 | 0.765385 | 0.173420 | 0.331866 / 0.459700 |
| prefit-clean | banking77 | tfidf-logistic-C1 | 3073 / 3073 | 3072 | 0.876017 | 0.875929 | unavailable / unavailable |
| prefit-clean | banking77 | wine-hist-gradient-boosting | 0 / 3073 | 0 | unavailable | unavailable | unavailable / unavailable |
| prefit-clean | wine | wine-hist-gradient-boosting | 1300 / 1300 | 1064 | 0.753077 | 0.301982 | 0.276985 / 0.459780 |
| prefit-clean | banking77 | prior | 3073 / 3073 | 3072 | 0.013017 | 0.000334 | unavailable / unavailable |
| prefit-clean | wine | tfidf-logistic-C1 | 0 / 1300 | 0 | unavailable | unavailable | unavailable / unavailable |

Accuracy intervals, Brier intervals and ordinal MAE intervals use 2,000 grouped percentile draws and are retained per arm in JSON. Macro F1 uses the complete declared vocabulary; missing Wine bin0 therefore remains in the averaging vocabulary. Wine classification accuracy uses genuine probability argmax, while MAE/RMSE use the raw prediction scalar in bin-index units. Class-probability estimates and training-label frequencies are explicit meanings, not established calibrated posteriors.

## Five-fold validation

- prior: accuracy 0.018694; 95% [0.016092, 0.021494]; 10003 physical rows / 9999 input groups.
- tfidf-logistic-C1: accuracy 0.859242; 95% [0.852159, 0.866100]; 10003 physical rows / 9999 input groups.

OOF intervals describe fixed predictions and do not include correlated shared-training/refit uncertainty. Validation-only adaptive Wilson gates are recorded for each fitted selection model, without simultaneous risk guarantees or transfer to final refits.

## OOS and Wine limits

Canonical CLINC C1 OOS: TP 354, FP 58, FN 646, TN 4442; recall 0.354000, precision 0.859223, F1 0.501416. All1000 planned OOS rows completed; official 'oos' is unchanged.

Wine bin0 (grades0–2) has no source observations; bin4 has five white grade9 rows, including one test row. Grade10 is absent. Extreme-bin performance cannot be generalized from these counts.

Wine empirical H(original grade | bin): full 0.895168 bits, selected test 0.891319 bits. This is information lost by binning, not prediction error.

Matched categorical controls comprise 14 validation/test groups and 42 physical rows. Exact-rule all-member agreement is1; uniform reference agreement is0 through declared tie-breaking. These are mechanism checks of joint ordered presentation, not learned-model prompt-position causal evidence.

## Evidence and reproduction

- Selected JSON SHA256: `e018869c8a448cc04710ae4b691616daa563b31c4f0901e8a1a73766df04a0b7`.
- Original numeric summary SHA256: `45d74ad9a7e73710acb4a94ef0c4380e7ae5113a20714aef2bfef3eaef1286fd`; its inherited Wine wording is corrected additively here.
- Nine complete reports independently regenerated with exact JSON stream identity; all original exports and source snapshots preserved.
- Portable preparation/view commands and fixed baseline recipes: docs/datasets.md and benchmarks/configs/full-offline.yaml, full-offline-leakage-clean.yaml and banking77-selection-fold0.yaml through fold4.
- API request billing is zero for these local CPU comparators; energy/hardware expense and native/hosted performance remain unavailable.
- Historical partial native studies, exhausted Qwen4 allowance and hosted zero-attempt proposals remain separate; no funding or allowance reset.

Sources and licenses:
- banking77: [https://github.com/PolyAI-LDN/task-specific-datasets](https://github.com/PolyAI-LDN/task-specific-datasets); CC-BY-4.0.
- clinc150: [https://github.com/clinc/oos-eval](https://github.com/clinc/oos-eval); CC-BY-3.0.
- wine: [https://archive.ics.uci.edu/dataset/186/wine+quality](https://archive.ics.uci.edu/dataset/186/wine+quality); CC-BY-4.0.
