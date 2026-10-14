# E1 × E2 physical joint frontier — research only

This is a **new versioned shadow experiment**, stacked on draft PR #1848.
It does not modify the preexisting mmBERT 384d E2-v1 record or its source,
and does not promote a Stem, Head, Cell topology, signed NDU or production route.

## Actual preregistered inputs

| Field | Frozen baseline | New physical candidate |
| --- | --- | --- |
| Encoder | jhu-clsp/mmBERT-small | answerdotai/ModernBERT-base |
| Hidden width | 384d | 768d |
| Model revision | Exact materialized producer revision | fa3113d09d6dacfe5528708803dd92a62240237a |
| Corpus | Same original AG News public 128-row file | Byte-identical file |
| Folds | 64 train, 32 calibration, 32 retrospective holdout | Identical |
| Cells | 2 logical (same observed assignment) | Identical |
| Seeds | 11, 23, 47 | Identical |
| Train | 20 AdamW steps, batch 16; same per-Cell sampled indices | Identical |
| Head | factorized tanh, no dense base | Identical formula |
| Budget ceilings | 2K, 8K, 16K, 64K, 262K | Identical |

Actual parameter counts **differ** between 384d and 768d Head
widths, and are reported separately. The smaller 2K candidate is feasible
at 768d (1,550 parameters per Cell) without silently increasing the cap.
Comparing equal upper bounds is not comparing exactly equal parameters or
exactly equal active FLOPs. The physical Encoder loading and execution are
different and must be metered separately.

## Execution flow

The existing pinned real-weight public job first physically executes mmBERT,
including its original frozen Feature Snapshot and 16 saved trained/frozen
per-Cell Head checkpoints. The existing version-one E2 runner and
**independent NumPy reviewer** validate all five Head budgets: 60 checkpoints,
1,920 probabilities.

Next, the same job physically executes ModernBERT using safetensors,
pinning model and tokenizer files. Missing/download/weights/tensor errors
**fail** the job; there is no fake Encoder fallback. An independent model
execution review must pass, including the now-bounded train-only offline 768d
centroid router. The new `e2_modern_budget.py` then trains and seals a
**new v2**, not a reinterpretation of old v1, physical E2 sweep:
60 learned/frozen checkpoints and 1,920 sealed predictions.
`e2_modern_review.py` reopens the actual frozen features and
checkpoint tensors and recomputes every probability without importing
Torch or the fitter.

Finally, `e1_e2_joint_review.py` requires **both** independent physical
replay results, identical original corpus bytes, compatible candidate
registration, identical training/seed/budget/cell profiles, identical exact
minibatch stream digests and complete per-case/role/seed/budget coverage.
For each of five budget ceilings, it reports observed real trainable
parameters per Cell; case-paired correct/incorrect/tie counts, multiclass Brier
difference and a multiplicity-corrected bootstrap interval.

### Hosted commands (paths are on the hosted runner)

```sh
python -m experiments.shared_stem_cell.e2_modern_budget \
  --manifest /approved/modern/manifest.json \
  --producer /approved/modern/execution \
  --report-sha256 MODERN_REAL_REPORT_SHA256 \
  --output /evidence/e2-modern
python -m experiments.shared_stem_cell.e2_modern_review \
  --manifest /approved/modern/manifest.json \
  --producer /approved/modern/execution \
  --report-sha256 MODERN_REAL_REPORT_SHA256 \
  --sweep /evidence/e2-modern \
  --output /evidence/e2-modern-review.json
python -m experiments.shared_stem_cell.e1_e2_joint_review \
  --mmbert-manifest /approved/mmbert/manifest.json \
  --mmbert-producer /approved/mmbert/execution \
  --mmbert-report-sha256 MMBERT_REAL_REPORT_SHA256 \
  --mmbert-sweep /evidence/e2-mmbert \
  --modern-manifest /approved/modern/manifest.json \
  --modern-producer /approved/modern/execution \
  --modern-report-sha256 MODERN_REAL_REPORT_SHA256 \
  --modern-sweep /evidence/e2-modern \
  --output /evidence/e1e2-joint-review.json
```

The production artifact does **not** include any downloaded base Encoder
weights, private labels, credential tokens or release authority. Head
checkpoints are research artifacts, scoped to their original data.

## What the current local evidence establishes

**Actually executed and independently replayed:** the original 384d
mmBERT frozen-feature E2 v1 run, 60 checkpoints and 1,920 output vectors.
The v2 768d algorithm has passed seven bounded unit tests (including a real
Torch optimizer fit) and an end-to-end **synthetic software fixture** in
which the old 384d features were duplicated to 768d. That fixture replayed
60 checkpoints and 1,920 predictions and exercised the paired reviewer;
**it is NOT a ModernBERT model result**, not a valid new source family,
and must never be imported into a model-efficacy score.

The prior real ModernBERT run #1835 reached the Encoder forward step
but failed at a separate 512d-limited training-only router.
The bounded 768d research-only correction is in draft PR #1848.
Only a successful **new exact-source hosted run** can supply actual
ModernBERT E1/E2 comparison data and close that issue.

## Strict non-acceptance

The AG News 32-row publisher Holdout is retrospective, repeated across
three seeds. Its record/group IDs do not independently certify source-family
independence. The bootstrap groups by original case and keeps all seeds
together; its five-budget familywise correction is exploratory.
It **cannot** choose the production Encoder or Head.

Unknown GPU/energy/target-host counters remain unknown. A process-lifetime
peak RSS observation is disclosed per model but never presented as an
isolated-per-Head memory or certified target-host capacity. No Laya 421M,
frozen production no-change, two genuine future windows, independent signed
NDU, negative-transfer/retention, or 64–4096 native Worker/WAL recovery
qualification is supplied here.

All receipts retain `research_winner_selected=false`,
`signed_future_NDU_verified=false`, `production_accepted=false`.
The native Neuron Q24 z≤512 pilot schema, Artifact CAS, generation fences,
independent Evaluator/Selector/Executor and final-use authority are unchanged.

## Tests

```sh
python -m unittest -v experiments.shared_stem_cell.test_e1_e2_joint_review
python -m compileall -q experiments/shared_stem_cell
```
