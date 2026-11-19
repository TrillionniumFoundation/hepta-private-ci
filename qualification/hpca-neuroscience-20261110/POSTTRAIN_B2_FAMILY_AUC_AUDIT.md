# HPCA B2 retained rank: within-family versus cross-family pairs

**HOLD_NO_GO / DENY_ALL.** This is a new descriptive decomposition of the
**existing** 540 operator-generated, real CPU SmolLM2-135M-Instruct forward
scores on the same 60 arithmetic prompts. No new model inference, training,
independent B evaluator, model-selection threshold, Owner action, or task
effect was executed. The nine runs reuse the same 60 operator-built tasks:
they are **not nine independent evaluation cohorts**.

## Exact input custody and method

Stacked non-force on [#6022](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6022),
at exact parent `00654bf5d01e143c491249fd4c9019a45087908e`.
The original B2 result SHA-256 is
`937a87f1da2e502f954be0870cd3a64ce06df0245938fc984b8b2a5ed0d95731`;
the original frozen operator task manifest SHA-256 is
`0f12ac4aa7fd32989ba62983ed82367b83fe6a3f51868e4c1b8f567a9decf12a`.
The parent rank report Git blob is
`05c830c88b4d6cd7a3fa0edc48ae6de631c4da62`.
The command `posttrain_b2_family_decomposition.py` first executes the
original source/score/roster audit through `posttrain_b2_rank.calculate`.
Then it partitions the 900 YES/NO score pairs per run into
**180 same-family** and **720 different-family** pairs. Ties earn half
credit, as in the upstream integer twice-win Mann-Whitney calculation.
The within-family score weights each of the five balanced families
equally (36 pairs each); it is not a new trained, held-out or
prospective classifier.

## New result: the pooled adverse ranking is not explained away by family mixing

| Retained CPU run | Same-family AUC | Cross-family AUC | Pooled AUC |
| --- | ---: | ---: | ---: |
| Frozen base | 0.377778 | 0.450000 | 0.435556 |
| Interleaved / Bursty, seed 11 | 0.377778 / 0.377778 | 0.454167 / 0.454167 | 0.438889 / 0.438889 |
| Interleaved / Bursty, seed 17 | 0.377778 / 0.377778 | 0.451389 / 0.451389 | 0.436667 / 0.436667 |
| Interleaved / Bursty, seed 23 | 0.372222 / 0.377778 | 0.461111 / 0.461111 | 0.443333 / 0.444444 |
| Interleaved / Bursty, seed 29 | 0.383333 / 0.383333 | 0.447222 / 0.447222 | 0.434444 / 0.434444 |

For the frozen base, **136/360 twice-win units** come from the same
family and **648/1440** from different families, totaling the
upstream **784/1800** pooled AUC numerator/denominator. All nine
within-family values are below 0.5, and below their respective
cross-family values. Thus the already adverse pooled B2 rank is
*not solely a cross-family mixing artifact* in these frozen rows.
However, 60 tasks and four reused seeds do **not** justify
significance, independent generalization, or statements about other
task distributions. Do not invert labels or fit any threshold here.

`POSTTRAIN_B2_FAMILY_DECOMPOSITION.json` preserves exact integers and
per-run AUCs; new tests guard original SHA-pinned upstream input,
candidate roster, authority/evaluator claim drift, pair-count drift,
and the negative conditional finding. The path-scoped CI must
regenerate this report and compare bytes, in addition to upstream
original-score and rank tests. Test passes are **arithmetic and
custody checks**, never independent effect verification.

Previous B2 model scoring cost remains **not rerun** here:
92.954481356 total process-CPU seconds summed across nine forwards,
24.313295296 seconds summed *per-process* wall duration (not an
end-to-end elapsed time), maximum per-process RSS 1,242,076 KiB.
This decomposition introduces CPU-only report/test cost to be measured
from the corresponding GitHub job, not model training cost.
Full training, inference, external evaluator, retry, networking,
owner/readback and future task costs remain unmeasured.

## Unclosed gates

Native Owner-attested A/feedback timestamps; independent future B and
properly held-out C; real Agentd Adopt/NoUpdate and cold Root recovery;
PERC/ACT regression correction; seven-lineage cost-matched net
benefit; MEM retention/deletion with actual tasks; and Core x NDU
2x2 causal attribution are still **HOLD_NO_GO**. No promotion, weight
adoption, permission expansion, automatic merge or deployment is allowed.
