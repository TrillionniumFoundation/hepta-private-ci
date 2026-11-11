# HPCA B2: source-pinned rank discrimination on retained CPU forwards

**HOLD_NO_GO / DENY_ALL.** This is a new, read-only arithmetic diagnostic
of the **existing** 540 operator-produced forward scores, not new model
training or an independent model/evaluator run. No calibration threshold is
fit or adopted. It neither proves neuroscience mechanisms nor authenticates
the original observations.

## Frozen source and data

- Parent/source: original [B2 collapse audit #6020](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6020) HEAD
  `7a887343015043351da5b0560121dee6a248a434`,
  parent `0ed4fce8bd07d361bf7eba40c40fe73d1f349c66`.
- Fixed result SHA-256 `937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731`.
- Fixed task manifest SHA-256 `0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a`.
- Original operator-scored model: SmolLM2-135M-Instruct, base plus
  four matched seeds 11,17,23,29 for two LoRA scheduling arms.
  Original retained evaluation covers 60 arithmetic prompts in five families,
  six YES and six NO per family. There is no independent future B.
- The script reuses the baseline `posttrain_b2_reaudit.audit` before
  calculating any new ranks; that earlier audit checks original
  model/seed/task/score identity, row arithmetic and HOLD authority.

## New threshold-free diagnosis

For every run, compute exact *integer* twice-win count over every
YES-versus-NO score pair: two for higher P(YES) on a YES task, one
for a tie and zero for an inverted ranking. Divide by twice the total
positive-negative pair count to obtain ROC AUC.

| Actual retained run | Pooled AUC, 30 x 30 YES/NO pairs |
| --- | ---: |
| Frozen base | 0.435556 |
| Interleaved seed 11 / Bursty seed 11 | 0.438889 / 0.438889 |
| Interleaved seed 17 / Bursty seed 17 | 0.436667 / 0.436667 |
| Interleaved seed 23 / Bursty seed 23 | 0.443333 / 0.444444 |
| Interleaved seed 29 / Bursty seed 29 | 0.434444 / 0.434444 |

All nine original runs had P(YES) below 0.5 on every task and all
nine pooled AUCs are below 0.5. Therefore the previously observed 540/540
NO decisions are **not merely evidence of a poor fixed classification
threshold**: even before thresholding, the overall operator task
ranking trends in the wrong direction on these frozen rows.

This is **not uniform across task families**. In the frozen base,
comparison AUC was 0.111111, even AUC 0.194444,
prime AUC 0.388889, set-membership AUC 0.416667, while
divisibility AUC was 0.777778. The later eight runs retain
comparison around 0.111111-0.138889 and divisibility around
0.777778-0.805556. Every family contains only 12 operator-made tasks.
Pooled cross-family comparisons and family-conditioned rankings measure
different things; neither may be silently relabeled as prospective accuracy.

No heldout/calibration partition is available to select an optimal threshold.
Any threshold selected on these same 60 tasks would be **resubstitution**
and not an independent improvement. Do not invert the prediction labels
or fit a threshold from these ranks and call it a tested model gain.
The exact arithmetic rule control and negative B2 outcome remain governed
by their own PRs; these identical task rows are not nine independent samples.

## Executed checks and cost boundary

- Local HeptaRuntime ai395 isolated worktree, same frozen B2 data;
  17/17 Python tests passed: eight previous source/score checks and nine
  new rank/identity/adversarial controls. No old HPCA micro smoke rerun.
- New rank tests cover complete seed/arm/label roster, exact integer pair
  accounting, family stratification, stable row permutation, monotone
  probability transforms, reversed-label complement, ties, invalid
  probabilities, and original-score/label tampering rejection.
- The generated `POSTTRAIN_B2_RANK_REPORT.json` was independently
  recomputed from the pinned originals and compared byte-for-byte
  (successful `cmp`, exit 0).
- Tests: wall 0.03 sec, user CPU 0.03 sec, max RSS 22,892 KiB;
  report regeneration: wall 0.02 sec, user CPU 0.02 sec,
  max RSS 21,600 KiB. See original untouched
  `POSTTRAIN_B2_RANK_TEST.log` and
  `POSTTRAIN_B2_RANK_GENERATION.log`.
- Earlier original scoring process totals, **not rerun here**:
  nine process CPU times sum to 92.954481356 seconds;
  nine individual wall durations sum to 24.313295296 seconds,
  peak per-process RSS 1,242,076 KiB. These cannot be interpreted
  as complete experiment lifecycle cost or sequential wall time.
  Training, retries, external hosting, networking and owner verification
  remain unmeasured in this rank audit.

These new ranks are a negative diagnostic, not a new generalization claim
or proof the adapted weights are useless on independent arithmetic tasks.
Next qualified action requires an externally frozen, independently
evaluated task cohort with locked base/LoRA and exact-rule baselines,
matched action/effect owner receipts, resource budgets, NoUpdate/Adopt
and different subsequent task/cold-recovery checks. The scientific and
production gate remains **HOLD_NO_GO / DENY_ALL**.
