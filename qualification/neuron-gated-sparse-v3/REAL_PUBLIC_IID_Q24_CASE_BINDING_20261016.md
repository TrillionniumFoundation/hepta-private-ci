# Real public Q24 inputs: fit-only labels and blind heldout, without invented time

**Research only — DRAFT / DENY_ALL / no real model selection or production effects.**

## Controlling physical parent and source owners

This research descendant requires the physical ModernBERT→32D Q24 Feature Snapshot
producer from PR #2499 (exact initial SHA `29680c069b67d1bbf49a0beb1425fca38503fad6`).
It uses the genuine `answerdotai/ModernBERT-base` fixed HF model revision
`8949b909ec900327062f0ebf497f51aef5e6f0c8`, and the frozen original
public BANKING77 data selector owned by source commit
`758205d3de23ccbf76649b1446c271101dc917b0`.
Original 4-intent BANKING77 source remains at PolyAI Git commit
`57ec275d8078af65b7731c2a98be812d844a6d6b` (CC-BY-4.0).

The read-only task binder **re-reads the actual original train/test CSV files**,
checks the pinned Git blob SHA and source MATERIAL SHA, reconstructs the exact
original 64-fit / 32-heldout case IDs using unchanged original `prepare`, and
rechecks the original producer's physically saved Q24 Feature Snapshot,
train-only PCA `projection.safetensors`, registry, model identity and receipt.

It emits, via create-once files, three distinct research inputs:

- `fit-only-q24.json`: exactly 64 authentic public training-case Q24 32D
  features, source-text SHA, ID and their **four-class training labels**.
  The training input is never archived in the research Actions artifact.
- `heldout-unlabeled-q24.json`: exactly 32 genuine heldout case IDs,
  public-source text SHA and Q24 features. **No class label** and no model
  prediction. It is safe to publish as a small public-data study artifact.
- `predeclared-iid-plan.json`: exact 4 pre-registered one-vs-rest binary
  tasks, four temporal mechanism candidates, 8KiB/32KiB byte budgets and
  explicit remaining evidence blockers. Its exact source feature digest
  is the same as the fit and heldout file.

Both test/feature partitions are checked again against the original physically
bound public inputs. No heldout-label CSV values reach the candidate data
composer. The original source's heldout labels are loaded by
`banking77_material.prepare` (as part of reconstructing immutable case IDs)
but immediately discarded; this is logical software separation, **not**
independent process/OS custody or proof the original CSV cannot be read.

## Why IID, not longitudinal evidence

BANKING77 is a public collection of **unsequenced utterances**, with no
verified per-case event timestamp or temporal state transition. Assigning
synthetic timestamps then describing predictions as 'future' or calling the
samples repeated observations of one Cell would be scientifically invalid.

Therefore the new source profile is explicitly
`UNORDERED_IID_ONE_TICK_PER_CASE_NOT_FUTURE_OR_RETENTION`.
The binder does **not** invent `event_time_utc` or `sequence` properties.
Future temporal learning, checkpoint recovery, retained knowledge,
causal negative transfer, 64–4096 real Cell scaling and signed NDU remain
unmeasured. The original deployed V1 no-change baseline remains unavailable:
no fake V1 weight, authority or checkpoint may substitute for it.

## CI and next admissible scientific step

The dedicated real ModernBERT job, when it physically succeeds, now runs the
binder using the freshly downloaded and verified original public dataset
and 96-case physically produced Feature Snapshot. Twelve pure-Python negative
and positive tests run normally and under Python `-O`. The job checks that
the original train-only case IDs and exact 32D physical feature identities
match before any training, and retains only unlabeled heldout and no-authority
preregistration evidence; it does not re-archive public training labels.

This enables a **later** physically executed public-data *IID one-tick*
classification canary, which must be a separately versioned experiment.
Only a temporally valid dataset with genuine event/time/group and independent
future labels could support a temporal-cell learning/retention claim.
At no point does this profile authorize `main` merge, model promotion,
CNS cutover, Final-use or physical Cell Split.
