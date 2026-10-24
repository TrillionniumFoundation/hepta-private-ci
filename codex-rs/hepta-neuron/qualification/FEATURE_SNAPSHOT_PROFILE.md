# CPU feature snapshot materialization check

Scope: finite source-level CPU profiling of the existing HeadTensorBundleV2 consumer. Not a multi-Cell implementation, skill-count benchmark, encoder rerun, scientific efficacy result, or production qualification.

## Exact source and input custody

- Source parent: 17e55bb34e63888b8f03a8f001d963d5a9b69fac.
- Baseline consumer SHA-256: 56f88a126c1e0e55cd1b17db81bdce9ab205d0f6ea1196f71144235cd8d38e4d.
- Candidate consumer SHA-256: b72b53d72b3ccebea7230719b99ef90a4035728e47e73a923ea850e7cac1249b.
- Retained head manifest: 649e87c896ba117156d396216c3c91c2a1dc33f1291a396be8a6f158cc856654.
- Retained trained-head weights: e3e2d37c56760230d9408706a24ced1ef6650003ced7680a520efac1d42d3401.
- Inputs: first 32 retained synthetic-row Harrier-derived embeddings, hidden width 640, four candidate embeddings per row. These were not freshly re-encoded.

## Baseline first, then candidate

The baseline profiler identifies matrix multiplication, Tanh and finite-value checks as larger costs than copying. The optimization is deliberately narrow: detach().to(cpu, float32, copy=True) replaces detach().to(cpu, float32).clone(). It still creates an owned snapshot, including for already-float32 CPU inputs. No cache, generation, artifact identity, calibration or authority policy changes.

PyTorch 2.8.0+cpu, one CPU affinity and one intra/inter-op thread. Six alternating baseline/candidate rounds after 50 warmup calls. Each input is the same admitted batch; 64/256/1024/4096 below are **call counts, not distinct skills or Cells**. Maximum process RSS: 441188 KiB. No CUDA/device-transfer validation.

| Input dtype | Calls per round | Baseline median us/call | Candidate median us/call |
|---|---:|---:|---:|
| torch.float32 | 64 | 978.180 | 958.609 |
| torch.float32 | 256 | 1018.730 | 979.835 |
| torch.float32 | 1024 | 944.793 | 922.489 |
| torch.float32 | 4096 | 932.216 | 921.752 |
| torch.float64 | 64 | 908.644 | 884.949 |
| torch.float64 | 256 | 958.140 | 935.078 |
| torch.float64 | 1024 | 937.922 | 911.274 |
| torch.float64 | 4096 | 949.554 | 899.565 |

Small timing changes are descriptive and host-specific, not statistically established general speedups. The deterministic allocation result is stronger: over 64 float64 calls, aten::copy_ count falls from 1792 to 1664 and aten::empty_strided from 1152 to 1024. At this shape, avoiding a second float32 snapshot saves 409600 transient bytes per call (not retained-RSS savings). Float32 copy counts remain 1664 in both paths.

## Safety validation

- Existing 13 tensor-bundle tests pass against candidate (explicit module substitution verified).
- Added regression tests bring the suite to 15 passing tests.
- Float32, float64, float16 and bfloat16 inputs; contiguous, non-contiguous strided and overlapping expanded views.
- Bit-identical outputs, preserved snapshot strides, detached/autograd-free owned snapshots, no source-buffer alias.
- A forward pre-hook mutates the original caller buffer after snapshot creation; model inputs and expected output remain unchanged.
- Non-finite values and float64 values overflowing during float32 conversion are rejected.
- Existing manifest/weights/base/profile integrity rejection tests remain passing.

Known limit: no guarantee of atomicity against concurrent writes while taking the snapshot existed before this patch, and none is added. Copying is retained rather than replaced by unsafe shared aliases. Remote CI is not awaited per user instruction.
