# E5 physical CPU Head fan-out: 64–4096 Cell measurement (2026-10-14)

**Research only — DENY_ALL. No pretrained weights or production Rust Worker were run.** The fixed Q24 feature and all labels are synthetic. This experiment physically executes the exact 9,744-parameter (384D feature, 64D private state, rank-8, 8-class) State-Gated Head geometry and CPU SGD calculations in isolated Python/PyTorch processes. Model parameters are **actually resident**; this is not a linear memory estimate.

## Why it matters

Previous E5 contracts checked untrusted counters but did not physically assess whether thousands of tiny independently trained Cells are viable. We measured four resource cohorts, each with all logical Cell weights resident and approximately 10% active Cells. Each cohort runs four separate OS processes:

1. `shared_sgd`: one physical immutable Q24 feature tensor borrowed by active Cells, 2 forward repetitions and one real CPU SGD update per active Cell.
2. `cloned_sgd`: *byte-identical* feature cloned once per active Cell, the same seeded independent Head weights, repetitions and SGD work; identical prediction digests are verified.
3. `shared_inference`: shared feature, no optimizer or gradients, 20 repetitions, identical per-Cell Head module objects.
4. `packed_inference`: only **six contiguous weight tensors**, actual `torch.bmm` forward over active Cell indices, **zero-stride** view of one shared feature vector, 20 repetitions and no training.

The nontrivial batch implementation was compared with the actual per-Cell modules both **before and after** one exact SGD update on distinct Cell labels; the parameter tensors agree within prescribed float tolerance. A regression verifies that packed Head gradients **cannot enter the shared feature or the Cell-private input state**. The packed route is a prototype, not an installed Neuron V1 model-port backend.

## Measured local CPU outcomes

Untrusted one-host observations, **one isolated process per configuration**, PyTorch 2.10.0+cpu, Python 3.13.5, psutil 7.2.2, one PyTorch CPU thread. Each separate process measures its own process-lifetime peak RSS. End-to-end request queueing, model input preprocessing, loaded foundation Encoder, security, durable storage, multi-device scaling and energy are not included.

| Logical Cells | Active | Module inference process RSS | Packed inference process RSS | Observed RSS difference | Loop-average per Cell, module → packed |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 8 | 258.0 MiB | 257.0 MiB | 1.1 MiB | 25.5 µs → 14.9 µs (1.71×) |
| 256 | 25 | 268.4 MiB | 264.3 MiB | 4.1 MiB | 25.9 µs → 13.5 µs (1.91×) |
| 1024 | 102 | 310.5 MiB | 293.2 MiB | 17.3 MiB | 26.0 µs → 12.4 µs (2.11×) |
| **4096** | **409** | **478.9 MiB** | **408.2 MiB** | **70.7 MiB** | **32.5 µs → 12.1 µs (2.68×)** |

The comparison is **loop wall time / returned output count**, not a per-request latency guarantee. A packed `torch.bmm` invocation is an entire active-Cell batch; dividing by active Cells measures amortized compute, NOT the observed service latency of an individual request. Only 20 batch repetitions were taken, so the raw batch p95/p99 columns are descriptive and `p99_independently_qualified=false`. One process per arm does not support a general confidence interval or universal speedup claim.

The 4096 resident FP32 Heads contain 39,911,424 parameters (~152.2 MiB *tensor payload*). Actual module-runtime RSS includes Python/PyTorch processes and tensor objects; packing leaves parameters resident but reduces Python module and tensor-object overhead. Sharing a single 384D input without packing saved only a small number of feature bytes and did **not** reduce total RSS by thousands of times.

## Source and raw evidence

Files:
- `e5_physical_head_fanout.py` and its unit tests: real module/head forward, cloned/shared feature identity, SGD weights changed, per-head timing and process RSS.
- `e5_packed_head_fanout.py` and its unit tests: actual packed CPU `bmm`, per-cell independent parameterization, input detachment, **forward and SGD update parity**.
- `e5_cpu_fanout_review.py` and its tests: rejects missing one of 16 experiments, incorrect population, unpaired controls, forged model/energy/p99 status, missing SGD updates, altered feature or output digests.
- `E5_LOCAL_CPU_HEAD_FANOUT_20261014.json`: source Git blob digests, 16 original receipt-set SHA-256, separate independent review SHA-256, process resource observations and **hard-disabled** acceptance flags.

The local evidence bundle `hepta_e5_actual_cpu_fanout_20261014.zip`, SHA-256 `943132cead74eca204697576fe54f085b9cac8faca4854e1942b1cb371614d3a`, contains the six exact source/test blobs, all 16 original process reports and the read-only analysis. No model weights, private text, private media or original training cases are included. Source blobs are checked against GitHub. A separate same-repository Actions workflow `hepta-e5-real-cpu-head-fanout.yml` will repeat the 16 isolated experiments and upload fresh receipts on **its own exact PR HEAD**; earlier local tests cannot certify that hosted run.

Local reproduction (fresh files required, four *separate processes* per cohort):

```sh
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e5_physical_head_fanout.py' -v
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e5_packed_head_fanout.py' -v
python -m unittest discover -s experiments/shared_stem_cell -p 'test_e5_cpu_fanout_review.py' -v
# See the dedicated workflow for all sixteen process invocations and source-bound review.
```

## What has NOT been established

No original Granite/mmBERT/EmbeddingGemma2 weight ran here; synthetic Head updates do not establish unseen semantic learning, task utility or independent future NDU. `packed_inference` has not been profiled for 4096-Cell **batched SGD**; only the three-Cell exact update parity was validated. There is no actual target-host Rust Worker queue, signed FinalUse, CAS/WAL replay, device thermal/power/GPU measurement, security blessing or production Cell Split. This is a local CPU microbenchmark that suggests a direction for further research. No model/Stem selection, production merge, release or privilege follows from it.

**Disposition:** preserve PR #1926 as Draft/Shadow, require exact-HEAD CI and `blocking-ci` without waivers, independently qualify native Worker, matched pretrained model tasks, OOD and future NDU before treating this as production evidence.
