# Frozen fit40 retained-text gap findings — 2026-11-11

**Decision: HOLD / NO GO.** The native result and both baseline artifacts have been recovered and checked. Terminal job status remains unknown; artifact recovery does not establish terminal publication.

Evidence: [native gap result](FIT40_GAP_RESULT_20261111.json), [exact native baseline archive](FIT40_GAP_BASELINES_20261111.zip), [execution and recovery status](FIT40_GAP_EXECUTION_20261111.json), [earlier coverage result](FIT40_COVERAGE_RESULT.json), [earlier execution pins](FIT40_COVERAGE_EXECUTION.json), and [frozen diagnostic status](GAP_NATIVE_STATUS.json).

## Integrity and scope

The recovered result is 7,924 bytes, SHA-256 `b4f7645170cd721b1687b0de869e84cdbf92793a4da46753e092b44a2ed673d1`.
The result JSON is copied from the recovered native output without reserialization. The ZIP preserves the exact native bytes at `BASELINE_BEFORE/RESULT.json` and `BASELINE_AFTER/RESULT.json`, with fixed member order, timestamps, permissions, and compression settings.
Its complete `input_pins` object equals the earlier coverage execution and result: records, request, collection, embedded plan, and original source inventory. The records and request also match the frozen gap status.
The diagnostic, coverage, and legacy implementation hashes and byte counts match that status and the inspected checkout. The normalizer matches the earlier execution pin; the frozen OCR hash matches the inspected source. All five source hashes equal the recovered result.
The rules object matches the inspected implementation, and its canonical digest recomputes to `506edb39b46c20fb285e29962e65adf051f692f5d570f6b7046a791f6ad0b3e7`.
The result records two baseline validation rounds over 60 original source files. Each round checks the complete inventory before and after: four inventory passes, or 240 source-file hash validations, not 240 independent sources. Both separately recovered baseline files match its exact output digests:

| Baseline artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Before | 29,593 | `bfbe3d573f224ee9440b43a85b2420fd043695044737b26036b71290dd7f23e6` |
| After | 29,594 | `983a55e9e74ab899741601e8f6cc16ac1be4349b536ce89a6cb41ad86cb2c2ff` |

Every JSON value except execution CPU and wall time is unchanged between these baselines and the earlier coverage result. Input pins, every per-source record, 160 states, 40 sources, and the 0.5375 source-equal ceiling all agree. These consistency checks do not authenticate the historical producer.

This is the existing training cohort: 200 rows, 160 unique states, and 40 sources with four states each. Forty duplicate state records do not add independent observations. There are zero new independent tasks, new observations, OCR calls, model inference calls, or training steps; future labels remain unopened.

## Category accounting and denominators

Percentages in this table use the observed state count in each column. The date and total columns describe their observed subsets, not a complete 40-source field cohort.

| Quantity | All observed states | Date subset | Total subset |
| --- | ---: | ---: | ---: |
| Observed / registered sources | 40 / 40 | 17 / 40 | 23 / 40 |
| Missing registered sources | 0 | 23 | 17 |
| Unique states | 160 | 68 | 92 |
| Originally covered | 86 (53.75%) | 34 (50%) | 52 (56.5217%) |
| A: frozen lexer proposal match | 0 | 0 | 0 |
| B: numeric-format proposal match | 1 (0.625%) | 0 | 1 (1.0870%) |
| C: match in another recorded state | 73 (45.625%) | 34 (50%) | 39 (42.3913%) |
| D: fixed probes insufficient | 0 | 0 | 0 |
| Unknown reference | 0 | 0 | 0 |
| Out of scope | 0 | 0 | 0 |
| Original uncovered states | 74 | 34 | 40 |
| Covered after retained A/B proposals | 87 (54.375%) | 34 (50%) | 53 (57.6087%) |
| Full-cohort source-equal original coverage | 53.75% | `null` | `null` |
| Full-cohort source-equal probe availability | 54.375% | `null` | `null` |
| Selected accuracy / selection gap | `null` / `null` | `null` / `null` | `null` / `null` |

