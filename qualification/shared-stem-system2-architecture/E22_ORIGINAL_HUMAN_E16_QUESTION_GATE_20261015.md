# E22 — Eight-arm original-human MultiRC whole-question learning gate

2026-10-15 · **DRAFT / RESEARCH / DENY_ALL** · stacked on E21 #2252 exact head `78aa6df0d5fe8ab2f3240748dbee02b10dc4937f`.

## Why E22, rather than another FBSDE iteration

The original human-annotated E16 #2205 source-HEAD and synthetic-merge independent
GitHub Actions score archives have **actually completed successfully** (workflow
`38682359793`; scorer ZIPs `11953241456` and `11952742279`). The original
E15 #2195 source-HEAD and synthetic-merge run `38681145276` also succeeded.

Original four heldout passages, eight genuine questions, 33 *dependent*
candidate-answer rows and one source family:

| Original research arm | Trained scalar parameters | Correct/33 | Mean 2-class Brier |
|---|---:|---:|---:|
| Frozen conditioned | 0 new | 16 | 0.6198974379 |
| Frozen mean-pool/query | 0 new | 17 | 0.4968649272 |
| E15 linear readout | 5 | 17 | 0.4957882902 |
| E15 gating | 3 | 16 | 0.5202617476 |
| **E16 centered, train-only scaled** | **5** | **20** | **0.4679101348** |
| E16 centered, unscaled | 5 | 13 | 0.5158668081 |

**Important negative qualification:** all three additional E16 scaled correct
candidates relative to the frozen mean-pool Reader occur in **one** original
passage: paired source-level deltas `[0, +3, 0, 0]`. The previous same-size
unscaled centered Head becomes worse. No positive result across multiple
independent passages, new source families, chronological generations or
matched service cost is established. Multiple learned variants have been
inspected retrospectively; their unadjusted favorable contrast is exploratory.

## Executable new audit

1. `e22_e16_question_gate.py` pins the exact original real pretrained
   ModernBERT+four-Reader ZIP `11946621518` and ALL four original E15 and
   four original E16 source-HEAD heldout ZIP SHA-256 digests. The blind job
   opens only original model logits, heldout probabilities and immutable
   source receipts. It does not open scored ZIP members, original human
   parquet, or any owner-held labels; no model forward is fabricated.
2. `e22_artifact_fetch.py` creates a SHA-locked 8-original-fold inventory,
   optionally adds four original *scored* human aggregate ZIPs after the
   blind seal, and exports original archive paths for inherited tests.
   Strict create-only SHA validation; no missing original file triggers a
   synthetic fallback. Optional original E9 physical+truth files are enabled
   **only in the inherited broad research CI** after its earlier model-only
   work, keeping the genuine E7 separate scorer job unchanged.
3. `e22_independent_human_score.py` reopens original pinned
   `aps/super_glue` MultiRC validation parquet SHA
   `5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada`
   **only after sealed blind predictions are uploaded**. It reconstructs the
   33 original human labels, independently replays the E15 whole-question
   scorer and **all four E16 training folds with the independent 48-step SGD
   implementation**. Every result must agree with both historical E15 and
   both E16 source-HEAD/merge independently hosted human score receipts.
   Then it computes all-eight-question *complete correctness*, all-four
   passage *complete correctness*, candidate Brier, paired recovered/lost
   questions, full source-level deltas and descriptive exact 16-sign
   enumeration. None of the 33 candidates are treated as independent
   original passages.
4. Dedicated E22 Actions source-HEAD and synthetic-merge profiles use distinct
   label-blind and post-seal human scorer **jobs**, create-only outputs,
   normal and `python -O` adversarial tests, true source SHA checks and raw
   failure preservation. E22 cannot publish human results from synthetic
   contract labels.

## Repair of a verified inherited CI failure

E21 #2252 original hosted inherited E6-E8 Actions run
[`38690999858`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38690999858),
job `116276640286`, failed its **unchanged complete** `test_*.py` suite:
E20's original-ZIP env name was missing; E21 demanded four original E15
source heldout ZIPs and two original E15 score ZIPs. Its raw log reports
`Ran 278 tests; FAILED(errors=3, skipped=9)`; neither passing local
mechanics nor historic E6 green can waive this source-HEAD failure.

The E22 stacked branch supplies the exact missing immutable sources **before**
inherited broad unittest discovery, including all new E22 source ZIPs, with
strict per-archive byte hashes. It does **not** change any existing test,
the broad `-p 'test_*.py'` selector, the E7 label-blind policy, production
owners, `blocking-ci`, source review or prior source commits. The original E9
physical/human historical originals may additionally eliminate the older
conditional skips; do not claim hosted zero-skips until actually observed.

## Checks completed locally vs unobserved hosted qualification

At first publication, E22 original prelabel ZIP-backed tests passed **27/27
normal** and **27/27 `python -O`**, no skips; includes 17 no-label checks,
10 human-score-contract tests using **explicit SYNTHETIC labels where
necessary**. Python compilation and strict YAML/shell lint performed on
final source. The only actual-human score claims above come from E15/E16's
**already completed original CI**, not E22 synthetic test labels.

Hosted E22 original-human complete-question count, current-source inherited
E6-E8 job, and `blocking-ci`/Architecture must all finish on this new exact
HEAD before claiming those specific gates passed. No new actual pretrained
forward, live conditional Encoder invocation, target-host RSS, power, p99,
future-time/signed independent original human labels, full-service cost win,
System 2/FBSDE reasoning improvement, selected model or production approval.

**Required decision:** Continue E16 scaled five-scalar Head as an exploratory
research control only, with a new original source-disjoint/time-forward
human-labeled panel and source-level complete-question gains **before**
resource investment. Retain frozen Reader, equal-budget no-change/cheap
Critic/Bellman, and E12–E14 FBSDE `NO_GO` as binding negative controls.

`production_accepted=false` · `model_selected=false` ·
`system2_fbsde_reactivation_permitted=false` · **DENY_ALL**.
