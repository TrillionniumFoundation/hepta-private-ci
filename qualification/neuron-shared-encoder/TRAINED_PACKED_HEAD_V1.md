# Trained Head artifact → exact safetensors readback → packed multi-Cell replay

**Status: shadow-only research, no production authority.** This work is stacked on
[#1928](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1928).
It does not alter the Rust inference worker, NDU selection, generation fences,
CNS routes, artifact registry, Q24 semantics, or a Cell's selected model.

## What is physically exercised

The new `trained_head_artifacts_v1` module accepts **already-present** token
features of a single Cell, a `train/validation/future/ood` manifest, scoped
identities and complete input/encoder/normalizer pins. It uses PyTorch CPU to:

1. Revalidate source identity and source-group/time split boundaries with the
   existing `_audit`. Only **training** rows enter optimizer updates; validation,
   future and OOD labels do not train the Head.
2. Instantiate one `CellHead` and execute real AdamW optimizer updates (explicit
   `lr`, betas `0.9/0.999`, eps `1e-8`, weight decay `0.01`), recording seed,
   minibatch sample digest, steps, batch size and PyTorch version. This is
   **physical training**, not a randomly initialized weight test.
3. Create one private (mode `0700`) directory; write a unique **create-only**
   safetensors file (mode `0600`) and canonical manifest (`0600`) with file
   flush/fsync and SHA-256. No pickle or `torch.load` execution.
4. Independently re-read exact *caller pinned* manifest SHA and safetensors bytes
   from disk; reject any altered digest, symlink, malformed schema, wrong
   principal/purpose/Organ, epoch/generation or incompatible geometry. A
   SHA-256 alone is **not an independent signature or authorized use**.
5. Convert reloaded, numerically checked per-Cell Head tensors into the existing
   `PackedCellHeadBankV1`. Compare **every loaded Cell's scalar prediction** with
   the packed CPU execution for the same already encoded observation; report
   numeric tolerance and total packed weight bytes. No future-label-based
   promotion is performed.

One packing call requires matching `principal`, `purpose`, `organ_id`, Encoder,
tokenizer, preprocessor, normalizer, dataset, generation and authority epoch,
with a unique Cell ID per Head. Each Cell can have a different training
snapshot but cannot silently cross the declared scope. The loader remains
limited to 4,096 Cells and 128 MiB of expected total FP32 Head weights.
The readback is self-contained in a reference module; **it is not an
independently controlled NDU evaluator**.

### Test procedure

From `qualification/neuron-shared-encoder`, in an environment with PyTorch,
pytest, `safetensors==0.7.0` and `numpy==2.2.6`:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m pytest -q tests/test_trained_head_artifacts_v1.py
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -m pytest -q tests/
python -m compileall -q neuron_shared_encoder tests
```

The Torch safetensors writer internally imports NumPy; the Python-only
shadow CI pins both packages explicitly. Without NumPy, checkpoint writes
fail even though the surrounding Head/hash code does not import it.

New adversarial tests include create-once recovery semantics, safetensors
corruption with both unchanged and recalculated self-reported hashes, wrong
external manifest SHA, cross-principal scope, duplicate Cell, wrong output
kind, incompatible generation, invalid training controls, disallowed symlink,
future-label exclusion, and private file/directory permissions on POSIX.
Both pooled and Token Query Head architectures must pass the complete
safetensors reloaded scalar/packed parity test. A learned Head is **not**
assumed to perform better than no-change merely because training ran.

### Observed reference result, not product evidence

On 2026-10-14, CPython CPU/PyTorch 2.10.0, an isolated local smoke executed
**64 distinct Cell optimizers**, each with two AdamW steps on synthetic
frozen token features, wrote **64 separate safetensors artifacts**, and
reloaded all 64 into a packed Head bank. The full-bank scalar/packed maximum
absolute difference was `1.1920928955078125e-07`; bank FP32 weights were
`34,304` bytes. These values are software/numerical observations on synthetic
data, **not authentic pretrained Encoder learning, causal utility, production
latency or a qualified NDU gain**.

### Still blocked

- No independently approved source-entitlement or signed artifact CAS witness;
  self-reported training receipts never authorize use. `independent_training_verified`
  and `selection_authorized` remain `false`, `production_admission=BLOCKED`.
- No genuine shared Q24 model or native Rust Worker dispatch. Floating-point
  PyTorch parity is numerical-tolerance parity, not Q24 bit-exact replay.
- No independently sealed future-time no-change baseline, negative-transfer
  measurement, NDU Evaluator/Selector/Executor, or release authority.
- No authenticated / physically shared Transformer token snapshot in this
  particular train-and-reload test. No GPU, p95/p99, power, WAL, crash/restore
  or 64/256/1024/4096 **target-host service** qualification.
- The local file backend does not attempt to secure against an adversarial
  actor with write access to the checkpoint parent directory. Product-grade
  file path hardening and tamper-resistant owner storage belong to Artifact
  CAS, not this offline study.
