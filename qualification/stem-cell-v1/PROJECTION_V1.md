# Shared Stem low-rank projection — qualification V1

**Status:** SHADOW / algorithm-contract only. No production signature, grant, CAS publication, route cutover, or NDU promotion.

## Purpose

A text Encoder can emit 768- or 1152-wide mean features, or a 6144-wide
eight-landmark representation. The canonical Neuron Q24 worker currently
accepts at most **512** inputs. Truncating the final dimensions destroys
potential decision evidence. This V1 uses one **shared** registered low-rank
projection before many **cell-local** Heads.

```text
locally audited frozen HF snapshot
  -> existing SharedStemEngine.encode_many (one actual Torch forward for misses)
  -> FrozenFeature (canonical IEEE-754 f32 values and source digest)
  -> versioned LowRankProjectionQ24
  -> ProjectedFeatureRef (source+scope+generation+revocation+projector bound)
  -> existing NeuronFeatureRequest / CpuGatedHeadDriver
  -> independent inference-control admission and receipt
```

The final Worker arrow is **not** automatically wired to a live
inference-control owner. A Rust request verifier confirms the projected vector,
projected digest and worker generation, but does not mint a capability.
The numeric Tensor driver computes real Q24 Head outputs; there is **no native
Rust Transformer Encoder** and no qualified 4096-Cell production result.

## Exact numeric algorithm

For approved float32 Encoder values `x`:

1. Validate finite inputs, full declared source width (1..8192), and `[-8,8]`.
2. Convert f32 to signed Q24 with nearest-even tie breaking.
3. `u = round_even_Q24(A x)`, `A` row-major `[rank,input_width]`.
4. `z = round_even_Q24(B u + bias)`, `B` row-major `[output_width,rank]`.
5. Reject out-of-range intermediates/outputs. **Never saturate** or silently
   discard source coordinates.

Registered dimensions: rank 1..64, output 1..512, at most 600,000 stored
coefficients. `A`, `B`, bias each stored as exact little-independent
big-endian signed i64 Q24 in content digests. Projection weights are shared
once per permitted model/organ bundle, **not** counted as per-Cell Head weights.

Golden cross-language fixture: 3→2 rank-2 projection, input
`[0.5,-0.25,0.125]`, output Q24
`[8388608,-2097152]`.

- Frozen f32 feature SHA256:
  `e2738fbff6a632280fd48ed1022a3ea63a924111c75bc65260766e31b4f41327`
- Projection SHA256:
  `451632b3946c1d3dd690eaf2007ad71ba00b50c49c8911854aa02be25a7838c3`
- Scope/generation/revocation/projector-bound input SHA256:
  `a61a79d9d616f28356a12dbcb1eaccbf37c7d51ae3fee807fc6d8d724150a40e`

Python and native Rust each check all three identities and the exact numeric
output, including negative ties-to-even, wrong widths and overflow.

## Cache and provenance restrictions

All cached projected features are keyed by scope, generation, revocation
frontier, Encoder/preprocessor/runtime, input, immutable f32 feature digest,
and exact projection digest. Request IDs are not deduplication keys; a new
Neuron request must still have its own independent authorization.

The cache holds only immutable vectors, stays bounded and supports
scope invalidation. A changed source or projection receives a new key;
revocation-triggered eager invalidation still belongs to the authoritative
runtime lifecycle owner. A SHA digest is **not** an authenticated execution
receipt or data-use permission.

The projection manifest requires a full-file SHA256 pin, exact shape and
tensor fields, reviewed training lineage, `shadow_only=true` and
`production_authorized=false`. The strict loader denies unknown, missing,
duplicate or mutated fields; it does not write Artifact CAS.

## Reproducible qualifications

```sh
python3 -m unittest discover -v -s qualification/stem-cell-v1 -p 'test_*.py'
cd codex-rs
cargo fmt --package codex-hepta-infer-worker-host -- --check
cargo check --locked -p codex-hepta-infer-worker-host --lib
just test --locked -p codex-hepta-infer-worker-host --lib \
  -E 'test(model_worker::)'
```

These checks are **L1**. A synthetic Torch forward is tested to prove that
the projected batch can consume a real tensor operation, not that an audited
mmBERT checkpoint has run. No pretrained weights are included or downloaded.

For **L2**, run approved, pinned model snapshots and grouped future-window
trials: compare joint encoding, mean projection, landmarks and cross-attention,
with no-change and full Laya decisions; measure retained evidence and Head
training data requirements. Train the projection only on approved train folds;
freeze weights before calibration/held-out/future evaluation.

For **L3**, only count actual native Tensor backend executions with genuine
per-process RSS/CPU and same-clock enqueue/start/finish telemetry. Distinguish
`encoder_cold`, `encoder_batch`, `feature_hit + projected_head`,
`projection_miss`, and WAL/recovery. Do not infer shared computation from
a batch request API or from the number of logical Cells.

For **L4/L5**, require independent signed evaluator/selection/execution
receipts, negative-transfer and subgroup floors, revocation reconciliation,
and measured NDU gain. These gates are not implemented by this research module.
