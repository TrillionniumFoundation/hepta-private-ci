# Packed Cell Heads — independent parameters, batched feature readout

**Research-only CPU Tensor reference.** No production Worker, Q24, Artifact CAS, Final-use, NDU, CNS cutover, current-run mutation or release authority.

## Physical execution

An already-frozen [tokens, mask] is passed to a prepacked bank of per-Cell query, low-rank gate, classifier and bias tensors. Each Cell keeps independent parameters; inputs are not rematerialized for every Cell. The packed CPU implementation uses batched Tensor matrix multiplications rather than one Python model invocation per Cell. Two readouts are supported:

- `pooled_cached`: masked pooling once, each Cell's feature gate, then low-rank gated classifier.
- `token_query_prepared`: independent per-Cell token attention on one shared token matrix, followed by the same classifier.

The packer copies parameters into a detached snapshot and rejects duplicate Cell IDs, mutable weight aliasing, nonfinite weights, incompatible dimensions and packed-bank weight memory exceeding 128 MiB. It has no source or authorization authority: the enclosing shadow experiment validates synthetic input hash, scope and generation, not independent Final-use.

All Cells are compared with the independent serial reference *before* timing, with float32 tolerance 1e-5. This is not Q24 bitwise equivalence.

## Reproduce locally

From qualification/neuron-shared-encoder with CPU PyTorch and pytest:

```shell
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m pytest -q \
  tests/test_token_reader_v1.py \
  tests/test_token_reader_offline.py \
  tests/test_token_reader_cost_v1.py \
  tests/test_packed_cell_head_v1.py
python -m compileall -q neuron_shared_encoder tests
```

Use `measure_packed_readout(tokens, mask, labels, rows, pins, expected_sha256, cells=256, rank=8, rounds=3, warmups=2)` for four bounded readout arms; it returns `production_admission=BLOCKED` and `native_rust_worker_batch_verified=false`.

## Observed local CPU reference, 2026-10-14

One process, PyTorch CPU with a single compute thread, 384-dimensional synthetic features, 12 tokens, Rank-8, 2 classes, 2 warmups and **3 measured rounds**. Each number is the median wall time in milliseconds for **all active Cell Heads**:

| Active Cells | Serial pooled | Packed pooled | Serial token query | Packed token query | Independent FP32 packed weights |
|---:|---:|---:|---:|---:|---:|
| 64 | 1.852 | 0.746 | 3.617 | 0.772 | 1.78 MiB |
| 256 | 8.621 | 2.450 | 15.565 | 2.610 | 7.13 MiB |
| 1024 | 38.963 | 9.256 | 74.992 | 10.785 | 28.51 MiB |
| 4096 | 134.786 | 33.875 | 234.873 | 36.214 | 114.03 MiB |

Every Cell passed full scalar-versus-packed numerical checks at every scale. This is not target-host p95/p99, not fused Rust Worker dispatch, and not end-to-end request latency. The serial baseline is an unoptimized Python per-Cell reference. Encoder loading/forward, training, source entitlements, CAS, WAL, process RSS, GPU power and startup/pack cost are excluded from these timing numbers. The original scalar Head bank and newly packed snapshot coexist in memory during testing; the 128 MiB packed weight ceiling is not a process RSS ceiling.

## Performance integrity repair

The earlier NumPy-free snapshot hasher used `bytes(UntypedStorage)`, which iterates one storage byte at a time through Python. Packing 128 small Head tensors incurred millions of Python calls and masked inference performance. The replacement reads the exact *logical tensor bytes* as bounded 64 KiB chunks via a CPU uint8 view, preserving the existing digest meaning. It handles contiguous Tensor views whose storage starts at nonzero offsets, and does not require NumPy.

## Production blockers

Actual approved pretrained token features; matching pretrained model and complete question/options format; calibrated no-change and future-time outcomes; negative transfer and independent NDU review; Q24 parity; signed Artifact CAS and Final-use; live Worker batching with generation/revocation fences, WAL/restart; and target-host 64/256/1024/4096 p95/p99, GPU, CPU, peak RSS, energy, queue and cancellation evidence remain unqualified. No choice or promotion is made by this PR.
