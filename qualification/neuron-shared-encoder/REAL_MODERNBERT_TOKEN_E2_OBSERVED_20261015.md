# First successful pinned ModernBERT full-token paired result (research only)

## Evidence identity
- Exact producer/reviewer PR HEAD: `b68d1c2937510eebb02a436d7c1096c0087b5edb` (#2049).
- Completed GitHub Actions physical experiment: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590216816 (success).
- Original downloaded physical research ZIP: artifact `11923659430`, name `hepta-real-token-research-38590216816`, ZIP SHA-256 **`8c2a5bb4b9d2cbc0b298829d90fe7bee17c6bd9e20eebd68bb5ceb1c875b38f5`**.
- Source historical AG News ZIP SHA-256: `1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2`.
- Model: `answerdotai/ModernBERT-base`, exact revision `fa3113d09d6dacfe5528708803dd92a62240237a`.
- Preflight: **128/128** original joint ordered question/options/state inputs; maximum untruncated tokens **152** (Cell 0) and **150** (Cell 1), at max length **168**, batch **8**. The two ordered token-ID stream digests match the Producer.
- Producer: **two cells × eight** observed physical module-forward batches, 64 original rows per Cell, with 5,324/5,485 active tokens; observed encoder forward walls 13.109 s and 13.270 s respectively. These are self-observed host-local module calls, not independently signed/target-host production metrics.
- Two paired equal-parameter Head kinds: `pooled_cached` and `token_query_prepared`, **16,132** parameters each. Three seeds (11,23,47), 20 optimizer steps per Head and exactly **12** sealed Head safetensors.
- Separate independent Reviewer process: fresh actual pretrained re-encode plus independent NumPy metrics/checkpoint replay, reported `independent_numeric_replay_all_metrics_passed=true` and `real_pretrained_encoder_forward_reobserved=true`. The source report SHA-256 matches `f8e0a95590bf72148ab6845a4ceaf18940a3d332b72077a3066c4c34d5a5f7fc`.

## Paired *retrospective* holdout: Token Query minus Cached Pooled

The resampling unit is **one of 32 original cases** (16 per Cell), retaining all three seed outcomes. The same 32 case labels are not 96 independent examples.

| Metric | Paired point difference | Original-case-stratified bootstrap 95% (descriptive only) | Direction |
|---|---:|---|---|
| Accuracy | -0.0104166667 | [-0.03125, 0.0] | Higher better; no Query accuracy improvement |
| Brier | -0.0045607523 | [-0.0086932524, -0.0006997700] | Lower better; Query modestly better |
| NLL | -0.0081529011 | [-0.0146401028, -0.0020081056] | Lower better; Query modestly better |

The unadjusted descriptive bootstrap used 2,000 replicates with fixed seed 20261014. Original source-family independence is **not** certified. The repeated-seed holdout comparison recorded **0 newly correct** and **1 newly incorrect** for Token Query across 96 correlated case×seed rows.

The experiment's CPU training-wall observations across six individual Cell×seed Head pairs (not a controlled target-host throughput study): mean **8.683 ms** Cached Pooled versus **41.846 ms** Token Query per 20 optimizer steps, an observed ratio **4.82×**. This **does not** estimate the independent incremental Encoder forward, request scheduling, end-to-end p95/p99, inference cost, memory, energy or production sharing.

## Decision and blockers

**No default Token Query promotion or declared winner.** It improves retrospective probability metrics slightly but not accuracy, and has higher observed training cost on this workload. Prefer cached Pooled as the conservative comparator, keep Query as an experimental arm, and preregister new source-separated prospective tasks before any selection.

Exact same-HEAD research workflows `Hepta physical token paired Head research`, Shared Encoder Shadow, Architecture and Canary succeeded. The **global `blocking-ci` failed**: `cargo-deny` raised security advisories including RUSTSEC-2026-0318, 0319, 0346–0349, while Windows Bazel/Clippy produced unrelated Rust test/lint failures including disallowed `sqlx::pool::PoolOptions::connect`. These must be fixed at the affected dependency/code owners; **do not suppress security advisories** to manufacture green status.

Remaining unverified: independent source/license/use attestations; deployed frozen no-change; truly future timestamped windows, negative transfer and independent NDU evaluator; Q24 parity; physical Rust shared-Encoder Worker; signed CAS/final-use and generation fences; WAL/restart; target-host 64/256/1024/4096 CPU/GPU/RSS/p95/p99.

`production_admission=BLOCKED`
`selection_authorized=false`
`signed_future_NDU_verified=false`

This file is a **read-only physical research evidence index**, not a signer receipt, model-selection artifact or authority to deploy. The cited ZIP is the canonical inspectable numerical source.
