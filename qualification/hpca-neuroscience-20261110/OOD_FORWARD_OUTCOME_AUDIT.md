# HPCA V2: replay-independent arithmetic audit of actual operator OOD forward (2026-11-11)

**Status: HOLD_NO_GO / DENY_ALL.** This audit *re-scores* original, already-completed real CPU model forwards; it is not an independently held-out scientific evaluation, is not a new training run, and does not authorize adoption/deployment.

## Original source, freeze, and measured execution

- Precommitted task plan: [PR #5960](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5960), exact HEAD `a54c1d72ee2d82d3bae5c5fdda94d5d3333046b2`, immutable plan SHA-256 `acb16047e5942d317262ddb8273a2d62e9131e758d6627dcf1c2f42081d98043`. All 24 tasks and truths were operator-authored and public to this audit. This is **not independent future B**.
- Original actual 9-condition SmolLM2-135M-Instruct CPU LoRA / base OOD forward took place on HeptaRuntime `ai395` from **2026-11-11 11:10:38.242356 to 11:10:48.161613 UTC**. The unmodified original 98,459-byte JSON report is archived here as `ACTUAL_OOD_FORWARD_RESULT.json`, SHA-256 `3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a`. Model identity/config/script/tokenizer digests remain the original operator **self-reports**, not new independent hardware/owner attestations.
- Original forward reported **9.919518773 seconds wall**, **33.539317821 seconds process CPU**, **1,229,628 KiB process-lifetime peak RSS** and 14,946,304 bytes of block reads (cumulative process counters). These are original process scope costs, **not** a complete training/labeling/owner/verification/full-product cost.
- This second-phase pure-Python re-score ran on `ai395`; the original forward and training were **not repeated**.

## Independent re-scoring results and failure controls

The read-only verifier checks the original plan bytes and SHA, 24 unique registered tasks, all nine model conditions, 216 distinct per-condition task rows, same prompt digests across conditions, truth/family binding, finite probabilities, threshold labels, all per-row Brier/logloss scores, each per-family and overall aggregate, four paired seed comparisons and recorded loading/inference cost structure. It rejects omitted/duplicate rows, changed plan, altered prompt identity, erroneous predictions/scores, altered paired statistics, invalid costs, duplicate JSON keys and NaN. **Passing is internal consistency of a recorded observation, not independent verification that the model was executed.** Prompt hashes do not prove prompt/label origin and the operator's full result is not a signed receipt.

| Condition comparison, on *the same* 24 operator OOD tasks | Recomputed result |
| --- | --- |
| Nine real model conditions, total prediction rows | 9, 216 |
| Frozen base model accuracy | 11/24 = 45.8333% |
| Four bursty minus interleaved paired *binary accuracy* differences | 0, 0, 0, 0 |
| Different binary decisions within four seed-matched pairs | **0 of 96 paired task decisions** |
| Mean bursty minus interleaved binary log-loss | **+0.0000554441** (higher is worse, very small) |
| Scientific, independent future-B or production conclusion | **HOLD_NO_GO / DENY_ALL** |

All four seed matched decision vectors were identical between cadence arms. This is a useful negative behavioral finding **on the particular operator OOD panel only**. The confidence/power is inadequate for a general "no effect" theorem. A small loss variation does not establish actionable task-value improvement; this is not proof of four independent evaluators or causal cadence attribution.

The original report separates `load_wall_seconds`, `inference_wall_seconds` and `load_plus_inference_wall_seconds`. The latter contains about 0.06–0.08 ms overhead per run rather than equaling their exact arithmetic sum; the verifier preserves this recorded overhead with a bounded nonnegative tolerance rather than falsifying the original observations.

## Local tests and reproduction

```sh
cd qualification/hpca-neuroscience-20261110
python3 -m unittest -v test_ood_forward_audit
python3 ood_forward_audit.py --plan HPCA_V2_OOD_PLAN.json \
  --result ACTUAL_OOD_FORWARD_RESULT.json --out /tmp/hpca_ood_audit.json
```

Original local second-phase green log, SHA256 identities and `/usr/bin/time -v` accounting are archived in `OOD_AUDIT_TEST_EXECUTION.log`. All **11/11** deterministic evaluator tests passed. The same path-scoped GitHub workflow runs the tests and verifier on the exact submitted source+original report. No precommit OOD plan, original weight, training script, native Owner or selected generation is modified.

## Remaining required gates

A genuinely independently curated/frozen future B (not this public operator panel); same-source Owner-attested time/feedback/effect receipts, prospective seeded 2×2 Core×NDU matched controls; real sparse/dense ACT/CTRL outcomes and MEM exact-key/typed/recovery comparisons; semantic generalization and old-task retention with costs and multiple-comparison control; A→train→independent B→real **NoUpdate/Adopt**→different C→cold recovery. None of these are conferred by re-scoring existing logits. PR remains Draft; no merge, promotion, deployment or new authority.
