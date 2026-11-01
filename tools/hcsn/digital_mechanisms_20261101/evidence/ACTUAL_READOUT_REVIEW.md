# Actual-task before/after trained-readout audit

Post hoc descriptive trained-readout audit. Event, elapsed time, task flags, bank features and selected trajectories can change together. This is not maximum recoverable information, a randomized event/reset intervention, an independent task-utility contrast or an efficacy gate.

All 16 registered fits have successful confirmation process and FINISHED receipts. The audit covers both splits, all six non-CPU cell candidates and the value controller. It retains per-fit counts and paired observations; no model, primary contrast, threshold or protocol was changed.

## Join and estimand

Consecutive decisions are joined only when the complete successor task state exactly equals the next state, the transition has no READ completion or failure, fitted teacher belief is exactly unchanged, and the recorded transition is a fresh event or recovery. Latent-state continuity and stored squared errors are checked. Before/after squared error uses the same teacher belief. Positive paired change means worse readout error after the transition.

The main table pools transition pairs, matching the DEV descriptive join. These observations are dependent within episodes and fits. The separate equal-fit mean includes only fits with eligible pairs; empty fits stay explicitly empty, not zero-error. No significance tests are performed.

## First-passage brief table

| Split | Drive | Transition | Pairs | Contributing fits | MSE before | MSE after | Paired change | Equal-fit change |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| iid | sustained | event | 616 | 16/16 | 0.012698 | 0.018817 | 0.006119 | 0.007056 |
| iid | sustained | recovery | 307 | 16/16 | 0.027631 | 0.019330 | -0.008301 | -0.008868 |
| iid | impulse | event | 573 | 16/16 | 0.016296 | 0.017556 | 0.001260 | 0.001360 |
| iid | impulse | recovery | 263 | 16/16 | 0.026116 | 0.028633 | 0.002517 | 0.002933 |
| ood | sustained | event | 705 | 16/16 | 0.027369 | 0.042379 | 0.015009 | 0.015116 |
| ood | sustained | recovery | 354 | 16/16 | 0.053886 | 0.030281 | -0.023605 | -0.024797 |
| ood | impulse | event | 623 | 16/16 | 0.034288 | 0.034997 | 0.000708 | 0.000552 |
| ood | impulse | recovery | 334 | 16/16 | 0.044513 | 0.048933 | 0.004421 | 0.004582 |

## Complete candidate table

| Split | Candidate | Transition | Pairs | Contributing fits | MSE before | MSE after | Paired change |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| iid | ordinary_bank__structured_on | event | 0 | 0/16 | — | — | — |
| iid | ordinary_bank__structured_on | recovery | 0 | 0/16 | — | — | — |
| iid | ordinary_bank__impulse_on | event | 0 | 0/16 | — | — | — |
| iid | ordinary_bank__impulse_on | recovery | 0 | 0/16 | — | — | — |
| iid | clocked_bank__structured_on | event | 425 | 16/16 | 0.014654 | 0.020916 | 0.006261 |
| iid | clocked_bank__structured_on | recovery | 204 | 16/16 | 0.025777 | 0.016131 | -0.009646 |
| iid | clocked_bank__impulse_on | event | 327 | 16/16 | 0.018002 | 0.018719 | 0.000717 |
| iid | clocked_bank__impulse_on | recovery | 130 | 16/16 | 0.023931 | 0.025915 | 0.001983 |
| iid | first_passage_bank__structured_on | event | 616 | 16/16 | 0.012698 | 0.018817 | 0.006119 |
| iid | first_passage_bank__structured_on | recovery | 307 | 16/16 | 0.027631 | 0.019330 | -0.008301 |
| iid | first_passage_bank__impulse_on | event | 573 | 16/16 | 0.016296 | 0.017556 | 0.001260 |
| iid | first_passage_bank__impulse_on | recovery | 263 | 16/16 | 0.026116 | 0.028633 | 0.002517 |
| ood | ordinary_bank__structured_on | event | 0 | 0/16 | — | — | — |
| ood | ordinary_bank__structured_on | recovery | 0 | 0/16 | — | — | — |
| ood | ordinary_bank__impulse_on | event | 0 | 0/16 | — | — | — |
| ood | ordinary_bank__impulse_on | recovery | 0 | 0/16 | — | — | — |
| ood | clocked_bank__structured_on | event | 526 | 16/16 | 0.028499 | 0.038327 | 0.009828 |
| ood | clocked_bank__structured_on | recovery | 251 | 16/16 | 0.060448 | 0.038531 | -0.021917 |
| ood | clocked_bank__impulse_on | event | 394 | 16/16 | 0.030047 | 0.033447 | 0.003399 |
| ood | clocked_bank__impulse_on | recovery | 170 | 16/16 | 0.043133 | 0.048010 | 0.004877 |
| ood | first_passage_bank__structured_on | event | 705 | 16/16 | 0.027369 | 0.042379 | 0.015009 |
| ood | first_passage_bank__structured_on | recovery | 354 | 16/16 | 0.053886 | 0.030281 | -0.023605 |
| ood | first_passage_bank__impulse_on | event | 623 | 16/16 | 0.034288 | 0.034997 | 0.000708 |
| ood | first_passage_bank__impulse_on | recovery | 334 | 16/16 | 0.044513 | 0.048933 | 0.004421 |

Ordinary candidates have no recorded event or recovery in any fit; their empty MSE entries are undefined, not successful zero-error observations.

## Per-fit first-passage pair counts and changes

