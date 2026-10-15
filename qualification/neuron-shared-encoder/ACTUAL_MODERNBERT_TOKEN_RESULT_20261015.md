# Exact hosted full-token ModernBERT research result — October 15, 2026

This is a **read-only retrospective observation**, not a deployment, a new held-out future window or a new model winner. Original pre-trained weights and AG News texts are **not** copied into this repository.

## Audited source

- Draft source: [Neuron PR #2049](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2049), exact Git HEAD `b68d1c2937510eebb02a436d7c1096c0087b5edb`.
- Hosted Actions run [`38590216816`](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590216816), completed with `success`. Research ZIP artifact ID `11923659430` (28 entries), exact ZIP SHA-256 `8c2a5bb4b9d2cbc0b298829d90fe7bee17c6bd9e20eebd68bb5ceb1c875b38f5` — the same digest printed by `actions/upload-artifact` in the original job.
- Original public 128-item source ZIP SHA-256 `1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2`.
- ModernBERT-base publisher revision `fa3113d09d6dacfe5528708803dd92a62240237a`; original pinned model.safetensors SHA-256 `340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9`.
- Token capture: 168 padded positions, no truncation (max actual original input: 152 tokens), 8 CPU batches × 64 rows per Cell, one frozen source, two independent Cell scopes.
- **12 genuine trained safetensors Head checkpoints**: two Heads × two Cells × three seeds, equal 16,132 FP32 parameters per Head and 20 optimizer steps. Both Pooled and Token Query consume frozen full-token hidden states from the original pretrained Encoder.
- The second process re-ran the Encoder from pinned pretrained assets and used independent NumPy Head equations to replay the Checkpoints. The PR job claims this completion and passes its guard. The small uploaded research ZIP contains **no raw hidden-state tensors or original texts**, so this **third-party** read-only audit cannot redo the model forward or reconstruct the per-case bootstrap directly.

## Actual 32 original retrospective holdout cases (16 per Cell)

The **same 32 unique cases** were evaluated for each of three seeds. Repeated seeds DO NOT increase independent sample count.

| Metric (lower better for Brier/NLL) | Cached Pooled | Token Query | Token − Pooled |
|:--|--:|--:|--:|
| Accuracy | 61.4583% | 60.4167% | **−1.0417 percentage points** |
| Brier | 0.538158 | 0.533597 | **−0.004561** |
| NLL | 1.018896 | 1.010743 | **−0.008153** |

The independent report includes original-case stratified bootstrap **descriptive** intervals for Token minus Pooled: Accuracy `[-0.03125, 0]`, Brier `[-0.00869325, -0.00069977]` and NLL `[-0.01464010, -0.00200811]`. Bootstrap input per-case prediction vectors are not included in this artifact, so the third-party archive audit **cross-checks the means** against independent metrics but cannot recompute those bootstrap intervals. Source-family independence is not established. The repeated three-seed trajectories include **0 newly correct** versus **1 newly incorrect** Token prediction.

## What the byte audit does and does not attest

`actual_hosted_token_receipt_v1.py` independently checks exact ZIP SHA-256, bounded 28-file membership, path traversal / symlink / duplicate / noncanonical JSON and nonfinite faults, complete Head roster and safetensors tensor boundaries, each Head's weight SHA-256 and manifest lineage, tokenizer/producer input IDs and forward counters, reviewed report SHA-256 and original-case metric means. It never extracts ZIP entries and never deserializes weights with Pickle.

It **does not** independently authenticate Github identity, the publisher's model license, raw hidden states, source-family independence, original-case bootstrap uncertainty, actual deployed no-change, future NDU, negative transfer, production Q24/Worker, signed Final-use, Artifact CAS, WAL/recovery or target-host CPU/GPU/RSS/p95/p99. Every output is forcibly `production_admission=BLOCKED` and `selection_authorized=false`. SHA equality is not an external signature.

## Re-run

Use a trustworthy copy of exact artifact `11923659430` (do not upload the original text or Encoder weights into this repo) and run:

```bash
python -m neuron_shared_encoder.actual_hosted_token_receipt_v1 \
  --archive /private/path/hepta-real-token-research-38590216816.zip \
  --output /private/new/path/independent-actual-byte-audit.json
HEPTA_RESEARCH_ARTIFACT_ZIP=/private/path/hepta-real-token-research-38590216816.zip \
  python -m pytest -q tests/test_actual_hosted_token_receipt_v1.py
```

The recorded machine-readable outcome is `ACTUAL_MODERNBERT_TOKEN_RESULT_20261015.json`. The archive is ephemeral under GitHub's 14-day retention policy; preserve its SHA and the sanitized outcome without overstating the preserved evidence. Actual decision: **do not promote Token Query based on this limited retrospective accuracy signal**; it remains a candidate needing independently adjudicated prospective outcomes, negative transfer and total compute budget.
