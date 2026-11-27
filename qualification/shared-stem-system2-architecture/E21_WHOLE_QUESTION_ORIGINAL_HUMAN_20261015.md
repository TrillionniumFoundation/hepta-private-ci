# E21: Whole-question original-human E15 replication and negative evidence (research only)

**Date:** 2026-10-15. **Authorization:** `DENY_ALL`. Child of E20 #2242, which inherits #2195 E15, #2205 E16 and the original E14 source. No production Neuron, NDU, Reader, model selector, Q24/Q32 wire, Artifact CAS, Evidence WAL, FinalUse, blocking-ci or main mutation. No new pretrained weights or forward passes.

## What changed scientifically

Original E15 four-fold out-of-passage (LOPO) trained **real** 3- and 5-parameter Heads on three groups of original public MultiRC human training labels per fold, and an independent scorer used the fourth original group. Two hosted sources independently completed the **same** 33 original held task scores on 4 passages / 8 questions. These results are real historical human-label scores; the prior authoring-side synthetic-label mechanism tests are NOT the primary result.

| E15 method | Human candidate correct / 33 | 2-class Brier | Per-passage correct counts, sorted original IDs |
| --- | ---: | ---: | --- |
| Frozen Conditioned | 16 | 0.6198974379 | 2, 5, 6, 3 |
| Frozen Mean-pool + Query | 17 | 0.4968649272 | 2, 4, 6, 5 |
| Frozen No-evidence | 16 | 0.5081489893 | 2, 4, 5, 5 |
| Frozen No-query | 19 | 0.6912318938 | 4, 4, 6, 5 |
| Learned 3-param gated | 16 | 0.5202617476 | 2, 5, 6, 3 |
| Learned 5-param linear | 17 | **0.4957882902** | 4, 4, 6, 3 |

5-parameter linear vs strongest frozen original Brier competitor Mean-pool + Query: candidate correct delta **0**; Brier difference **−0.0010766370**. Passage-wise count deltas **(+2, 0, 0, −2)**. Four passage-level sign flips cannot support any general model selection; for the observed count difference zero, exact descriptive 16-pattern sign flip returns p=1. Mean Brier improvement is small and the Head uses additional measured training/inference CPU plus unmeasured whole-service costs. Thus **not a cost-adjusted win**. The previously reported no-query 19/33 does not complete mixed-label questions because its score is constant within each original question. Do not optimize for raw candidate accuracy alone.

In the *source-head* original E15 hosted human receipt, self-observed additional two-Head train CPU = **11,027,953 ns**, held inference = **85,717 ns**. Synthetic-merge corresponding quantities are **14,802,880 ns** and **116,359 ns**. These are separate runner observations and not independently attested production costs; they are NOT summed with archived ModernBERT meters.

## Next actual original-human question-level test

Original E15 final summary reports counts by passage only. It lacks the **complete-question** pass/fail outcome, where each original question must classify *all its genuine positive and negative answers correctly*. E21 adds a read-only independent scorer that reconstructs all genuine human labels at the candidate IDs, uses the original E15 four immutable held-prediction artifacts, and computes:

1. Complete question success 0–8, complete passage success 0–4, candidate accuracy and 2-class Brier for all six unchanged arms.
2. Source-passage paired correct deltas; small-sample group-aware exact sign-flip diagnostic with only four clusters. Do not treat 33 dependent answers as 33 independent sources.
3. Byte-exact comparison against **both** successful original E15 independent human score ZIPs for original human totals, per-passage counts, exact source SHA and research-only status. Any disagreement **fails**, rather than taking a convenient positive score.
4. Training and evaluation work remains separately identifiable, and no FBSDE is reactivated or made a production caller.

### Immutable actual-archive dependencies

- True pretrained ModernBERT Reader original (pre-score): Actions artifact `11946621518`, SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
- Successful E15 four source-head held-fold ZIP artifacts (IDs and SHA values embedded in `e21_whole_question.py`): `11949475467`, `11948693014`, `11949330575`, `11948993287`. Freeze original E15 source `d4d71baa8c00821fe385c1a47ed7b68b4255ad6e` and each original E15 ZIP and held prediction member.
- **Two** successful independent original E15 source/merge score ZIPs: `11950611472` (SHA `f332ab92181a0e088d941dbf4c77165ab2e4c40e48e9bbda4915e8d1543aceb8`), `11950935731` (SHA `63da90cb7da7f2f6ef478e44731e548a62a4b3c1a071593864f23b5896290acc`). Compare exact archival score report and per-passage vectors; CPU timings deliberately vary.
- True original human annotations: `aps/super_glue` @ `4e14482c58d790d467ecfb29b6790e1917bf8756`, validation parquet SHA `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`.

**The first CI job has NO human label parquet and no E15 human score ZIPs.** It imports only two original *pre-score* archive members from the original ZIP and four separate held-prediction ZIPs, seals predictions. The second job separately downloads the original human source and both E15 already-sealed human reviews, independently reconstructs labels and recomputes actual complete-question success after the blind job succeeds. Public human labels are not secret; process separation is a leakage-control convention, not cryptographic nonaccess proof. Dataset contamination, permissions and observer signing are not established by SHA-256.

The E15 original fold models have already physically trained. E21 does **not** retrain, compare alternate hyperparameters, infer a new future outcome or add a second service model loader. The Stage 1 tests use real original pretrained model logits without human labels; Stage 2 original-label job tests are run only after all blind assets are sealed. Source-head and synthetic-merge are distinct protected research paths; retain failures and never count queued jobs green.

## Test and next decision

```bash
# Actual original source ZIPs are mandatory, exported by the workflow:
PYTHONPATH=qualification/shared-stem-system2-architecture \
  python -m unittest discover -s qualification/shared-stem-system2-architecture \
    -p test_e21_blind_only.py -v

# Only in the post-seal original-label evidence-review job:
PYTHONPATH=qualification/shared-stem-system2-architecture \
  python -m unittest discover -s qualification/shared-stem-system2-architecture \
    -p test_e21_whole_question.py -v
```

Even if learned E15 wins *one* original question, it is a selected single retrospective source family of only four passages. An E16 result must be audited under its **own exact SHA and real held labels** rather than mixing with E15. Independent future-time/source groups, enough statistical power, Reader evidence sufficiency, task utility above matched total costs, original FinalUse/CAS/WAL and full blocking-ci/Architecture remain necessary for any decision. **`production_accepted=false`, `real_future_group_gain=false`, `cost_adjusted_system2_gain=false`, `fbsde_reactivation_allowed=false`**. Keep Draft / `DENY_ALL`, no merge or deployment.
