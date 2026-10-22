# P40 native task Head evidence

This package retains the actual Rust task-Head replay and descriptive cost
observations from a shared Linux host. It is **head-only research evidence**.
It does not qualify a target device, measure energy, train a policy, or constitute
a new independent multimodal quality trial. All task/action admission remains
false, with `SHADOW_ONLY` / `DENY_ALL` posture.

## Exact bindings

- Runtime report: `native-results/report.json`, SHA256 `22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6`.
- Tested local source: `762bbc0a335f1d6cc663712b7e5693c496758dad`.
- Tested source tree: `74687598e9cf24d3bcd479b9f65a7e2903ab3b4f`.
- Actual release binary SHA256: `86ff023ed2be26b85b9ad47d7f2efb5f0e91a0cb41b7c9bf9df4bef4351eea90`. The compiled binary itself is not included.
- Original experiment report: `26c74e604c9404f93677d64687603f50afbf0414e7773c07a4237f5f9cbe0211`.
- Original reconstruction archive manifest: `2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e`.

The published source commit is `ace39fc0ce930b057001ee1566e938ccf86990c5`; its Git tree equals the tested local tree. The original runtime report retains its local source SHA verbatim;
publication mappings do not rewrite experimental evidence. Source and binary
hashes provide identity bindings, not independent compiler attestation.

## Preserved contents

`native-results/` contains the original report and all 16 files indexed by that
report: two bounded task artifacts, ten per-row response JSONL files and two
cost files. **The report and every JSONL file are copied byte for byte.**
`checks/` retains two independent checker scripts and their original observation
receipts, plus the packager. Historical absolute paths inside receipts are kept
unchanged. `validation.json` gives the package-relative locations and scope.
`manifest.json` lists SHA256/size/origin for every payload; `SHA256SUMS` also
indexes the manifest itself. Those two index files are not self-indexed.

## Numerical and presence results

The independent check verifies 2,560 rows and reconstructs each source-record
digest from the original cohort and feature-bank provenance. Present-row class
and confidence decisions match the original NPZ ledgers exactly. Temperature
remains 0.25, confidence threshold 0.7 and the fixed absolute tolerance 2e-5.
Maximum logit difference is 1.03712081909e-05; maximum probability
difference is 4.11259987043e-06.

For each Head, the 256 missing-text and 256 missing-image rows return null
predictions. Mixed-presence input scores 86 rows and rejects 170. Shuffled-image
rows remain present and are evaluated; this guard does not detect an incorrect
pair. The 14 invalid-CLI rejections are retained observations of the original
execution, not probes reexecuted by the independent checker or packager.

## Observed cost

Each Head used one persistent process, 20 warmup requests and 1,000 measured
requests cycling through 256 fixed paired inputs. Nearest-rank quantiles are
independently recomputed from the preserved integer-nanosecond samples.

| Head | p50 ms | p95 ms | p99 ms | Final native RSS B | wait4 lifetime peak B |
|---|---:|---:|---:|---:|---:|
| gated | 0.300797 | 0.534371 | 1.038540 | 1,708,032 | 313,290,752 |
| linear | 0.296997 | 0.441053 | 0.613730 | 1,740,800 | 320,225,280 |

Latency includes pipe IO, native JSON decoding/inference/encoding and Python
response decoding. Encoder execution, request construction, startup and
validation are excluded. RSS is recorded through the source-bound
PPid/NSpid/executable/starttime-checked proc path; closed processes cannot be
reobserved retrospectively. **The wait4 lifetime peaks may include inherited
pre-exec parent memory and are not native resident-memory estimates.**
These sequential shared-host observations do not establish an intrinsic cost
ranking between gated and linear architectures or target-device performance.

## Original logs and source scope

`logs/stem_tests.raw.log.gz` losslessly preserves the original log reporting
273 tests passed in 9.197s, captured for
`73bf9a43338bbfec6eff1a3b66348164d4b676d2`. Its source matches the runtime
report: **false**.
Scope: Original 273-test run for 73bf before mechanical Rust parameter-comment and P39 codespell revisions; no claim of a test rerun on final 762bbc0.

`logs/release_build.raw.log.gz` losslessly preserves the optimized release
build log captured for `762bbc0a335f1d6cc663712b7e5693c496758dad`.
Raw and compressed byte hashes are recorded separately in `validation.json`.
The packager does not transform an earlier test run into an exact-head rerun.
The final replay's raw stdout is retained losslessly in `logs/native_replay.raw.log.gz`; its parsed JSON equals the preserved final report.


## Reproduction boundary

Reconstruction uses the existing repository archive at
`qa/stem-bakeoff/evidence/20261022-real-multimodal/`, whose manifest pin is above.
The cached bank and trained Heads are reused; the native replay does not download
or run a foundation Encoder. At the pinned source, build the
`codex-hepta-neuron` example `native_task_head` in release mode, then run
`qa/stem-bakeoff/replay_native_task_head_v1.py` with `--archive-directory`, a new
`--output`, the compiled `--binary`, and `--measure-cost`. New runtime cost samples
will differ from these retained observations. The independent scripts expose
their complete command-line interfaces with `--help`.

Original request JSONL streams were ephemeral and are reconstructed by the
replay; their hashes and each response's request digest are retained. The
independent observation explicitly distinguishes source-digest reconstruction
from independent reconstruction of those deleted complete request streams.
