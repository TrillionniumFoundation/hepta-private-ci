# Cached Pooled Feature versus Token Query: measured CPU readout V1

**Shadow-only.** This is a bounded, real CPU *readout kernel* experiment,
not evidence of a running shared Encoder service, production Worker batch,
valid source entitlement, NDU promotion, or learned-task improvement.
This PR is stacked on #1894, which is stacked on #1881 and #1827; it must
remain Draft and should not be merged directly into production `main`.

## Why this comparison matters

An unfair baseline recomputes masked mean pooling for every Cell, then calls
that repeated work a benefit of token attention. This experiment makes the
pooled baseline competitive: once for one approved, already-encoded observation
it computes and caches **one masked pooled vector**. The other arm prepares
one masked token matrix and then pays for its Cell-specific attention. The
*same* physically separate, initialized, frozen `CellHead` parameter bank
serves both readouts. Each arm gets the identical Head weights and feature
source, with alternating measurement order and equal CPU output synchronization.

The per-Cell Head count for input width `d`, rank `r`, and class count `c` is
`d + 2*d*r + d*c + c`. The shared input matrix is physically retained **once**
in this local process. Both arms return actual logits, which are consumed by a
checksum. Numerical equivalence to the original unoptimized per-Cell kernels
is checked before measuring.

## Offline harness usage

Provide frozen, group/time-disjoint model snapshot rows and existing pinned
model, tokenizer, data, generation and scope metadata to
`measure_cached_head_cost(tokens, mask, labels, rows, pins, digest, cells=N)`.
The loader and strict schema validator from #1894 can optionally invoke this
readout measurement using the **same** locally captured token tensor. The
additional CLI flags are:

```
--cost-cells 64 --cost-rounds 20 --cost-warmups 2
```

`--cost-cells 0` (default) turns the measurement off. The selected sample is
only the **first validation input**; no label is used for the readout itself.
Both comparison arms run **serially** on CPU in one PyTorch process. This is
not a GPU fused kernel, batch scheduler, queueing latency, or concurrency test.

The fixed input validation enforces one principal/purpose/Organ/Cell scope,
source-disjoint splits, strict future time, full input hashes, bounded
generation/epoch, finite contiguous tensors and a complete frozen snapshot
SHA-256. The benchmark limits 1..4,096 Cell Heads, 1..128 rounds, 0..16
warmups, <=65,536 total Head invocations across arms, and <=256 MiB of
explicit FP32 Head weight tensors. Large p95/p99 require >=20/>=100 repeats,
respectively. Requests exceeding bounds are rejected before allocation.

Local Linux `/proc/self/statm` reports current **co-resident** process RSS
before Head-bank materialization, after bank creation and after shared input
preparation. These are **not** isolated per-arm RSS peaks and cannot be used
to claim a memory winner. CPU process time and batch wall time are measured,
with the observations separately named; no model load, Tokenizer work,
Encoder forward, training, scheduling, WAL or GPU energy is included in this
readout-only probe. Encoder cost is recorded separately by #1894's offline
real model capture when actual local pinned weights are present.

## Repeated and full-scale qualification

Run the original 31 prior tests and the new 16 readout tests from
`qualification/neuron-shared-encoder`:

```
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m pytest -q \
  tests/test_token_reader_v1.py tests/test_token_reader_offline.py \
  tests/test_token_reader_cost_v1.py
python -m compileall -q neuron_shared_encoder tests
```

A local CPU synthetic **single-trial smoke** on 2026-10-14 used frozen
384-dimensional, 12-token features, 8-rank Heads, one thread, no optimizer
and ONE timed round per scale:

| Active Cells | Cached pooled batch wall | Prepared token-query batch wall | Head weights |
| ---: | ---: | ---: | ---: |
| 64 | 1.87 ms | 2.95 ms | 1,868,288 bytes |
| 256 | 7.34 ms | 12.85 ms | 7,473,152 bytes |
| 1,024 | 32.44 ms | 55.07 ms | 29,892,608 bytes |
| 4,096 | 145.14 ms | 232.56 ms | 119,570,432 bytes |

These numbers are deliberately **not** a throughput guarantee or p95/p99;
process RSS varied with earlier allocations, and this experiment was NOT run
on the deployment target host. One observation is insufficient to select a
Head architecture. Do not present this as evidence that token attention loses
on future utility: it tests resource overhead, not learned accuracy.

## Additional blockers before product or learning promotion

1. **Genuine pretrained token-level hidden states**, approved task/corpus,
   externally verifiable source and license, and joint Laya question/options
   comparison with declared semantic compatibility.
2. **Train matched Heads on identical real model features**, independently
   freeze no-change predictions, group-disjoint holdout and future outcomes,
   report negative transfer and multiple Cell-task strata.
3. **Account for full computation:** Encoder forward/reuse, separate pooled
   feature cache, Token Query read cost, Head training, checkpoint/optimizer
   memory, per-request p95/p99, cancellation/fault paths, target CPU/GPU power.
4. **Production gating:** signed artifact loads, live source and Final-use
   checks, Q24 reference parity, Generation Fence, checkpoint CAS/WAL, recovery
   and independent NDU Evaluator -> Selector -> Executor. None of these are
   granted by passing this study.

The only supported conclusion is a shadow CPU readout-cost observation.
`production_admission=BLOCKED` and `selection_authorized=false` are invariant.
