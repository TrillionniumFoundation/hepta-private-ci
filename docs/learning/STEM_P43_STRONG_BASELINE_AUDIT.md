# P43 — independent strong-baseline gain audit (shadow only)

This follows P39 (real COCO photo/caption source-pair classification), P40/P41
(native task Head and fanout), and P42 (frozen train-only cosine comparison).
It is an independent, source-bound audit, not a replacement learning arm.

## Original source pins

- P39 retained archive SHA256:
  2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e
- Original cohort SHA256:
  4d7eec98a8546f8af64b0a5f2b4f192b30c6c43cb086f73f67bb0793a4509d63
- Frozen feature-bank manifest SHA256:
  e620c7ac8264979136cf39d992ddd575ab37c71baa6a729269af41bc42ca290d
- Original 256-row P39 prediction file Git blob:
  049ae2a390bb5fbb3d52deb21065af38fcd78bdc

P42 fits two logistic scalars on original training source pairs and selects
temperature on calibration alone. The original P39 test was already inspected.
Neither P42 nor P43 is a new prospective, blinded semantic trial.

## Source-bound audit

The verifier aligns original Head and cheap cosine observations by all 256
original row IDs; validates the real source/feature provenance and 64 complete
two-photo/four-pair groups; rejects cross-block ID and image-byte duplication,
forged labels, missing rows, invalid probabilities, redefined acceptance and
self-declared authority; and independently computes:

- classification accuracy, balanced accuracy, minority recall and specificity;
- confidence coverage at the *unchanged* 0.70 threshold, accepted errors,
  and accepted-error risk for both Head and frozen cosine;
- complete pair-block-aggregated Head-minus-cheap accuracy difference and
  independent 2,000-bootstrap one-sided 95% interval;
- reported cosine NLL against per-row probabilities when mathematically
  identifiable; saturated probabilities retain an explicit nonidentifiability
  marker rather than a fabricated recomputed NLL.

An exploratory, post-hoc screen flags whether Head-minus-cheap accuracy >=2pp,
independent paired lower-95% >0, Head minority recall >=90%, Head coverage
>=80%, and Head accepted-error risk <=5%. These thresholds were written
*after* researchers saw the original P39 test and are NOT preregistered
confirmation criteria. Screen success is NOT scientific or product admission.

## Engineering validation and replay

The dedicated exact-head CI runs 20 synthetic adversarial unit tests, restores
the original fixed P39 archive, executes the fixed P42 train-only cosine
calibration, and independently rechecks the complete P39 Head ledger. It
retains real per-row, paired and CPU-only replay results. Synthetic fixtures
are never model quality evidence.

After restoring the P39 archive and running P42 into /tmp/p42-result:

    python qa/stem-bakeoff/paired_gain_audit.py \
      --plan /tmp/p42-result/plan.json \
      --report /tmp/p42-result/report.json \
      --baseline-rows /tmp/p42-result/test-rows.json \
      --primary qa/stem-bakeoff/evidence/20261022-real-multimodal/primary-predictions.json \
      --output /tmp/p43-audit.json

Audit successful or not, production and action authority remain exactly
SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. An engineering CI green means the
diagnostic was calculated correctly; it never authorizes a Cell.

## Blockers not closed here

New image-family/entity-disjoint semantic hard-negative cohorts, original
pretraining-contamination bounds, independently evaluated semantic outcomes,
native Windows FILE_DELETE_CHILD isolation, original product Agentd/FinalUse
paths, learned nonzero-state Action/Value/Uncertainty episodes, and actual
target-device full Encoder+Head+queue p95/p99 and energy remain open.

A genuinely prospective trial must freeze all cohorts, categories, budgets,
controls, thresholds, paired uncertainty and failure rules before inspecting
the terminal test set. Avoid reusing P39 or P42 holdout results for promotion.
