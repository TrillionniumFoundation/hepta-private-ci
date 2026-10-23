# P41: actual private Head pools on a shared Linux host

The completed run allocated 1, 32, 256 and 4096 private native Head instances for
each of the two already trained P40 artifacts. Every instance owns its parameter
vector through `LoadedTaskHeadV1::from_artifact`; each was exercised by a real
prediction before measurement. This is replication of **two fixed artifacts**,
not evidence for thousands of independently learned tasks.

## Identity and scope

- Final source: `f8855a7ac07af47b618199a3a9ccb87ff9552a5c`; tree `231ed14ea73a71c6d2ac3fe353b1779419154f53`.
- Original P40 report: `22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6`.
- P41 report: `f4ed9cce8f33cb26764933cbc2b950239c9b7e2f8360410b051467a50ca8abe0`.
- Release pool binary: `42c69fcec3a2b5332893e6a417710df38fbc6cab3ca51ab1afe195db2fe4fc31`; a byte-identical copy is retained in the run directory.
- Exact paired request stream: `3bb13eaae37d0d72b245ce65aa28c81b057a542fe555d367a0f7758b392cd214`; 256 rows, 16,988,720 bytes.

The eight new processes ran serially and completed in 12.934 seconds.
Each required an 800 MiB address-space hard limit, checked its own proc RSS and
HWM, and had an external 90 second wall timeout. The total budget was 12 minutes.
These are head-only, zero-state, cached-feature observations. No Encoder or
optimizer ran, no thresholds changed, and no new quality trial was conducted.
All task/action admission stays false with `SHADOW_ONLY` and `DENY_ALL`.

## Actual resident storage

Both artifacts retain the same 135,256-byte parameter layout, including the
linear control's retained adapter slots. RSS includes the cached inputs, source
artifact buffers, manifest allocations, private weights, allocator and runtime.
The raw reports preserve baseline, post-load, post-warmup and final RSS/RssAnon.
Native `/proc/self/status` is read inside each child; no parent PID lookup or
`wait4` peak is substituted for its resident memory. One MiB means 1,048,576 bytes.

| Heads in one process | Private parameter bytes | Gated post-load RSS MiB | Linear post-load RSS MiB |
|---:|---:|---:|---:|
| 1 | 135,256 | 5.750 | 5.750 |
| 32 | 4,328,192 | 9.969 | 9.969 |
| 256 | 34,625,536 | 39.934 | 39.922 |
| 4096 | 554,008,576 | 554.465 | 554.465 |

At 4096 Heads, the private payload was 554,008,576 bytes, post-load RSS was
581,398,528 bytes, and anonymous RSS was 580,161,536 bytes for both artifacts.
The largest sampled post-exec HWM was 582,201,344 bytes. Ownership follows the
source-bound owned-Vec API and observed scaling; this is not physical-page
attestation or a measurement of a resident Encoder.

## Dispatch and full fanout

Each process first scored all 256 reference rows through Head 0 and warmed every
private Head once. It then measured 4096 round-robin indexed single-Head calls,
followed by 16 calls that each score one input through all resident Heads.
Fanout timing includes collecting every output. Reference comparisons are
outside those timing intervals. An additional 16 reference calls are recorded.
The total observed execution schedule contains 184,034 native predictions.

These timers run inside the native process: JSON parsing, pipe IO and response
serialization are excluded. P40 round-trip timings include IO and therefore
measure a different interval. Raw integer-nanosecond samples are retained.
Single-Head quantiles use nearest rank; the 16 fanout observations report only
median and maximum, not tail quantiles.

| Artifact | Heads | Dispatch p50 ms | p95 ms | p99 ms | Fanout median ms | Fanout max ms |
|---|---:|---:|---:|---:|---:|---:|
| gated | 1 | 0.028691 | 0.041743 | 0.083063 | 0.028578 | 0.049079 |
| linear | 1 | 0.029524 | 0.041909 | 0.089217 | 0.030333 | 0.030849 |
| gated | 32 | 0.029242 | 0.051739 | 0.105431 | 0.949162 | 1.217635 |
| linear | 32 | 0.029849 | 0.059410 | 0.150305 | 1.037993 | 1.426035 |
| gated | 256 | 0.029348 | 0.042854 | 0.097743 | 8.014128 | 8.819103 |
| linear | 256 | 0.030417 | 0.052348 | 0.098766 | 8.820510 | 14.760913 |
| gated | 4096 | 0.096087 | 0.312126 | 0.732163 | 163.999591 | 660.982911 |
| linear | 4096 | 0.033130 | 0.059202 | 0.108711 | 147.681460 | 151.203510 |

The gated 4096-Head run contains substantial timing variation. All observations
are retained, with no outcome-driven rerun or sample selection. A sequential
shared-host run cannot establish an intrinsic gated-versus-linear cost ranking,
target-device performance, an end-to-end routing budget, or energy consumption.

## Verification

The separate crosscheck rehashed all 256 complete request lines, including their
trailing newlines, against the original P40 per-row request digests. It checked
2048 reference predictions with exact equality to P40, all 32,768 single-Head
timings, all 128 fanout timings, source Git objects, Head bytes and the binary.
The closed processes' proc measurements are retained observations, not later
reobservations. The unchanged P40 report and its binary remain independently pinned.

Validation retains 11 Python regression tests, 110 owning Rust library tests
(0 skipped, local nextest 0.9.149), and warning-free scoped release Clippy.
Two tiny native fixture pools and six invalid-input rejections are execution
checks only. Cargo's automatic fix command could not open its local locking
listener in this environment; the read-only scoped Clippy check passed.
No remote CI completion is claimed by these local results.

## Reproduction without encoding or retraining

Use a fresh clean checkout at the recorded source. Build the release example
`native_task_head_pool` with `--locked --offline`. Materialize a P40 input directory
by copying the retained `native-results/` evidence from
`qa/stem-bakeoff/evidence/20261022-native-task-head/`, and restore the existing
`20261022-real-multimodal` archive into its `restored/` subdirectory with
`multimodal_evidence.restore_evidence` and the fixed archive manifest pin
`2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e`.
This reconstructs cached features and original cohorts without an Encoder.

Run `qa/stem-bakeoff/native_task_head_pool.py --help` for the required original
report, binary and clean-source pins and a new external output directory.
`prepare_inputs` must reproduce the exact request-stream hash above before any
child starts. A new run creates new resource observations; it does not replace
this retained run. The full original request stream, raw child reports, raw
sample arrays, original Head bytes and copied binary are retained in
`/tmp/hepta-p41-native-pools-f8855a7`. The evidence index lists every byte hash and accompanying log.
