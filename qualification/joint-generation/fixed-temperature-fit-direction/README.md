# Fixed-temperature FIT directional preflight: numerical domain refusal

**The engineering screen and scientific quality are NOT EVALUATED.** All 28 literal tests passed, but the first fixed-temperature gradient was outside its unchanged numerical domain. No direction update or sentinel comparison occurred. This is neither a generation-quality win nor a quality negative.

The completed fixed-temperature chain qualification established only finite literal cases. This prospective FIT-only preflight tested whether its gradient could support a new direction diagnostic on four source-masked bases (folds 0/1, seeds 103/107), rather than immediately launching a larger training comparison. The original normalized-coupled training negatives remain final; this is not an attempt to relabel them as unresolved numeric failures.

## Frozen comparison and actual stopping point

All four bases were freshly recreated with the original 300 decoder and 500 source-label pretraining steps, and all four historical parameter digests reproduced. Eight temperatures were fitted on each base's original FIT full/low observations with the existing [.125,8] interval and 28 evaluations/head. The global base/temperature barrier completed before any direction computation.

The planned directions were independent A/N, coupled tau=1 N, and fixed-temperature A/N, each with the unchanged ordinary aligned anchor .2. Each base had eight predetermined partial-command FIT gradient groups and eight disjoint FIT sentinel groups. Sentinels were already used in pretraining/temperature fitting: they were never claimed as blind or model-unseen groups. All twenty parameter gradients had to complete before twenty native fresh-moment Adam updates and twenty equal-norm explicit parameter perturbations could be constructed; all forty variants then had to freeze before sentinel evaluation. The strict launch screen was explicitly separate from the unchanged scientific +.005/no-regression gates.

Actual prefix on the first base, fold0/seed103:

1. One 64-row gradient batch and all four independent A/N branches completed.
2. The old normalized coupled tau=1 N gradient completed on the same batch.
3. The first new fixed-temperature **A** gradient, with both fitted temperatures **8**, rejected: `positive exact min tie: no classical derivative selected`.
4. The one predeclared whole-batch forward diagnostic completed, then the exception was re-raised and the child fully waited. No row was omitted and no second temperature/seed was tried.

The whole 64-row diagnostic found **56 rows with at least one represented positive min tie**, minimum active residual **0**, maximum relative residual-mass imbalance **1**, and zero rows with both residual denominators zero. These are aggregates of the represented powered marginals, not proof that their exact real-number counterparts are equal. The first rejection was the tie guard; the additional statistics also expose unresolved residual arithmetic. No epsilon, denominator floor, arbitrary subgradient, tau reduction, row mask or guard relaxation was applied.

**Zero clones, zero parameter-gradient pullbacks, zero direction Adam updates, zero norm perturbations and zero sentinel evaluations.** There were still 1200 decoder and 2000 supervised preparation updates; “zero direction updates” must not be mistaken for zero training cost. No RESULT success artifact or all-steps barrier was produced. Later bases' directions were not attempted under the predeclared whole-campaign stop rule, even though their base preparations and temperatures had completed.

## Completed FIT temperatures

| Base | Text inverse temperature | Image inverse temperature |
|---|---:|---:|
| Fold0, seed103 | 8 (upper boundary) | 8 (upper boundary) |
| Fold0, seed107 | 3.634272289 | 3.485699702 |
| Fold1, seed103 | 7.172455739 | 8 (upper boundary) |
| Fold1, seed107 | 5.385994833 | 4.464043085 |

This establishes a practical domain barrier for this fixed preflight, not a failure of the qualified chain rule, a global impossibility theorem, or evidence that NDU improves/worsens generation. The larger training launch is not justified by an unevaluated screen. Its score thresholds were not weakened.

## Actual complete cost

Fully waited exit1: **2.906249 CPU seconds**, 2.935952 wall seconds, **62748 KiB RSS**, under 10 CPU / 45 wall / 512 MiB / 4 MiB, CPU0 and one numerical thread with the existing synthetic lock. No timeout or retry. Whole CPU includes all 28 tests, source checks, new FIT generation, four bases, eight temperature fits, attempted gradients and the one aggregate diagnostic.

Actual prefix: 4009 forwards / 262304 rows, 1208 decodes / 14496 images, two FIT datasets and zero VAL/TEST datasets. Calibration used 8 heads / 12480 head rows, 224 NLL evaluations / 349440 head-row evaluations, and 6240 FIT serving tables. The old tau1 call completed once; the new fixed-tau call was attempted once and completed zero times. All Python SHA256 work was instrumented: 6605 constructions, 6957546 input bytes, zero copies. Supervisor hashing is outside those child counters and not asserted free.

SUMMARY retains every completed per-base preparation/FIT timing, FIT generation cost, current failed-phase/direction elapsed CPU, the entire actual-prefix ledger, all four frozen base/temperature records and full wait4 receipt. Unknown or uncategorized tails remain included in whole child CPU, not zero. The prior 1.007076-second literal qualification, older research, source/review work and supervisor tails are additional history.

## Portable model-free helpers

```sh
python -B -m unittest -v test_direction_helpers
```

The two tests cover the fixed partial-group split and equal-parameter-norm perturbation helper. The run also reran all 26 previously qualified chain tests before FIT generation. Equal global parameter norm controls one displacement-size confound; it does not imply equal function-space movement or unbiased Adam, and no perturbation was actually reached here.

Only portable helpers/tests, the executed prospective plan and complete aggregate failure evidence are published. No model weights, private input arrays, per-request model predictions or runtime paths. No default change, deployment, unrestricted scientific runner, skipped-row continuation or hidden retry.
