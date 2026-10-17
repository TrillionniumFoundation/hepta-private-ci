# V7 original physical gated-Head fleet CPU probe (separate from pretrained Stem)

**Strictly SHADOW_ONLY / DENY_ALL.** This is a bounded original Torch CPU execution of
lightweight private Head tensors, with **synthetic 384-dimensional features**. It
is **not** an execution of the original Granite97 Encoder, original 421M
weights, multimodal sensing, independent tasks, durable CNS/FinalUse or the
user's dot/production host. It tests only whether a practical resident
private-Head tensor bank and microbatch arithmetic can be executed and
metered without inventing pretrained system throughput.

## Source and setup

- Source: `stem_v7_physical_heads.py`, exact SHA256 in each receipt row.
- Real `torch` CPU FP32, one CPU Torch thread, deterministic seed 7347, ranks
  384→8→384, one synthetic immutable 384D feature shared among 32 active Heads.
- 5 actual trainable tensor banks: `up`, `down`, `gate`, `readout`, `biases`;
  6,914 parameters per Head (count derived from original tensor `.numel()`).
- Separate child process for each fleet size: 64, 256, 1,024, 4,096 physical
  resident Heads. Eight warmup forwards and **64 timed physical forward batches**
  per size. `head_forward` gathers 32 selected Heads, runs two batched matrix
  multiplies, a gate, and a readout; no Encoder forward or Head learning occurs.
- Original physical process RSS is read from Linux `/proc/self/status`. Torch
  import/startup and PyTorch allocator overhead make RSS larger than theoretical
  Head tensor bytes. Percentiles are nearest-rank samples from 64 *unloaded*
  CPU microbatches and should not be treated as a production p95/p99 SLA.
- Each exact source process reported its original raw FP32 output SHA, CPU/wall
  within benchmark, actual parameter tensor counts, before/after RSS, and
  `energy_joules=null`, `gpu_vram_bytes=null`. No post-hoc fitting selection.

## Newly executed isolated analysis-container result — 2026-10-15

| Physical resident Heads | Allocated private parameters | RSS after allocation (KiB) | Batched 32-Head p50 (ms) | p95 (ms) | p99 (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 442,496 | 261,956 | 0.3703 | 0.5593 | 0.7125 |
| 256 | 1,769,984 | 268,120 | 0.4062 | 0.6702 | 0.8059 |
| 1,024 | 7,079,936 | 295,764 | 0.3920 | 0.6210 | 1.0566 |
| 4,096 | 28,319,744 | 375,640 | 0.3652 | 0.4102 | 0.4718 |

The quantiles are measured in four independent process runs; the low 4,096
p95 is a scheduling/cache artifact of this small non-competitive synthetic
microbatch cohort, **not evidence that performance scales better with more
resident Heads**. No model was loaded and no concurrent 4,096-query service
was exercised. Peak and after-RSS and exact phase clocks are in the JSON.

## Actual local validation and limitations

`test_stem_v7_physical_heads.py`: **6/6** local actual Torch CPU/mechanism
regressions passed. They check deterministic physical tensor forwards, complete
parameter allocation, bound active IDs, receipt field integrity and rejection of
fake pretrained/dot claims. No real source family or human-rated output used.
The fixed source suite `test_stem_selection_v7.py` separately passed **34/34**
normal and **34/34** optimized stdlib tests; those are contract mechanics only.

The GitHub Action `hepta-stem-v7-physical-heads.yml` is a **new hosted rerun
candidate**, not proof until its exact HEAD jobs complete. It measures on its
own Ubuntu runner; its RSS/latency may differ and must not be substituted
into the local receipt. Its artifact contains only numeric/sanitized data and
source SHA; no raw pretrained weights, modalities or answers are uploaded.

## Reproduce

```
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=qualification/stem-cell-v1 \
  python -m unittest -q qualification/stem-cell-v1/test_stem_v7_physical_heads.py
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python \
  qualification/stem-cell-v1/stem_v7_physical_heads.py \
  --output /tmp/stem-v7-fresh-physical-receipt.json
```

The target path must not exist. Four source-bound subprocess observations are
sealed create-only. **DRAFT / SHADOW_ONLY / DENY_ALL / no model selection, main
merge, or production FinalUse.**
