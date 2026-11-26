# E2 V4: matched trainable-parameter nonlinear Head qualification

**Research / shadow only.** This work is stacked on [#1772](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1772), which is stacked on [#1496](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1496). No production authority, CAS signature, independent NDU outcome, precommitted future result, or runtime Q24 activation is granted here.

## What this controls

The existing V3 E2 grid uses identical *parameter ceilings* (2K / 16K / 64K / 262K), but not identical actual trainable counts across all architectures. V4 adds a genuine paired experiment for `dynamic_gate` versus `swiglu`. Both have the same linear drive, linear gate and linear readout shapes, but distinct nonlinearities. At dimension 128 with four choices, their exact counts match: 1,838 / 16,248 / 65,504 / 262,004.

Each pair and seed uses **equal initialization tensor values**, training row IDs, sampled minibatches, AdamW, learning rate, steps, capacity budget, train-only mean/std and held-out splits. Actual counts are checked by assertions. Input matrix size, class width, seeds, steps, minibatches and parameter budget are bounded. The report includes the identical batch-plan SHA-256 and separate optimizer footprints.

The descriptive paired winner is selected on **validation Brier only**. Future labels must not affect training or the winner. A mutated-future-label regression proves this boundary, but offline access to labels means no causal/prequential proof. The selected model is **not** published, never gets Final-use and cannot be treated as NDU.

The dataset checker rejects mixed principal/Organ/Cell scope, duplicate rows, source-group leakage across splits, future-before-validation data, missing timezone offsets, inconsistent option geometry, mismatched labels and missing classes in training.

## Reproducible local smoke (synthetic)

Run inside `qualification/neuron-shared-encoder`, with preinstalled Torch/pytest:

```bash
python -m pytest -q tests/test_strict_e2.py
python -m neuron_shared_encoder.experiment synth-data \
  --allow-synthetic --output /tmp/e2-data.jsonl --data-count 32
SHA_DATA=$(sha256sum /tmp/e2-data.jsonl | cut -d' ' -f1)
python -m neuron_shared_encoder.strict_e2 \
  --dataset /tmp/e2-data.jsonl --dataset-sha256 "$SHA_DATA" \
  --encoder synthetic-hash --allow-synthetic --dimension 128 \
  --budget 16384 --steps 32 --seeds 11 29 47 \
  --output /tmp/e2-equal-params-shadow.json
```

For a **real** Encoder, replace `--encoder synthetic-hash --allow-synthetic` with `--encoder mmbert-joint` (or `granite-joint`, `modernbert-joint`, `laya-joint`) and supply `--checkpoint-dir`, `--weights-sha256` and `--bundle-sha256`. All assets must be locally staged and SHA-256 pinned; the loader has no network fallback. Data approval, complete teacher semantics, model source attestation and snapshot authorization remain independent prerequisites. Untrained random feature projection is reported separately when input and requested output dimensions differ.

## Mandatory independent admission gates

1. Exact-head hosted CI, global blocking CI, security advisories and source-head architecture checks.
2. Genuine approved data with isolated groups, real pinned pretrained Encoder and real original Laya teacher baseline.
3. Independent frozen **no-change** prediction snapshot; future forecasts externally precommitted before ground-truth outcome.
4. Independent Evaluator calculates resource-adjusted NDU, uncertainty, negative transfer, OOD and future-window gains; Selector separate from Executor.
5. Rust Q24 dynamic nonlinear gate parity, signed artifact CAS, final-use admission, generation fence, durable WAL/rollback and target-host 64/256/1024/4096 Cell measurements.

**No step in this module or its JSON produces permission to promote a model.**
