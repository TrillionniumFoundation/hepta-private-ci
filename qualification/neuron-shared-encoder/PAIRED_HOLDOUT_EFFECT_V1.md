# Original-case paired Pooled versus Token Query quality panel — shadow only

**Research status:** this feature adds purely descriptive analysis to the separately
re-encoded, independently numerically replayed and source-pinned full-token
ModernBERT Head experiment. It never runs a model, loads a checkpoint, selects a
Head, issues final-use permission, changes a Cell or promotes a deployment.

## Why this is necessary

The fixed historical public AG News cohort contains **32 distinct holdout cases**:
16 for each logical Cell. There are three planned Head optimizer seeds. Counting
all 96 `(case, seed)` observations as independent inflates the effective sample
size. Prior reviewer output retained a per-seed accuracy contrast but had no
unified case-paired uncertainty report for accuracy, Brier and NLL.

The new `paired_holdout_effect_v1.py` accepts only the verified *post-seal*
matched case, Cell and seed logits emitted inside the independent NumPy reviewer
and computes the **Token Query minus Cached Pooled** metric differences:

- Accuracy: positive favors Token Query.
- Brier and NLL: negative favors Token Query.
- Newly-correct and newly-incorrect counts are explicitly labeled **repeated
  seed observations**, not additional source cases.

For each original case, first average its complete seed trajectory. Then run a
fixed-seed, 2,000-repeat descriptive 95% case bootstrap, sampling 16 original
cases with replacement **within each Cell**, retaining both arms and all seed
repeats together. Every report binds the fixed resample seed and sample count.
No hyperparameter, budget, architecture, checkpoint or production winner is
selected by any interval, even when an interval excludes zero.

## Fail-closed checks

Exactly 32 distinct original source cases and 16 per Cell; exactly one matched
Pooled/Query pair per `(case, seed)`; aligned non-Boolean class labels; stable
source-group and label across seeds; complete identical seed sets for every
case; strict finite four-class logit geometry; no metadata outside the fixed
allowed schema, including raw text or alleged future timestamps. Missing,
duplicate, cross-scope or nonfinite evidence refuses the entire summary.

The independent Reviewer calls this function **only after** all frozen
checkpoints are SHA-verified and its NumPy Head arithmetic agrees with the
Producer's held-out metrics and newly correct/incorrect counts. It returns an
additive `paired_original_case_descriptive_effect` field. The original source
itself has `observed_at=null`, so this remains a retrospective publisher holdout,
not a time-forward experiment.

### Evidence boundaries

`case_source_independence_verified=false` because publisher `group` identifiers
alone do not prove independent source families. A stratified bootstrap does not
solve hidden clustering, data reuse, adaptation to holdout or correlated topics.
Three training seeds represent repeated stochastic training, not 96 independent
observations. These intervals are **descriptive** rather than independently
attested NDU utility, causal benefit, OOD robustness, or equal full-system cost.
The real deployed no-change baseline and genuine prospective windows are absent.

All records always emit:

```
production_admission = BLOCKED
model_winner_selected = false
selection_authorized = false
real_deployed_nochange_verified = false
prospective_future_outcome_verified = false
independent_signed_NDU_verified = false
```

No patient/user raw prompts, full original articles, feature matrices, or
per-case probabilities are written into the report. The original producer,
independent reviewer and public model asset checks remain mandatory. A local
hash is not a trusted signature.

## Tests and acceptance

Run the normal research suite in `qualification/neuron-shared-encoder`:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
python -m pytest -q -p no:cacheprovider tests/
```

The added tests cover source/seed/Cell identity and group isolation, numeric
and shape faults, missing/duplicate/reordered observations, calibrated signs,
bootstrap reproducibility, the no-winner posture, and actual integration with
the research NumPy reviewer using explicitly **synthetic** test features.
Original true ModernBERT weights and actual independent second physical
forward are **not** available in this local environment; only hosted exact-SHA
CI logs and fixed-model execution receipts can establish that later.

The next decision needs physical full-token forward evidence, a sealed review
for all 12 Head safetensors and 32 historical holdout rows, independent future
outcomes and no-change NDU, and real host Encoder+Head+cache+Worker cost. This
addition itself provides no scientific selection or production qualification.
