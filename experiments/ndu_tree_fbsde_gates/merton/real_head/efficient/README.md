# Prefix-reusing Head investment and corrected compute accounting

Research only. Parent `acd2a0fd8b25568188f7f554f14644c636bbdee2`, PR #2319.
No native NDU owner, selected model, production effect or parent evidence changes.

## What changes

The predecessor measured `predict + full_questions` together and used that sum
as future inference cost. Full-question scoring reads training/calibration labels;
it is not deployed prediction. This version measures prediction on label-free
rows and subsequent human-label scoring separately. Both remain paid in the
pilot lifecycle. Exact old records retain their old meaning and are not rewritten.

Candidate models have the same five-parameter architecture. The new versioned
quote uses the mean prediction-only cost across the twelve observed calibration
calls for every candidate. This is an explicit shared-architecture estimate,
not an assertion that coefficients cannot affect real CPU cost. Original raw
per-call costs remain in each record. Candidate final-refit quotes retain their
measured training dependence; hypothetical reuse remains eight, not observed
future executions. Ordinary enumeration independently rederives every decision.

The original 8/32/128-step pilots all start from zero, use the same data order,
normalizer, learning rate and full-batch deterministic SGD. They share the exact
first 8/32 updates. Run the 128-step trajectory once, copy its 8/32/128 snapshots,
and verify every snapshot against independently restarted training. Three inner
folds require 384 actual updates rather than 504. This is 23.8095% less PILOT
optimizer work, not an end-to-end speedup claim. Checkpoint copies and evaluation
are paid. This optimization is invalid for different data, random trajectories,
learning rates, initializations or optimizers without a new equivalence proof.

Controls are no-update, fixed8, fixed32, fixed128, corrected independent pilots,
prefix NDU-inspired pilots and prefix neutral pilots. All fixed controls really
perform no search. Every arm pays its own executed work; no cross-arm cache is
silently free. Nine rotated execution orders expose clock variability; they are
repeat measurements of the SAME four historical passages/eight questions, not
new independent sources or confidence intervals for future hardware.

The reference auditor reloads the same original four archives, reconstructs all
folds, and uses the inherited independently implemented scalar SGD to rederive
all coefficients, losses and probabilities. It checks actual updates, prediction
versus scoring phases, complete-question scores and exact rational choices.
Same author/separate implementation/process is NOT independent organizational
review. Raw timing consistency is not hardware attestation.

## Reproduce

From the repository root, after preparing original material with the unchanged
`real_head/material.py`:

```sh
D=experiments/ndu_tree_fbsde_gates/merton/real_head
export HEPTA_MERTON_ASSETS=/path/to/original/artifacts
python -m unittest discover -s "$D/efficient" -p 'test_*.py' -v
python "$D/efficient/prefix.py" --material /path/to/material --output /tmp/prefix-run
python "$D/efficient/audit_prefix.py" \
  --reader "$HEPTA_MERTON_ASSETS/11946621518.zip" \
  --labels0 "$HEPTA_MERTON_ASSETS/11949305579.zip" \
  --labels1 "$HEPTA_MERTON_ASSETS/11949100961.zip" \
  --human-score "$HEPTA_MERTON_ASSETS/11953241456.zip" \
  --material /path/to/material --run /tmp/prefix-run --output /tmp/prefix-audit.json
```

Repeat in `python -O` with fresh output paths. Replaying identical recorded costs
must produce identical choices; fresh clocks need not. Original source and
audit code hashes are bound into create-only output. Failed runs stay failed.

## Scientific boundary

This does not increase the source denominator. Another research line (#2323)
reports a different Granite/token-Reader panel, but its original per-question
archive was not obtained for this increment. Its aggregate is not a substitute
for source-bound predictions, the ModernBERT Reader identity or future data.
Do not claim a new-source trial, real future windows, neural preference learning,
continuous FBSDE, whole-service energy/p99, model superiority or promotion.

The new report explicitly tests whether the endogenous preference varies across
calibration folds and whether all candidate downside minima collapse to zero.
An inactive/saturated preference experiment cannot isolate dynamic-preference
benefit. Operational savings from reusing identical training prefixes are not
NDU-specific reasoning or learning efficacy.