The exhaustive accounting is `160 = 86 + 0 + 1 + 73 + 0`; the original gap is `74 = A 0 + B 1 + C 73 + D 0`. The overall source-equal rates equal the state fractions because every source contributes four states.
Retained proposals increase candidate availability by **0.625 percentage points**, from 53.75% to 54.375%. They recover 1/74 = 1.3514% of originally uncovered states; 73/74 = 98.6486% fall in C.
For date, C accounts for 34/34 uncovered states. For total, B accounts for 1/40 (2.5%) and C for 39/40 (97.5%). These are gap-conditioned proportions, not success rates of a deployed policy.
The complete-cohort field category rates also remain `null`, as do unavailable-observation counts. Neither field is observed for all 40 registered sources. Company and address are outside this retained-text diagnostic's two-field output.

## Proposal budget accounting

| Quantity | All states | Date subset | Total subset |
| --- | ---: | ---: | ---: |
| Scanned regex matches | 6,801 | 242 | 6,559 |
| Unique proposals encountered | 2,319 | 6 | 2,313 |
| Retained proposals | 1,813 | 6 | 1,807 |
| Dropped under the 64-proposal limit | 356 | 0 | 356 |
| Dropped under the 128-candidate cap | 150 | 0 | 150 |
| States with probe budget censoring | 13 | 0 | 13 |
| D states with probe budget censoring | 0 | 0 | 0 |
| States with both A and B retained matches | 0 | 0 | 0 |

The accounting closes: `2,319 = 1,813 + 356 + 150`; every overall count equals its date-plus-total sum. Proposal identities include text, source box, and origin within a state; these are not 2,319 distinct answers or tasks. Scanned matches include duplicates.
All 13 censored states belong to total: 13/160 = 8.125% overall, or 13/92 = 14.1304% of that field's observed states. The implementation flags any proposal-limit or candidate-cap drop, or a scan-limit hit; no scan-limit hit is reported here.
The artifact does not cross-tabulate these 13 states against covered/B/C. They cannot be described as 13 uncovered failures or 13 demonstrated causes of the gap. The drop counters use an ordered budget attribution and do not measure the benefit of lifting either limit.
Zero D states does not establish complete original observations, absence of historical truncation, or recoverability from the original pixels. Historical pre-cap truncation remains unknown.

## What the result establishes

The one B state shows that the frozen, target-free numeric projection can retain a scorer-matching total candidate in one additional state. It provides no evidence about selecting that candidate, semantic correctness beyond the scorer, serialization, delivery, or terminal utility. Do not broaden numeric rules using this single exposed training-state hit.

C means another recorded state from the same source and field contains a matching **original** candidate. It establishes neither chronological availability nor reachability from the current state. It is not evidence that a READ action caused the match, that another READ would help, or that 73 gaps are repairable by READ. C contributes nothing to the reported current-state proposal availability.

The A category is zero among previously uncovered states. This does not authenticate the historical extraction code or exclude an earlier extraction problem. Categories are ordered diagnostic attributions, with covered before A before B before C; they are not causal effects.

Proposal availability cannot supply a missing historical selected-candidate witness. Selected accuracy and selection gap remain unknown. No actor was updated, policy efficacy was not evaluated, full physical cost was not observed, and production admission remains false.

## Next evidence needed

1. Retain the verified baseline bytes with the gap artifact and recover the original job's terminal receipt without resubmitting the diagnostic. Keep terminal publication unknown until that receipt is observed.
2. Use a versioned native adapter for actual STOP-finalizer versus one continuation-macro-finalizer outcomes from the same initial state and pinned finalizer. Preserve the primitive action contract; an answer-producing READ macro is not a primitive READ-only transition.
3. Record two nonnegative absolute branch costs and compute `net_gain = (quality_continue - cost_continue) - (quality_stop - cost_stop)`. Their cost difference may be negative. Include planning overhead exactly once; keep latency-only evidence distinct from full physical cost.
4. Retain every registered pair in the denominator. Preserve failed branches and known costs; mask an unobserved terminal score instead of inventing zero or reporting only successful pairs as the cohort result.
5. Derive selected-used labels only from validated selection-to-delivery witnesses. Missing witnesses remain unknown. Require an independent, predeclared postcondition for effect labels; neither positive nor zero quality supplies that label.
6. Share the same versioned predecision feature projection offline and online. Keep post-READ features, reference answers, and true evidence-condition labels out of policy inputs; require source-disjoint calibration and complete-cost comparisons with strong light and tuned-fixed baselines before promotion.

This recovered diagnostic supports a narrow candidate-availability finding and a concrete audit of recorded-state differences. It leaves the native control-value, realization-label, and promotion questions open.
