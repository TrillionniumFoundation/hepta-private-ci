# Real public IID: 32 trained Q24 Cells × 32 official heldout cases

**DRAFT / SHADOW_ONLY / DENY_ALL / NO_MODEL_SELECTION.**

This is a **static public intent classification canary** attached to research
PR #2510, stacked on PR #2506 (real 32D input/case/fit-only-label binder),
PR #2499 (physical real ModernBERT 768→32D train-only PCA Q24 feature producer),
and the unchanged original pretrained+public-BANKING77 study PR #1825.
The original deployed no-change V1 owner is NOT present or fabricated.

## Physical training and custody protocol

Training *first*, using only public BANKING77 original 64 registered fit
samples and 4 one-vs-rest binary class labels:

- 4 class tasks × 4 mechanisms (V2, Gated V3, Diagonal SSM, low-rank minGRU) ×
  2 **actual serialized file byte** budgets (8192/32768) = **32 distinct
  physically persisted private model safetensors files**.
- Exactly 8 epochs; 4 batches of 16 per epoch; **32 actual optimizer steps
  and 512 single-event sample exposures per model**. Identical seeded
  permutation/minibatch schedule across all candidates. They have unequal
  parameter counts and FLOPs due to different physical tensor geometry.
- Each utterance gets a cold-start private state; no invented inter-utterance
  event ordering, state transition, or future-window measurement.
- After training, verify file byte count, tensor count, complete weight SHA,
  cap, rank and create-once training receipt. The trainer never opens official
  heldout Q24 features or observer labels. It cannot grant model authority.

**Independent scorer is a different Python process**; it starts only AFTER
all 32 model tensors and their training ledger have been sealed. It reopens
the original pinned PolyAI BANKING77 train/test material with the original
frozen source SHA and recomputes the same 32 heldout IDs and *original
observer labels*. This is separate program execution, **not** OS-isolated,
independently signed evaluation-owner custody.

For each of 32 trained candidate models and 32 heldout public cases, the
scorer constructs a **one-event, non-chronological** Q24 trace, launches
**two independent fresh Rust OS processes**, reopens the physical source
safetensors, and uses the existing independent Python signed-Q24 Adapter
and Head integer oracle to recheck both cold replays, model digest,
single-tick frontier and exact Q24 Head logit.

**Required complete native count: 32 × 32 × 2 = 2,048 OS processes and
1,024 independent integer event pairs**, not 2,048 independent task cases.
A missing or failed model/heldout event blocks the entire report.

## Evaluation: denominator, abstention and calibration

There are exactly **32 heldout public original text cases**, 8 positives
and 24 negatives per one-vs-rest binary task. The scorer records per
task/candidate the raw 32-case denominator, accepted decision count,
ambiguous native Q24 Head margin abstentions, positive recall (n=8),
negative specificity (n=24), coverage and **delivered accuracy**, where
all abstentions count as incorrect. No label-dependent tuning, model
selection, confidence threshold tuning or multiple-testing significance
claim is supported. Accuracy numbers, if produced, describe this small
fixed public 4-intent IID task only.

The Rust kernel requires a `monotonic_micros` integer for its API:
for these completely independent one-event model process calls, the
synthetic constant 1 is an **API-only clock primitive**, not an original
BANKING77 event timestamp or a future observation. The model state is
destroyed after the first tick. This does not test sequential retention.

## Strict scientific blockers retained

- No original A0 selected deployed V1 frozen no-change model/weights/owner;
  the separate binary task comparators may not be named V1 baselines.
- No prospective future task window, independently verified negative transfer,
  old-task retention or independently signed NDU evaluation, selector or
  Executor.
- No valid study-wide matching of full training FLOPs, model RSS, original
  complete shared Encoder + Worker inference cost or fault/recovery p95/p99
  on 64/256/1024/4096 actual Cells.
- No signed final-use, artifact CAS, generation fence, routing cutover,
  production NDU eligibility, governance or promotion.

All quality/weight results remain `NO_MODEL_SELECTION` and `DENY_ALL`.
Hosted exact-head real pretrained model, 32 full training files, 2,048
Q24 subprocesses, strict unit tests, architecture and global blocking CI
must successfully run before describing the observed accuracy as real.
