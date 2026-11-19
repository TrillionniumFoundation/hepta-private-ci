# E23: two original source-owner receipts expose the true whole-question result

**2026-10-15 · DRAFT / SHADOW / DENY_ALL · no model selection or production use.**
Child of E22 #2309, without mutating E22 original source-HEAD evidence or the
independent E16 and E15 training branches. No change to NDU, Worker, Q24/Q32,
CAS, WAL, FinalUse, main or blocking-ci.

## Distinguishing source and new physical result

Original successful ModernBERT+four-frozen-Reader candidate archive `11946621518`,
SHA256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
This sample has **4 distinct original passage groups, 8 mixed-true/false
human-labeled questions and 33 dependent candidate answers**, NOT 33 independent
tasks. Original E15/ E16 fitted Head owner Actions runs `38681145276` and
`38682359793` both completed on source HEAD and synthetic merge and retained
four train-only human label artifacts for each parent. Every held answer label
appears in the *other three* owner training fold artifacts. E23 downloads the
**eight original SHA-locked owner ZIPs only after a fresh blind prediction is
sealed** and requires three identical values for every case independently
within E15 and E16; both runs must also agree on all 33 human original labels.

This is not a new independently annotated dataset! Each past owner job was
constructed using the *same* original pinned `aps/super_glue` MultiRC validation
Parquet at SHA256
`5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`.
The new E23 post-score auditor does **not** download that Parquet again, so the
original E22 source-Parquet recheck, currently queued, remains separately binding.
The train-only artifacts' union also demonstrates that process-level label
separation is NOT cryptographic confidentiality for a party that can download
all four original owner files. No fold's actual learner is shown to have used
that union; never claim that it did.

The auditor independently re-fits **four** E16 models on the reconstructed
original 3-passage human labels using the separate E16 mathematics, recomputes
the 48-step parameters, all train-only scales and every held probability, and
requires exact SHA and metric parity with BOTH previously hosted original
E15 and BOTH E16 source/merge score receipts. Tampering with even newly
re-signed blind predictions, owner archives, folds, head weights, classifier
outcome receipts, source identity or permissions fails closed.

| Actual original-human arm | Correct candidates | Complete questions | Complete passages |
| --- | ---: | ---: | ---: |
| Frozen Conditioned | 16/33 | 0/8 | 0/4 |
| Frozen Mean-pool+query | 17/33 | 0/8 | 0/4 |
| Frozen No-evidence | 16/33 | 0/8 | 0/4 |
| Frozen No-query | 19/33 | 0/8 | 0/4 |
| E15 linear-5 | 17/33 | 0/8 | 0/4 |
| E15 gated-3 | 16/33 | 0/8 | 0/4 |
| E16 unscaled question-centered-5 | 13/33 | 0/8 | 0/4 |
| **E16 train-only-scaled question-centered-5** | **20/33** | **0/8** | **0/4** |

E16 scaled-vs-frozen-mean-pool: **+3/33** candidate correct and Brier
**-0.028954792378**, **0/8** net complete-question improvement. The gains
are concentrated in one of four source passages, so observed per-passage
correct deltas `[0, 3, 0, 0]`; a descriptive sign flip over four independent
passage units yields p=1.0. This is NOT a confirmatory test: this family and
Head policy were already explored; multiple comparisons and held-source
coverage are inadequate. Existing human labels do not certify future gains.

## Original owner semantics, fail closed

1. In a **blind** job only the original frozen logits and all E15/E16
   label-free held predictions are read; sealed result is create-only and
   uploaded before any label-bearing archive is downloaded.
2. In a distinct **review** job only, download the E15 and E16 original four
   train-label owner ZIPs; each SHA is pinned and every task appears exactly
   3x with the same bit. Reverify exactly 33 source identities and all
   four held group exclusions. These are original training labels, not newly
   collected independent human annotations.
3. Independently rerun E16 true-label 48-step Head SGD and predict all held
   candidates. Require all original E15/E16 source/merge human score receipts,
   including their outer bytes, source commit, inner content SHA, original
   actual candidate correct count/Brier and source-group success counts.
4. Count whole question success only when **all authentic human candidate
   answers** for the same original question are correct; preserve ties,
   negative results, four passage clusters and full-source label census.
5. Preserve complete failures and never convert research data into FinalUse.

### Reproduce local contract

Use the original external source ZIP and eight original E15/E16 heldout model
fold ZIPs (already covered in parent E22) with `HEPTA_E23_ORIGINAL`,
`HEPTA_E23_E15_FOLD_0..3`, `HEPTA_E23_E16_FOLD_0..3` set. Run the E23 **blind**
program first and write a frozen `HEPTA_E23_BLIND` file. **Only after the blind
file is sealed**, set `HEPTA_E23_E15_OWNER_0..3`, `HEPTA_E23_E16_OWNER_0..3`,
and both `HEPTA_E23_E15_SCORE_SOURCE/MERGE` and
`HEPTA_E23_E16_SCORE_SOURCE/MERGE`, all original SHA-bound CI artifacts.

    ROOT=qualification/shared-stem-system2-architecture
    PYTHONPATH=$ROOT python -m unittest discover -s "$ROOT" -p 'test_e23_*.py' -v
    PYTHONPATH=$ROOT python -O -m unittest discover -s "$ROOT" -p 'test_e23_*.py' -v

Dedicated PR source-HEAD/synthetic-merge workflow checks both paths separately;
**the hosted exact-HEAD CI outcome must be observed** before claiming green.

## Hard limits and next evidence

Zero pretrained model forwards, one retrospective original source family,
four independent passages, eight questions, **0 complete task successes** in
all eight arms. Current E16 +3 accuracy is NOT source-general task success,
a new reader, causal learning gain, a full service cost/watt qualification,
independent original human signer, future-time three-generation evidence,
new FBSDE/NDU reasoning, BF16 physical model run, or production permission.
Reader attention/answer representations must improve on new source families
before investing additional FBSDE, graph search, automatic Cell splitting or
large-scale promotion. **DRAFT / DENY_ALL; no `blocking-ci` waiver.**
