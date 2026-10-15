# E2 physical frozen Token Matrix vs native pooled Head

**Draft / SHADOW / DENY_ALL. No Stem or Cell is selected or installed.**

## Physical procedure

The E1 core-triad workflow runs pinned Granite R2 (384D), mmBERT-small (384D), and ModernBERT-base (768D) on a single frozen 224-row public AG News cohort, and then executes E2 against those exact staged model files. E2 reloads the model, verifies the original E1 publisher-file inventory, and performs its own Encoder forwards. It never claims to reuse E1's earlier physical execution.

Within E2, each original row is encoded in one of **28 physical microbatches of eight**. A PyTorch model-forward hook counts actual module calls, and the **same hidden tensor** is used to derive both the native pooled vector and the full contextual Token Matrix. No Head performs a new Encoder forward.

Token Matrix: contextual hidden tokens, per-token unit L2, nearest-even Q24, padding removed; length 1–512 and width 384/768. Native Pooled: CLS for Granite, masked mean for mmBERT/ModernBERT, then unit-L2 and Q24. The Token Matrix normalization is a distinct explicit E2 representation profile; it does not claim to be identical to the E1 pooled profile. Per-case feature bytes/lengths are hashed and the full immutable bank is checked before and after Head training. No raw model weights or hidden token matrices are uploaded in artifacts.

## Registered Head arms

| Head | Private parameters 384D | Private parameters 768D | Purpose |
| --- | ---: | ---: | --- |
| Pooled Linear | 385 | 769 | Lower-capacity binary baseline |
| Pooled Gated | 769 | 1537 | Same-capacity control |
| Token Query | 769 | 1537 | Learned masked attention query and binary readout |

All arms use exactly the same train cohort, seed, 40 full-train SGD steps at learning rate 0.15, calibration-only temperature fit, and maximum **2,048 private trainable parameters**. Actual Query movement and changed Head tensor digests are mandatory, not merely a declared learned architecture. The primary matched-capacity contrast is Token Query against Pooled Gated. Equal parameters are **not** equal FLOPs, CPU time or energy; the reviewer preserves separate observed costs.

## Evidence and limits

The independent reviewer requires complete original E1+E2 report pairs for all three pinned candidate models, all source case/label/input identities, full prediction coverage, original publisher snapshot digests, complete Head parameter and SGD receipts, actual observed batch hook counts and positive lifecycle resource fields. It rescales neither model, nor claims production advantage. Only **64 retrospective English held-out** records are scored for accuracy and Brier.

Missing: the independently authenticated deployed no-change model, blind future chronological windows, Reader sufficiency, E3 D0–D3 specialization and negative transfer, independent NDU, real multimodal improvements and target-host 64/256/1024/4096 Cell p95/p99/CPU/RSS/GPU/energy/WAL/fence/recovery. Neither a physical local forward nor an SHA-shaped string is independent origin authentication.

The E1/E2 workflow is located at .github/workflows/hepta-e1-core-triad-real-cpu.yml. Run the isolated mechanism tests with:

    python -m unittest discover -s experiments/shared_stem_cell -p 'test_e2_token_query_*.py' -v

Every output remains **production_promotion_permitted=false**, **stem_winner_selected=false**, **authority=DENY_ALL**. No main merge, Cell split or production route change is permitted.

## Explicit within-arm frozen comparator

For every E2 arm, the runner now publishes its original untrained Head's complete calibration-only-temperature-selected 96-case predictions, alongside the 96-case learned probabilities. The independent reviewer rejects a single missing/swapped frozen case and reports learned-minus-its-own-frozen accuracy as well as the paired query-minus-equal-capacity pooled result. This **is not** a substitute for the E0 deployed original no-change model or a prospective NDU improvement.
