# V21 — Independent post-hoc paired uncertainty on real pretrained AG News

**Exploratory research only; NO-GO for model selection, NDU or production.**

V20 completed real released mmBERT-small and Granite 97M R2 frozen Encoder
forwards, 128 train / 64 public AG News heldout examples, equal 8,204 Head
parameters and 64 AdamW steps, plus a separate heldout-label evaluator.
At its pinned published test set, mmBERT's Head scored 55/64 correct vs
Granite 54/64. V20 did **not** observe a deployed no-change baseline, a
prospective future stream, independent source publisher attestation or
matched total Encoder CPU/memory work. An apparent +1 case therefore cannot
justify production model selection.

V21 changes only the independent **evaluator**, never the original corpus,
model weights, training, Head initialization, split, feature pooling or score
semantics. After V20 has validated *both candidate result documents*, exact
source hashes and the heldout label census, V21 computes on the SAME matched
cases:

- The full 2×2 correct/incorrect paired contingency (both correct, each
  model alone correct, both incorrect) and exact two-sided McNemar p-value
  on discordant pairs; no asymptotic chi-square approximation.
- Observed mmBERT-minus-Granite differences in accuracy, multiclass Brier
  and log loss.
- Reproducible, same-case **class-stratified** paired percentile-bootstrap
  95% intervals: 4,096 resamples, seed 20261015, independently resampling
  16 heldout cases within each of 4 original classes. The same resampled
  indices apply to both model predictions and all three scores.
- Strict checks on the 64 sorted case IDs, original four balanced strata,
  two complete probability matrices and finite normalized probabilities.
  The evaluator receives heldout targets; Head fit/predict does not.

These statistics are exploratory and were added **after the V20 result was
observed**. The public AG News labels are not prospective. There is only one
training seed and one small heldout slice. A low nominal p-value cannot be
used as a pre-registered finding, model winner, negative-transfer test or
production authority. V21 always reports
`inference_status=posthoc_exploratory_public_test_set`, `experiment_winner=null`,
`significance_or_model_superiority_qualified=false`, `deployed_no_change_observed=false`,
`independent_ndu_verified=false`, `production_accepted=false`, `authority=DENY_ALL`.

The physical push-only V20 workflow now reruns both original frozen encoders
and Heads with **unchanged** data/budget, then emits V21 paired diagnostics
within the label-bearing independent readout. CI refuses missing diagnostics or
any authorization claim; model weights, raw texts and individual labels remain
excluded from uploaded artifacts.

A future confirmatory study requires **pre-registered** multiple independent
seeds, a truly unseen future window or new corpus, deployed no-change
predictions observed before new model selection, and a resource/NDU assessment
including actual model forwards and long-run CPU/RSS, not merely equal Head
parameters. The observed V20 wall-time ratio is descriptive and not equal
compute allocation.
