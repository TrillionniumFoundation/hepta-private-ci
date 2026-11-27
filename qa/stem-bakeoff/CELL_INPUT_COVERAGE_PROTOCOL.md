# Fixed token budget input coverage diagnostic

This is a new historical-source diagnostic, frozen before its source selection
or model outcomes. It does not reopen the 2026-10-23 Cell study's evaluation
sources and does not claim future or production qualification. No production
runtime is changed. The implementation follows Cell-next stage 25 at
`4b3081c25af86f707a5c0d50c688c959a04af446`.

## Question and fixed treatment

The prior study truncated 77.19% / 84.65% of its holdout inputs at 192 tokens.
At the same actual native-token count, does retaining the beginning and end of
an issue improve a small Head over retaining only the beginning? This policy
is a candidate, not a presumed repair.

Use the already cached LiquidAI LFM2.5-Encoder-230M snapshot
`0b649ad0c684378b03d4d8304f7577a662ab89bc`, CPU FP32, two threads, batch eight,
one frozen model owner, masked-mean pooling over non-padding hidden states and
L2 normalization. That pooling is this experiment's explicit policy; upstream
documents a masked-language-model body, not a tuned sentence-embedding pooler.
This is a different encoder from the prior study; results cannot be attributed
to Granite or EG2 or to full supervised encoder fine-tuning.
If the pinned snapshot cannot execute with the existing environment, retain
the failure and stop rather than silently substitute another encoder.

Both policies reserve the tokenizer's native special tokens within 192.
`prefix` retains the first remaining tokens. `head_tail` retains the first
ceiling-half and last floor-half of the same number. Short inputs are unchanged.
Native selected token IDs enter the model directly, without decode/re-tokenize.
Record all original token positions, source text hashes, padding, effective
tokens, model forwards, wall/CPU time and memory. No target influences cropping.
Head-tail concatenates discontinuous spans; loss of middle context is a risk.

## Sources and targets

Acquire official SWE-bench train, test and dev Parquet at revision
`e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6`. Use only official train records
for the new experiment. Old official test and dev records serve exclusively
as exclusion identities, normalized issue texts, and normalized patch groups.
Union duplicate source IDs, normalized issue texts and normalized changed-patch
lines across all splits. Remove every group touching official test or dev.
Conservative generic-patch merging may remove unrelated issues and is reported.

Sort eligible training records by UTC issue creation time and source ID, then
apply 60/20/20 boundaries before removing any boundary-crossing duplicate group.
Retain one earliest record per remaining group. Within each split, take the
smallest deterministic SHA-256 ranks of `coverage-20261024-v1:<group_id>`:
at most 512 train, 128 calibration and 256 evaluation records. Do not select
on labels, model scores, token length, repository difficulty, or future results.
Preparation may read gold patches to derive targets and duplicate exclusions;
these never become predictors. Persist selection and all manifests before
encoding or fitting. Unknown pretraining and semantic overlap remain limitations.

Four fixed targets are exact structural properties of the human patch:
`multiple_paths`, `multiple_hunks`, `at_least_twenty_changed_lines`, and
`net_added_lines`, with the existing stage-24 parser and definitions unchanged.
They are repair-shape surrogates in one task family, not root cause annotations,
tool decisions or autonomous repair success. A target without enough training
groups in either class is reported unavailable; no replacement target is chosen.

## Fixed learning and controls

Use the same source groups across policies, methods and nested budgets 32/128;
use balanced training groups from the selected training pool with seeds 7/17/29.
Reuse the existing stage-24 linear Head: 200 full-batch Adam steps, learning
rate 0.02, L2 0.001, global gradient clip 5. No encoder updates or gate search.
Every control gets the same labeled examples. Controls are constant class
prior, frozen parameter/off Head, prototype, dense top-k retrieval, and full
issue BM25 top-k retrieval. Retrieval selects k only from 1/3/7/15 using the
calibration set; no reranker, external labels, or extra source queries.
The full-source BM25 control is deliberately strong and its text storage and
query CPU costs must be reported; it is not silently charged as 192-token input.
No trained Head is selected based on evaluation outcomes.

Train and save every candidate and its calibrated temperature before opening
evaluation labels. Persist evaluation probabilities before scoring. Preserve
all outcomes, including failures and negative or inconclusive results. Never
reuse this exposed evaluation cohort as a fresh acceptance set.

## Analysis and stopping rule

Primary contrast: head-tail minus prefix macro balanced accuracy at n=128,
averaging the four fixed targets and three fixed seeds. Use 2,000 paired
bootstrap draws of evaluation source groups, holding fitted heads/tasks fixed;
report a 95% interval. The n=32 curve and each method are descriptive secondary
contrasts. Also report accuracy, positive recall, NLL, class-prior baseline,
coverage at fixed confidence 0.7, and net success with abstentions counted as
unsuccessful. Correlated tasks and seeds are not independent experiments.

A positive primary interval is bounded evidence for this input policy on this
cohort, not an encoder-wide or general intelligence claim. Failure to beat
strong retrieval and small absolute skill remain constraints. Do not use a
nonpositive or inconclusive result to justify adding split/edge capacity.
No further tuning on these evaluation labels is allowed in this experiment.
Any follow-up needs a new frozen source group and a separate protocol.
