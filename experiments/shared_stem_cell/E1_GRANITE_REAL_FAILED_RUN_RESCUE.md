# E1/E2 actual failed-run Granite receipt rescue — no model or production authority

**Status:** New independent read-only CI requested, **not yet a completed numeric result**. This work salvages a *partially successful real-model job*, not an E1 three-model victory.

## Source: original completed GitHub Action, no replay or forged model

- Original research job: [38594668819](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38594668819); exact source HEAD `1a22e114c1c8ea081da51d4e94ccb9ff9ce9aeff`. Its **overall conclusion was failure**.
- Archived artifact: `11926728554`, original Actions-uploaded ZIP SHA-256 `c90c5174eb8c2949dc64637ab2676ea756464723c3474cb56a8eb4a092434955`, size 165,519 bytes according to the GitHub artifact API.
- Job logs say `granite_97m_r2 real model and Head run completed`, and `mmbert_small real model and Head run completed`, but the latter's pretrained checkpoint load reported `embeddings.tok_embeddings.weight` **MISSING** and newly initialized. Neither existing Head performance nor a missing table may be called validated pretrained mmBERT performance.
- `embeddinggemma_2_text` **failed** because the pinned Python environment lacked `torchvision` required by `EmbeddingGemma2Processor`. There is no three-model paired result in this archive.
- Only **Granite 97M** is eligible for a historical *numeric readout* from this archived job; even it has **no independently signed physical model origin**, semantic Reader sufficiency or longitudinal future NDU.

## Independent numerical study

`e1_failed_run_rescue.py` accepts **only that exact original ZIP SHA**. It rejects unsafe/duplicate archive paths or basenames, changed or incomplete panel and source digest, missing original predictions and frozen/learned pairs, nonfinite/out-of-range probabilities, mismatched case IDs, wrong splits, changed Head optimizer budgets, missing token/feature/readout inventory and any changed nonproduction authority flag.

It re-derives Granite frozen vs learned Head Accuracy and Brier for original calibration (32 cases) and original test (64 cases), plus the descriptive, **unadjusted** exact paired McNemar p-value. It then invokes the independent existing `e2_residual_review.review` against the *original file SHA* of Granite E1 and the original E2 feature-gated 2K/8K/16K residual outputs. If E2's original E1/E2 frozen feature bank identities, Head baselines, optimizer digests or numeric controls disagree, the entire archive audit fails. This work does not make an E2 source-signed claim.

The original 128 train / 32 calibration / 64 test AG News cohort is public, English-only and **retrospective**. The script quarantines all original mmBERT result numbers, records Gemma as failed, and unconditional report flags prohibit a candidate winner, production promotion or any cross-model superiority conclusion.

## Actual reproducibility

Local **14/14 synthetic adversarial tests passed** for the exact source Git blobs; this tests the archival method, **not** real Granite quality. The dedicated read-only CI [`hepta-e1-archive-granite-review.yml`](../../.github/workflows/hepta-e1-archive-granite-review.yml) checks out the precise PR SHA, runs the tests, downloads artifact `11926728554` with `actions:read`, verifies ZIP SHA, runs the independent numerical calculation, and uploads only a sanitized JSON report. Any expired archive, changed ZIP byte, incomplete experiment or unsuitable control **fails closed**, without substituting simulated predictions.

The output is available only when that exact-HEAD hosted workflow **finishes successfully**. At that point its results remain unadjusted single-family observations; full E1 acceptance requires new source families, Reader-four-condition controls, all 3 fully verified pretrained candidates, temporal future windows, true source signatures, OOD/forgetting and comparable physical host costs.

**ALL authority remains `DENY_ALL`; `production_promotion_permitted=false`, no production Stem/Cell change, no waiver of `blocking-ci`.**
