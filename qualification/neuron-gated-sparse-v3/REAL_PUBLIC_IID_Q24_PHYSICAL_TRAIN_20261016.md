# 32 physical real-public IID Q24 Cell trainer — not future temporal learning

**DRAFT / DENY_ALL / SHADOW ONLY / no model promotion.** Stacked directly
on [PR #2506](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2506),
whose physical source is the pinned real ModernBERT 96-case train-only PCA
Feature Snapshot from [PR #2499](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2499).

## What executes

The input owner freezes 64 real BANKING77 public text cases, exact case IDs,
train-only 32D Q24 features and **train labels only**. No heldout labels or
heldout feature vectors appear in the actual training-source file read by
`real_public_iid_q24_physical_train.py`.

For each of four fixed intent-vs-rest binary tasks and each of the four
V2/V3/SSM/low-rank-minGRU Cell mechanisms at 8KiB and 32KiB **serialized
physical file-size** ceilings, the new program:

1. Reopens pinned fit-input and preregistered plan bytes with exact external
   SHA-256 checks; requires 64 unique fit IDs, class balance 16/16/16/16,
   32D signed bounded Q24 and explicit `DENY_ALL` / no-future profile.
2. Constructs a genuinely trainable private 32D→h F32 Adapter, an actual
   differentiable mechanism module, F32 binary Head and fixed resident I64
   Q24 projection using the existing `matched_train.make_model` training
   surrogate and independently audited `near_matched_byte_budget.choose`.
3. Seeds the same 64-sample permutation schedule across all candidates; the
   prescribed eight epochs are four 16-sample minibatches per epoch: **32
   optimizer updates per model, 512 original training-case exposures per
   model**, with every 64-case fit sample seen once each epoch.
4. **Resets recurrent state independently for every IID utterance.** Texts
   have no verified event timestamp or transition identity, so no synthetic
   `event_time_utc` is supplied or transformed into a future task.
5. Physically persists and reopens all private F32 and signed-I64 Q24
   safetensors weights, verifies tensor count/identity/dtype and the measured
   exact serialized-byte envelope; each file gets an actual SHA-256.
6. Writes a create-once `training-receipt.json` binding actual tensor SHAs,
   source input and plan SHA, all 32 trained model identities, full optimizer
   exposure/cost, NO heldout labels, NO 768D public Encoder execution within
   the trainer, NO signed original selected V1 A0, no future effect and NO
   production/NDU authority.

## Scientific boundaries

This stage can prove **physical training** on the *same* genuine public
32D feature corpus only if the pinned original public producer's hosted CI
successfully emitted that source in the same run. It is not a heldout
prediction or improvement, no original frozen selected production V1
comparison, and no formal comparative learning study of temporal memory.
Equal 32 optimizer steps and similar file byte ceilings are not matched
training FLOPs, accelerator use, real resident memory or total CPU.

The independent scorer must first re-open the 32 immutable model weights,
then load the original heldout observer labels in a separate step after the
training stage finishes, evaluate each one-tick state-reset Cell on the
identical 32 heldout vectors, retain abstentions/errors/latencies and
independent identity/cost receipts, and *still* keep model promotion blocked.
That would remain a static IID single-study benchmark, not future-window
NDU or negative-transfer evidence.

## New hosted job behavior

The existing pinned physical public-Encoder job runs its mock positive/negative
physical trainer tests in normal and `python -O` modes, then trains **32
additional real-public IID private Q24 models** using its own newly created
64-fit data. Sanitized `training-receipt.json` may be archived; raw training
labels and actual model tensor files are intentionally excluded from the
public GitHub artifact. No production deployment state or model winner is
modified. The full exact-head hosted test result remains a separate gate.

**No main merge, physical Cell Split, CNS route cutover, control-owner grant or
Final-use authorization.**
