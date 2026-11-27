# V3 source-bound 64/256/1024/4096-Cell physical fleet (shadow only)

**Identity:** additive child of PR #2485 V2 on exact `main@f8c9419df6ddeb36ff8b522a50219981fb8d9345`. Prior V1/V2 source, producer/reviewer, selected Worker, NDU, CNS, signed artifacts, memory, final-use and main unchanged.

**Authorization:** `DRAFT / SHADOW_ONLY / HOLD_NO_GO / DENY_ALL / NO_MAIN_MERGE / NO_MODEL_PROMOTION / NO_CELL_SPLIT`.

## Objective and experiment geometry

Continue the already authored original-source Granite97 V2 producer → distinct independent software reviewer → exact original Q24 feature bridge. The V3 addition consumes precisely this *reviewed physical feature tensor* without another Encoder forward.

- Head geometry: 384D pooled feature, rank-8 `A` (8×384), `B` (384×8), gate 384+bias, output 384+bias = **6,914 independently addressable int16 scalars per Cell**.
- Four physically allocated fleet sizes: 64, 256, 1024, 4096; exact parameter counts **442,496 / 1,769,984 / 7,079,936 / 28,319,744** and backing int16 tensor bytes **884,992 / 3,539,968 / 14,159,872 / 56,639,488**.
- Parameter generation is frozen, deterministic, **untrained**. The final scalar carries a different Cell identity so no Cell is represented by a shared mutable parameter slot. This is **not** evidence of learned specialization.
- Every iteration physically scores all N gate vectors, selects canonical top-32, then executes the 32 full rank-8+gate+output Heads. Each fleet executes actual warmups and timed repeats, not fake forward counters. The report distinguishes parameter setup CPU, current host process RSS, warm-cache head-only wall samples, and observed local head work. No raw model weights, private features or external-task answers are uploaded.
- The producer calculates the pooled original Q24 token vector once. Distinct question/token inputs may **not** reuse this pooled result. A separate scope/epoch/model/source digest is required to re-admit a feature. The four fleets are reruns of the *same* input, not 4096 concurrent user prompts.

## Independent numerical reviewer

`stem_cell_fleet_v3_review.py` runs as a **separate Python process**, reopens original source/export/reviewer, runs V2 bridge again, independently regenerates all int16 parameter banks, hashes every physical weight, recomputes **every gate**, reranks all candidates, and independently calculates all 32 selected rank-8 output scalars per fleet. Wrong source/token/feature, parameter SHA, gate SHA, selected index, rank8 score, cost census, output size, true/false status, or production privilege aborts.

This is independent **software numeric cross-check**, not model issuer, hardware, external human, task-label or performance attestation.

## Actually executed locally (2026-10-16)

In isolated local Python (not the production host) executed **5/5 ordinary** and **5/5 `python -O`** tests with adversarial numeric/source/authority tampering. Additionally ran the complete **64/256/1024/4096** parameter-bank execution with **14 rows of explicitly synthetic Q24 features**, one warmup and three timed repeats per size, followed by all-size independent reviewer validation: **PASS**. Exactly checked the local tested Git blob SHA of the three V3 Python files against each uploaded remote blob.

Observed single-host illustrative outcomes (synthetic source, 3 samples, **NOT** stable SLA p95 or pretrained task quality):

| Logical Cells | Physically allocated int16 bytes | Descriptive max / nearest-rank p95 of 3 head-only repeats |
| ---: | ---: | ---: |
| 64 | 884,992 | 39.35 ms |
| 256 | 3,539,968 | 48.56 ms |
| 1024 | 14,159,872 | 68.46 ms |
| 4096 | 56,639,488 | 209.35 ms |

These values reflect Python scalar reference execution and exact local CPU environment. A Python implementation's timing is *not* a Rust Worker / GPU / optimized inference p99 claim, and no statistical inference is valid with 3 samples.

## Original pretrained physical qualification

The source- and checkpoint-pinned V2 workflow has been augmented to run V3 after the *actual* original Granite97 producer, real second-model replay and successful V2 feature bridge. It independently executes and uploads only sanitized V3 fleet and reviewer receipts; missing or failed model work blocks the fleet stage. This new job must finish at its **exact HEAD** before saying actual pretrained-token → 4096 Head work succeeded.

Pending scientific blockers:

1. Independent issuer signatures, authenticated source owner, hardware attestation and production authority.
2. Equal lifecycle total cost vs independent 421M copies and alternative **shared** 421M deployments, target-host persistent RSS/recovery, real repeated sessions and time/energy.
3. Trained Heads, genuine future source/task families, old-task retention, sufficient-evidence Reader, independent semantic outcome ownership.
4. Real image/audio/video pretrained towers, modality necessity and temporal/spatial lesions; no multimodal generation claim.
5. No NDU utility gain, Cell Split or model promotion from this source-only gate.

## Reproduce source-only numerical experiment

```bash
cd qualification/stem-cell-v1
python -m unittest -v test_stem_cell_fleet_v3
python -O -m unittest -v test_stem_cell_fleet_v3
```

The ordinary V1/V2 suite remains enabled. No real model/network is downloaded by these tests.