# E2 learned Head frontier on the exact E1 Encoder bank

**Research-only, DENY_ALL.** This is additive to the pinned, public English-only E1 CPU pilot in [E1_REAL_PUBLIC_PILOT.md](E1_REAL_PUBLIC_PILOT.md). It does **not** load a second foundation Encoder, train backbone LoRA, grant production Cell capability, or claim independently signed NDU outcomes.

## Actual trainable implementations

Each of the three E1 Encoder executions now also invokes `e2_feature_residual_study.py` from the same Python process **after** the one-time frozen, scoped Q24 feature bank is produced. It does not re-encode, re-fetch or reload the source model for E2. An additional create-only `--e2-output` path holds a bound E2 result; the E1 output is written first and remains available if E2 fitting fails.

Actual runnable arms, all on the same 128 TRAIN rows and on separate 32 CAL / 64 TEST partitions:

| Arm | Status | Trainable Head parameters |
| --- | --- | --- |
| frozen_head | Matched frozen baseline initialized with fixed seed | 0 updates; frozen storage explicitly counted (770 at 384D, 514 at 256D) |
| from_zero | Original E1 SGD linear Head reproduced with same initialization/optimizer | 770 at 384D; 514 at 256D |
| cosine_prototype | Two L2 normalized class centroids fitted **using train labels** | 0 neural optimizer parameters, but fitted centroid storage and calculation are **not free** |
| residual_2k | Feature-gated residual, output projection initialized to exactly zero | At most 2,048 independently trainable weights |
| residual_8k | Same but larger rank | At most 8,192 independently trainable weights |
| residual_16k | Same but larger rank | At most 16,384 independently trainable weights |

The residual equation is a frozen original linear base plus a trainable low-rank correction. The correction is initialized to exactly zero and tested with bit-identical initial logits (not merely visually similar probabilities). The frozen base must remain byte-identical after SGD. Complete *trainable* parameters include down, gate, up and biases. Shared frozen base bytes are separately counted and never claimed free. This is **feature-gating of output vectors**, not the Cell's own 64D private state FiLM. Do not relabel it as a native Neuron v1 Cell-state experiment.

All trainable arms use real PyTorch SGD, the same fixed seed, 40 full-TRAIN-batch steps and learning rate 0.15, no pretrained parameter optimizer. Calibration-only grid searches choose the temperature; TEST labels never influence optimizer or calibration. Cosine centroids are fitted from TRAIN labels only. The returned training work is measured **separately for every Head**; when comparing standalone total cost each arm must be assigned the full Encoder feature cost, not only its incremental shared-campaign train time.

Before sealing E2 output, the source E1 runner replays the unchanged frozen and from-zero heads under this module and refuses E2 output if their per-case predictions drift by more than 1e-6 from the original E1 case predictions. A source-E1-report SHA256 binds the new E2 study to its actual parent report. Both are explicitly local integrity identities, not independent producer signatures.

## Independent scorer

`e2_residual_review.py` has no model dependency and reads the byte-frozen public panel, original E1 report, and its E2 report. It independently checks the complete six-arm case/option/partition parity, train identity and schedule, each full Head ceiling, true optimizer-step/weight-digest change, zero-initialized baseline match, source report SHA, original frozen/from-zero numeric replay, and no additional claimed Encoder calls. It recomputes TEST/CAL Accuracy, Brier and descriptive residual deltas. It does not compare against the genuine **production no-change** arm, establish held-out new-family longitudinal gain, supply calibration/OOD certification, or select a winner.

Example when the public-weight E1 model has actually executed:

```sh
python experiments/shared_stem_cell/e2_residual_review.py \
  --panel /approved/e1-public-panel.json \
  --e1 /sealed/granite_97m_r2.json \
  --e2 /sealed/granite_97m_r2.e2.json \
  --output /sealed/granite_97m_r2.e2-review.json
```

The existing three-model hosted Actions workflow runs independent scorer checks for all three Encoder candidates and uploads the exact create-only research reports, even if later arms fail. The full pretrained E1+E2 workflow may still be queued; an unrun or failed job does not count as pretrained learning evidence.

## Test receipts and limitations

Local Python/Torch CPU: `test_e2_feature_residual_study.py` **11/11** passed; `test_e2_residual_review.py` **12/12** passed using real numerical SGD on **synthetic** Q24-sized features. The original E1 versus E2 frozen/from-zero probability outputs also matched exactly on locally generated source fixtures. The remote test source was adjusted to import the exact existing E1 fixture name; hosted current-HEAD CI remains mandatory.

Incomplete acceptance: independent future1/2/3 outcome labels, language/code source families, a real production no-change baseline, Reader four-condition qualification, OOD, target hardware p99/RSS/energy, independent model origin, security blocking-ci and signed Worker/FinalUse/WAL/CAS. These cannot be substituted by this English-only retrospective panel.

**Every experiment remains `production_promotion_permitted=false` and `authority=DENY_ALL`.**

## Physical sharing correction (2026-10-14)

The first implementation accidentally made a separate deep copy of the frozen base linear Head inside each E2 residual arm. This would have made memory-advantage claims too optimistic. The corrected `FeatureGatedResidual` now refers to the **same frozen base module and weight tensor** for residual_2k, residual_8k and residual_16k during the single E2 study. It checks PyTorch `data_ptr()` identity before training and verifies the base tensor digest remains unchanged afterward. The independent reviewer requires the corresponding storage-sharing claim. The per-arm trainable parameter ceilings still apply only to genuinely updated residual weights; the shared frozen base is charged separately. This proves only same-process research tensor sharing, **not native multi-Worker zero-copy or actual 4,096 Cell storage**.

The corrected E2 module and reviewer Git blobs were both executed locally with pinned CPU Torch. Full selected E1/E2/E3/E4 local contract suite: 107/107 passing; the hosted exact-HEAD full pipeline and global blocking-ci remain mandatory.