| Fit | Split | Sustained event n / ΔMSE | Sustained recovery n / ΔMSE | Impulse event n / ΔMSE | Impulse recovery n / ΔMSE |
| ---: | --- | ---: | ---: | ---: | ---: |
| 501 | iid | 27 / -0.000669 | 7 / -0.024462 | 35 / 0.001971 | 16 / 0.003247 |
| 501 | ood | 45 / 0.007730 | 22 / -0.009480 | 39 / 0.001203 | 28 / 0.007456 |
| 503 | iid | 31 / 0.006495 | 10 / -0.013204 | 34 / 0.000847 | 16 / 0.004486 |
| 503 | ood | 34 / 0.014486 | 19 / -0.036613 | 39 / -0.000568 | 24 / 0.002393 |
| 509 | iid | 16 / 0.021792 | 6 / -0.000923 | 23 / 0.007356 | 9 / 0.002854 |
| 509 | ood | 24 / 0.012948 | 11 / -0.047651 | 36 / -0.001821 | 16 / -0.009974 |
| 521 | iid | 25 / 0.018105 | 25 / -0.008527 | 38 / 0.000421 | 21 / 0.000874 |
| 521 | ood | 38 / 0.030975 | 21 / -0.077656 | 35 / -0.010322 | 20 / 0.027400 |
| 523 | iid | 36 / 0.004941 | 25 / -0.003467 | 29 / 0.000219 | 21 / 0.006195 |
| 523 | ood | 54 / 0.010567 | 27 / -0.011025 | 45 / -0.006801 | 27 / 0.003910 |
| 541 | iid | 51 / 0.003667 | 25 / -0.004870 | 49 / 0.000721 | 15 / -0.000209 |
| 541 | ood | 60 / 0.011942 | 34 / -0.007694 | 52 / 0.003278 | 26 / 0.000659 |
| 547 | iid | 41 / 0.001745 | 21 / -0.005620 | 43 / -0.001193 | 19 / 0.003228 |
| 547 | ood | 48 / 0.023749 | 25 / -0.036194 | 36 / -0.002132 | 16 / 0.002436 |
| 557 | iid | 34 / 0.016098 | 11 / -0.018570 | 36 / 0.001784 | 17 / -0.005210 |
| 557 | ood | 38 / 0.013800 | 15 / -0.013289 | 39 / 0.008633 | 22 / -0.005660 |
| 563 | iid | 43 / 0.011870 | 22 / -0.013563 | 46 / 0.003747 | 14 / -0.001481 |
| 563 | ood | 41 / 0.016104 | 21 / -0.006158 | 41 / 0.018905 | 17 / 0.003391 |
| 569 | iid | 38 / 0.007484 | 17 / -0.007483 | 33 / 0.004991 | 16 / 0.007196 |
| 569 | ood | 48 / 0.023905 | 24 / -0.028510 | 41 / -0.002384 | 17 / 0.009830 |
| 571 | iid | 41 / 0.004178 | 21 / -0.007083 | 37 / -0.000533 | 16 / 0.001997 |
| 571 | ood | 38 / 0.006929 | 27 / -0.019909 | 41 / 0.000055 | 28 / 0.006603 |
| 577 | iid | 43 / 0.002978 | 19 / -0.007016 | 27 / -0.000170 | 8 / 0.001516 |
| 577 | ood | 40 / 0.025359 | 12 / -0.028886 | 33 / 0.001567 | 13 / 0.002148 |
| 587 | iid | 43 / 0.000931 | 17 / -0.003247 | 35 / 0.000008 | 20 / 0.001295 |
| 587 | ood | 45 / 0.002203 | 9 / -0.012282 | 40 / -0.000061 | 10 / 0.011831 |
| 593 | iid | 38 / 0.003717 | 19 / -0.000553 | 26 / 0.001001 | 12 / 0.018048 |
| 593 | ood | 46 / 0.011479 | 27 / -0.021379 | 32 / 0.004869 | 22 / -0.002777 |
| 599 | iid | 50 / 0.004319 | 31 / -0.006853 | 34 / -0.001179 | 9 / 0.003381 |
| 599 | ood | 48 / 0.013221 | 26 / -0.014128 | 30 / -0.005728 | 17 / 0.009533 |
| 601 | iid | 59 / 0.005245 | 31 / -0.016449 | 48 / 0.001775 | 34 / -0.000498 |
| 601 | ood | 58 / 0.016464 | 34 / -0.025899 | 44 / 0.000141 | 31 / 0.004128 |

## Interpretation limits and reproducibility

Elapsed time, action costs, pending/broken flags, time-indexed bank features and trajectory selection can change across the joined decisions. Different candidates can select different world/state populations. A constant teacher target removes new-observation changes in that target; it does not make event or recovery causal. This is the existing learned readout, not an independently fitted optimal decoder or maximal available information.

The controlled trained-cell retention probe remains separate. In the actual task, impulse changes both drift and bank future-driver features; this audit cannot separate those effects. The actual head retains public last-observation and time inputs, so cell-only information loss cannot be inferred from a readout-error increase.

Selected episodes: **18,432**; streamed raw episodes: **153,600**. The JSON retains every fit × split × candidate × transition row, nonexclusive exclusion counts, raw SHA-256 identities and per-fit audit hashes. Per-fit audit files additionally retain each included pair's world/decision ID, beliefs, latent indices, elapsed change and changed task fields. Main source bytes and the model-seal identity were verified before and after analysis; the successful confirmation receipts link these outcomes to that seal.

Audit script SHA-256: `824049bd452a73454351274c604001f025d63a8b01cca9c6ccf88f949470f601`.

Model seal SHA-256: `379898eaf4b7b73ec35c5fa36d123c1663b1ee48c080151e56b89d0d39977da7`.

Companion JSON SHA-256: `423f82916203900cb6434fdd6e991c893b2f64d088f68f754e13e784c5b54d1f`.

Whole-process costs are recorded by the published external wait4 supervisor in the audit output process_receipts directory; per-fit inner analysis costs are nested, not additive.
