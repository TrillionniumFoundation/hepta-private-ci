# E26: Actual five-parameter Head investment on the six genuine E25 MultiRC passages

**RESEARCH ONLY · DRAFT · DENY_ALL · NO MAIN MERGE · NO MODEL PROMOTION**

## Evidence and the testable question

Earlier NDU–Merton work had tested actual tiny Head training over **four previously examined** MultiRC source passages and a separate AG News task. This E26 continuation uses the exact original successful [E25 source-head run 38727583089](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38727583089) to assess **Head investment choices on six original, passage-disjoint MultiRC source passages, 12 whole questions and all 51 native candidate answers**. The six passages are disjoint from the previous four, **not** a new independent dataset family, new calendar window or fresh external publisher. The original E25 source labels/results have already appeared in preceding research, so this continuation is a **posthoc retrospective new-control study**, not a prospective holdout trial. Do not market it as independently preregistered.

Authentic original pretrained ModernBERT/four Reader source logits come from source ZIP `11946621518` (SHA `1a9b...`) and the actual E25 model ZIP `12010699818` (SHA `d1ff...`). E25's original public source ZIP `11991113170` (SHA `b8ea...`) contains a complete source/answer slate without held truth. Four original **E15 historical TRAIN-only** owner-fold ZIPs (`11949081037`, `11948881417`, `11948806536`, `11948681555`) each exclude its own historical held passage. The newer E25 human owner ZIP `11991387730` is **not downloaded in the producer job** and is first opened by the separate reviewer job after prelabel attempt sealing. Original external E25 score ZIP `12018967923` is an independent reference for the 48-step E16 control.

All nine ZIPs are pinned by exact artifact IDs, SHA256, and original member inventory. The separate download helper splits GitHub bearer REST authorization from an uncredentialed and hostname/HTTPS-approved signed object-store redirect. Missing/changed artifacts fail closed; no simulated or historical alternate source can substitute for the actual six-passage records. ZIP hashes provide integrity, **not** independent publisher signatures.

## Real CPU learning protocol (retrospectively registered; not prospective)

Same original question-centering and train-only normalization as E16. Each historical fourfold Head has **five float64 scalar parameters**, all-zero initialization, full-batch genuine Brier-loss SGD, learning rate 0.5, nonbias L2=0.001. Candidate training depths are **0, 8, 32, 48** updates. The 48-step ensemble's 51 probabilities are **bit-identical** to E25's externally archived frozen E16 scaled-Brier Head predictions. This is a strong numerical lineage regression; no Encoder or pretrained Reader is re-run by this study.

Seven controls are `no_update`, `fixed_8`, `fixed_48`, `calibrated_neutral`, `calibrated_fixed_risk`, `ndu_discrete`, `ordinary_same_profile`. The last four independently fit three **distinct physical 48-update** inner pilots per outer fold, each trained on two of the three historically available source groups and evaluated using labels of the third. The originally held outer group's labels and E25's new labels never enter any pilot. They choose a depth by calibrated whole-question success, minimum held-group success, a small Brier tie-break, and a **declared 0.001 utility-per-update tariff**. The NDU-inspired arm's bounded alpha uses only these old calibration outcomes; `ordinary_same_profile` explicitly enumerates the same ordinary augmented-state fixed objective and must choose identically. Neither is a neural preference learner or globally consistent FBSDE.

**All seven controls train their own individual Heads. There is no cross-arm free sharing of pilots**; total physically executed producer optimizer updates across all seven arms are 2,752 per completed Python-mode study. Per arm, `fixed_8` requires 32 updates, frozen `fixed_48` 192, and all calibrated selection controls **632**, including **576** actual pilot SGD updates and **56** final fitting updates. Pilot, final fit, selection and 51-candidate inference CPU are separately metered. Original pretrained Encoder/load/inference, stored feature preparation, audit, hardware instruction count, energy, p95 and total online service costs are NOT thereby measured; the tariff is **not** dollars or CPU milliseconds.

## Real completed isolated-container observations

| Control | Complete questions / 12 | Correct candidates / 51 | Executed SGD updates (all pilots) |
|---|---:|---:|---:|
| No update | 1 | 28 | 0 |
| Fixed8 | **1** | **34** | **32** |
| Fixed48 (exact original E16) | 1 | 33 | 192 |
| Calibrated neutral | 1 | 31 | 632 |
| Calibrated fixed risk | 1 | 31 | 632 |
| NDU-inspired discrete | **1** | **31** | **632** |
| Ordinary same-profile | 1 | 31 | 632 |

No NDU-specific rescue. All calibrated arm outcomes are identical to their ordinary same-objective reference; NDU consumes far more paid training than fixed8. This is not a theorem against general NDU, not a prospective family-level efficacy study, and not permission to promote any model. Candidate successes are correlated within twelve questions and six passages; they cannot be treated as 51 independent source groups. The source E25 fixed48 native Brier=0.4494438404024535 is reconstructed from original postseal labels.

## Reproducibility and custody

The producer is stdlib-only and sees **only the original E15 TRAIN labels**, not the E25 owner labels. It writes a create-only sealed attempt with all fourfold learned weights, **separately executed** pilot checkpoints, scales, decisions, per-arm predictions and phase-cost counters. The independent reviewer uses a **separate NumPy SGD implementation**, reconstructs original logits, old training labels, each inner pilot's every checkpoint, selected objective, full outer fits and 51 original predictions, then opens E25 human labels *after* the seal. The reviewer independently computes candidate Brier and exact whole-question outcomes and checks the archived E25 E16 score. This is separate authored code/process but **not an independently signed reviewer or hardware host**.

The standalone read-only source/merge GitHub workflow first checks immutable original E25 run status and artifacts, runs BLIND producer in one job and a separately dependent HUMAN reviewer in another; model job never downloads new owner truth. Run both ordinary and `python -O`; do not treat two modes as independent task populations. A test or workflow `success` does not grant FinalUse, model selection or production NDU authority. Global blocking-ci and Architecture remain mandatory. No old workflows are disabled or bypassed.
