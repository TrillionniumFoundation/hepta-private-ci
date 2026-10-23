# P42 — cheap cosine baseline for the real COCO source-pairing loop

Scope: a research-only, post-hoc follow-up to P39 (#3122), P40 (#3222)
and P41 (#3227). The original P39 test has already been examined. P42
is **not** another blind trial, model promotion or production authority.

## Motivation and existing observations

P39 uses 384 real original COCO val2017 photos and human captions, with
128/64/64/128 original-photo train/dev/calibration/test splits. The 256-row
test has 64 complete two-photo pairing blocks, balanced source identities
and frozen image/text features. Its preregistered gated joint Head scored
251/256, with 125/128 positive recall and 255/256 accepted at confidence
0.70. The interacting-feature linear joint Head scored 250/256 with better
NLL, so gated superiority is not established. Each modality-only Head
scored 128/256 by construction of the paired labels.

The independent P39 audit observes raw frozen text/image cosine AUROC
0.99646 on these same test rows. Thus the source-pairing research screen
does not measure how much accuracy the private Head learning adds above
the cheap cross-modal representation already present in its foundation
Encoder. The cosine baseline is a necessary additional descriptive
comparison, not a semantic-competence trial.

## Protocol and immutable inputs

The P42 runner requires three externally fixed source identities:

- P39 archive SHA256: 2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e
- P39 cohort manifest SHA256: 4d7eec98a8546f8af64b0a5f2b4f192b30c6c43cb086f73f67bb0793a4509d63
- P39 feature-bank manifest SHA256: e620c7ac8264979136cf39d992ddd575ab37c71baa6a729269af41bc42ca290d

It verifies used archive member byte lengths and hashes, exact feature tensor
digest, 2x2 source blocks, disjoint image/caption endpoints and the original
retained gated Head prediction ledger. No new photograph is acquired and no
model or image tower is run.

The cheap control uses only cosine of the original source caption vector
and the proposed image vector. It fits a regularized two-scalar logistic
calibrator using TRAIN labels alone and chooses a temperature from the
original fixed grid using CALIBRATION labels alone. The original 0.70
confidence threshold is unchanged. Neither dev nor the original test may
choose the classifier, threshold or temperature.

The resulting evidence stores every test row's source identities, source
hashes, cosine, calibrated probability, cheap prediction/acceptance and
the original learned Head prediction. It reports accuracy, balanced
accuracy, positive recall, coverage, selective risk, NLL and an empirical
64-pair-block bootstrap comparison. All measured costs are explicitly
HEADLESS FROZEN-BANK REPLAY; they exclude pretrained Encoder, queueing,
target device and energy. The report always says new_blind_trial=false,
semantic_quality_qualified=false and production_activation_allowed=false.

## Reproduction

From the repository root after installing NumPy 2.2.6:

    python qa/stem-bakeoff/multimodal_evidence.py \
      --directory qa/stem-bakeoff/evidence/20261022-real-multimodal \
      --manifest-sha256 2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e \
      --output /tmp/p42-original

    python qa/stem-bakeoff/cheap_cosine_control.py \
      --restored /tmp/p42-original \
      --archive-manifest qa/stem-bakeoff/evidence/20261022-real-multimodal/archive-manifest.json \
      --output /tmp/p42-result

The hepta-cheap-cosine-shadow GitHub workflow executes exact-source
negative tests, restores all original archive members, runs the cheap
control and retains the complete 256-row comparison/receipts. It also
checks the immutable P39 primary 251/256 witness. A green P42 job means
the post-hoc cheap baseline is reproducible; it does not admit the
baseline or supersede any inherited blocking CI.

## Remaining blockers: do not promote

The main image/caption source-pair loop is complete within its original
preregistered research scope. A hard real-world semantic-negative task
and independent new source/entity cohort are still needed to establish
general visual-semantic learning and Head benefits beyond frozen cosine.
Missing modalities in the raw Head caused high-confidence errors; use
the separately verified required-modality guard, not confidence as
presence evidence. Neither gated architecture superiority nor foundation
pretraining decontamination has been proven.

Live product episodes, nonzero Cell state and genuinely trained
Task/Action/Value/Uncertainty policy need separate outcome receipts.
Target devices have not supplied full Encoder+Head+queue p95/p99,
measured energy and sustained 4096 independently learned Cell workloads.

Most critically, native Windows restricted-token DELETE escape via
parent FILE_DELETE_CHILD has been reproduced on real runners. Global
Windows/native/macOS CI is not fully passing on the integrated source.
Do not weaken the original containment assertions or borrow green
checks from earlier unrelated SHAs.

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**
