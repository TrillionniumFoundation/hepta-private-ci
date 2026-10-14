# Multimodal shared stem — research V0 (not a production capability)

This isolated addition is a **mechanism contract**, extending the separate
frozen-text-encoder / multi-Head experiment. It cannot establish that an
untrained bridge sees images, understands speech, or improves any real task.
It does not change the selected `codex-hepta-neuron` journal, inference
worker ownership, production NDU, or final-use authorization.

## Current mechanics

1. **Pinned input**: a model owner supplies bounded, finite float32 feature
   bytes and independent nonzero SHA-256 identities for source input,
   tokenizer/preprocessor, stem, modality encoder, and each fitted bridge.
   A digest alone is **not** proof that the original model or consent was
   verified. No model checkpoint is fetched and no weight is generated.
2. **Fusion V0**: a registered frozen linear bridge projects each available
   modality into a common 1..512 feature width; simple mean fusion is an
   intentionally weak, falsifiable baseline. The modality-specific sidecars
   are retained. This is not Q-Former or trained cross-attention.
3. **Fan-out V0**: identical `(scope,generation,fence,stem,preprocessor,
   bridge,input)` keys borrow one immutable `bytes` snapshot. A bounded LRU
   accounts for encoded bytes. Host-supplied final-use checks run for **every**
   access, including a hit and just before returning a newly created value.
   This is not an independent authority verifier or cross-process zero-copy.
4. **Cell head**: a 384-input, 64-state, rank-8, 8-class local-state gate has
   exactly 9,744 trainable parameters. It updates only a post-Encoder residual;
   it does **not** install a layer-internal LoRA or update the shared stem.
5. **Neuron boundary**: a snapshot exports explicit signed Q24 values using
   nearest/ties-to-even rounding. The production runtime must still validate
   its own `[-8,8]` domain, calibration, provenance, fence, and durable owner.

## What the unit tests actually prove

- Image/text projections can be *manually* aligned on deterministic toy
  vectors, and changing the bridge identity changes the resulting snapshot.
- A synthetic 4,096 Cell fan-out reuses the exact same Python bytes object
  after one producer call, with no deep copy of the cached input.
- Scope/generation/fence revisions use distinct keys; an externally revoked
  capability, mutated snapshot, invalid modality, nonfinite input, or changed
  registered projection rejects rather than silently reusing old output.
- Two independently trained heads can solve opposite, held-out, synthetic
  sign-classification tasks without changing the input features or each other.

None of the above is an actual mmBERT, Granite, DINOv2, Whisper, Laya, or
production Worker inference benchmark. Tensor conversion and Python object
costs are not zero; the test counts are not p95/p99, RSS, energy, or GPU data.

## Next acceptance gates (not yet satisfied)

1. Pinned **real** mmBERT-small and Granite 97M experiments with published
   tokenizer/model manifest SHA-256s, calibrated OOD, and independent source
   /train/selection/held-out splits. Repeat on multiple seeds and fixed budgets.
2. Actual DINOv2-small image features and actual ASR/audio features; fit each
   bridge on **train only**, freeze it, compare mean fusion, no-fusion, linear
   projections, gated fusion, and low-rank cross-attention on held-out tasks.
3. Integrate verified immutable shared buffers in Rust inference-control and
   worker with an authenticated, generation-scoped final-use gate; keep V1
   deterministic Q24 journal bytes and rollback semantics unchanged.
4. Native microbatch, LRU invalidation, provenance and revocation races, Cell
   state durability, independent NDU learning ablation, 64/256/1024/4096 Cell
   wall/CPU/RSS/p95/p99/energy and crash-recovery receipts from target hosts.
5. Any production selection/activation requires independent qualification and
   must fail closed if receipts or actual physical execution are missing.

Run local research tests with:

```
python -m unittest discover -s experiments/shared_stem_cell -p 'test_multimodal_*.py' -v
```
