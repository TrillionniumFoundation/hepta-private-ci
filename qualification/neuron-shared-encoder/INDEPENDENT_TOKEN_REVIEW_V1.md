# Real Token E2 independent numerical review — shadow only

This review is stacked on Draft PR #1964 (which depends on #1963). It does
not change the native Rust Worker, Q24 model, NDU Evaluator, Cell selection,
Artifact CAS, CNS, Supervisor fence, or production final-use.

## Evidence and method

The original public AG News source is the completed GitHub Actions artifact
11881847060 from run 38534349397, immutable ZIP SHA-256
`1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2`.

The publisher checkpoint is ModernBERT-base revision
`fa3113d09d6dacfe5528708803dd92a62240237a`. All six publisher
files must match the source manifest, and the bundle SHA-256 is
revalidated. **No automatic model download takes place in the reviewer.**

After the producer has completed training, closed all Head files and written
`report.json`, this module opens them from a separate Python process. It
physically runs the **same actual pretrained model again** on the same
canonical full question/ordered options/state inputs. It rechecks the two
64-row token matrices and their masks, the complete train-only normalization
inputs, each immutable Head manifest, weight SHA-256, source and generation
pins, optimizer sample lineage, and all 12 safetensors.

The Head readout is calculated by independently written **NumPy equations**,
not by the producer's Torch CellHead, PackedCellHeadBank, optimizer or saved
logits. It recomputes per-Cell calibration/holdout accuracy, Brier, NLL,
and gains/losses relative to the cached pooled arm. Any mismatch or
missing/corrupt file raises an error. The producer's PASS fields cannot
override a failed numerical review.

## Commands

Use a fresh process with the same exact pinned local model and original ZIP:

```bash
python -m neuron_shared_encoder.physical_token_reviewer_v1 \
  --source-zip /private/hepta-public-pretrained-38534349397.zip \
  --source-sha256 1f1a463eebd130288445f5b7bf39377c0775c7cfc00a9cca4da87637a19eeff2 \
  --checkpoint-dir /private/immutable-modernbert \
  --bundle-sha256 EXACT_SOURCE_PINNED_BUNDLE_SHA256 \
  --producer /private/real-token-head-results \
  --output /private/new-independent-review.json \
  --max-length 128 --batch 8
```

The research workflow `.github/workflows/hepta-neuron-physical-token-pair-shadow.yml`
requires **both** physical producer execution and this separate reviewer
before its run can be green; it retains only small Head tensors and
numeric/provenance results, never the source corpus, raw token matrices or
large pretrained weights.

## Limits and mandatory blockers

These independent equations verify numerical *self-consistency* under one
declared model/data/source tuple. The GitHub runner and local file hashes
are not an independently licensed source-use grant or external signer.

The historical 32 unique holdout cases are retrospective and repeated
across three training seeds, **not** prospective independent evidence.
No real deployed no-change baseline, NDU net utility, negative transfer,
OOD/future-time outcomes, source entitlement, 64–4096 target-host
CPU/GPU/RSS/p95/p99, or Rust Q24/CAS/WAL/final-use evidence is provided.

A successful review still emits exactly:
`production_admission=BLOCKED`, `selection_authorized=false`,
`verified_prospective_future_NDU=false`. Never select a model or release
a Cell from this research PR.
