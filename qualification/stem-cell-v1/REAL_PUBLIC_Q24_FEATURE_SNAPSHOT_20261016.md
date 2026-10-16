# Real pretrained ModernBERT → immutable public BANKING77 32D Q24 Feature Snapshot

**Research-only / DRAFT / DENY_ALL.** Child of public physical Encoder
[PR #1825](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1825)
frozen at `758205d3de23ccbf76649b1446c271101dc917b0`. Unlike
synthetic Q24 experiments in
[PR #2426](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2426),
this branch **must load genuine pinned pretrained weights** and exact public
BANKING77 data. There is no offline random-feature or random-weight fallback
for the deployed physical integration step.

## Fixed source and no-label-leak producer split

- Hugging Face `answerdotai/ModernBERT-base`, pinned upstream model revision
  `8949b909ec900327062f0ebf497f51aef5e6f0c8`, complete
  `ModernBertForMaskedLM` materialization and reviewed stock eager Encoder
  worker from the existing original canary.
- PolyAI BANKING77 Git commit
  `57ec275d8078af65b7731c2a98be812d844a6d6b`,
  **CC-BY-4.0**. Four original fixed intents, 64 fitting utterances and
  32 official test utterances, exact original selection and no normalized
  text/ID overlap.
- `prepare` mode rereads the original physically pinned CSV bytes and
  verifies the original case selection. It writes an **unarchived**
  create-once Encoder-only input envelope: fitting ID/text/label,
  official heldout ID/text **without heldout label**.
- A distinct `encode` process reads **only that unarchived input** and the
  original local pinned pretrained snapshot, not raw original CSV files,
  not a heldout scoring endpoint or experimental selected Cell models.
  Every Encoder invocation receives `state, question, options` only,
  the identical prompt used by the original public CellBank experiment.

## Fit-only PCA32 and Q24 physics

The producer executes a fresh **96 actual CPU Encoder forward calls**: one
pooled F32 768D vector for every predeclared case, shared across all later
candidate comparisons. This is an *additional pass* relative to the original
Dense16/Sparse16 canary, not a falsely deduplicated original operation cost.

1. Center only the 64 **unlabeled fitting vectors**.
2. Compute SVD of the 64×768 centered training matrix; freeze the top
   32 right-singular vectors. Canonicalize each PC's sign by the largest
   magnitude source coordinate. Fail closed if actual training-only PCA rank
   is insufficient.
3. Normalize by train-only coordinate RMS, apply the same frozen
   768×32 projector to heldout vectors without refitting or score tuning.
4. Clip only at the native signed `[-8Q,8Q]` bounds and convert to signed
   Q24 I64 with nearest/ties-even; report every clipped coordinate.

Three actual safetensors artifacts are stored in **one immutable Snapshot**:
`pooled-f32.safetensors` (original 64+32 real F32 vectors);
`train-only-pca32.safetensors` (F32 center, 768×32 components, scale);
`feature-q24.safetensors` (64+32 original-ID-aligned signed I64 32D vectors).
A separate `case-registry.json` stores all IDs and fitting four-class
labels, but **only IDs for the heldout split**. `SEALED.json` binds all
four physical files' SHA256+byte sizes, original actual downloaded model
snapshot SHA256 and source revisions, and explicit deny authority.

`audit_public_q24_snapshot.py` opens the saved physical files and
independently re-fits training-only PCA and replays both Q24 splits. It
checks all SHA/shape/dtype, selected IDs, test-label absence and no
future-window claims; tampered projections, mislabeled cases and reordered
arrays block.

## Physical hosted acceptance

The existing `hepta-neuron-next-round-matrix` public Encoder job
acquires real pretrained/model data as before, executes original public
learning, then runs create-once `prepare` and real `encode` + independent
audit. It archives only the small Q24 F32/projection/features, case IDs,
JSON source attestation and verdict; **not the pretrained base model weights,
original raw CSV files, or raw natural-language case texts**.

The `test_public_q24_feature_snapshot.py` unit suite uses a clearly labeled
synthetic 768D fixture for *mechanics and negative controls*, and is NOT a
real Encoder invocation. The user-visible scientific acceptance must rely
on the exact original model-loading hosted task and its new artifact, never
the fixture's pass.

## Hard boundaries

This study does **not** run native Q24 temporal Cell heads on these public
features yet, and it retains the original baseline V1 missing A0 selected
weight/Checkpoint signatures. BANKING77 official heldout is **not a future
time window**, so genuine temporal retention, negative transfer and NDU
outcomes remain absent. Nor does it prove no pretraining contamination,
independent public-model signing, equal candidate training FLOPs/memory,
target-device 64/256/1024/4096 full pipeline, WAL/CAS or final-use.

The next consumer must authenticate the exported actual Feature Snapshot
and use it for every native Q24 candidate + baseline with correct
four-class/one-vs-rest targets; never claim performance without scoring
sealed task labels separately.

**No model promotion, main merge, CNS cutover or physical Cell split.**
