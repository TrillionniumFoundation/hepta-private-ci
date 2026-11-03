# Bounded semantic-memory maintenance experiment

This directory implements and records **64 sequential maintenance cycles for
each of seeds 731, 732 and 733**. It tests a fixed, canonical-address memory
problem with eight entities and three 4-bit policy values per entity. It does
not establish open-domain language memory, spontaneous network organization,
native Hepta integration, or an advantage over exact SQL storage.

## Locked protocol and implementation

[LONGRUN_PROTOCOL.json](LONGRUN_PROTOCOL.json) was locked before training with
SHA-256 `3f7a09a1158b3e40cd33157e0da727deda13fa6654950b01449d419c6cb9a007`.
The protocol, original manager, workers and runtime dependencies remained
unchanged throughout the first execution, its infrastructure recovery and
the completed clean CI replication.

- `manager.py` owns source truth, versioned SQLite mutations, sequence control,
  independent scoring and cost receipts.
- `fit_worker.py` performs one real Adam fit: **600 steps, batch 32, learning
  rate 0.01, sampling seed = seed + stage**. It replays all currently active
  canonical rows and updates the actual adapter and task head.
- `owner_read.py` runs in a fresh process after each trainer exits. It loads the
  saved tensors, reads all eight addresses through the real Python SQLite
  owner, checks stop behavior, and returns raw outputs without targets or
  scoring logic. Its parameter connection denies `sources.payload` through a
  SQLite authorizer. The explicit SQL comparator receives access to that
  column and uses the same addresses and source states.

Every eighth cycle deletes the registered entity and rebuilds a cell from its
initial architecture and seed, without loading prior parameters. The rebuild
uses only the seven active sources. At the following cycle the deleted entity
returns as a separately versioned source; the last-cycle deletion remains
inactive at the evaluation horizon. Source-status rejection is checked before
model prediction. Training and reader processes execute serially.

The original pretrained semantic checkpoints, source records and canonical
feature cache come from `memory-adapter-formal-01`. This experiment never opens
that study's held language or RESULT file. The frozen encoder is referenced by
identity and storage size; maintenance consumes its previously computed
canonical features and does not run the encoder again.

## First complete execution, with an explicit interruption

The first execution completed **192 cycles and 216 successful fit phases**:
192 updates and 24 clean rebuilds. An execution-server transport failure
interrupted one additional attempt. The original segment is retained as
`run-01`; `run-02-resume` continues it and contains the combined RESULT and
CYCLES records. [SUMMARY.json](SUMMARY.json) collects the delivery-level
measurements.

| Final-cycle checks, summed over three seeds | Parameter memory | Exact SQL |
| --- | ---: | ---: |
| Active values | 1,512 / 1,512 | 1,512 / 1,512 |
| Unchanged active facts retained | 1,305 / 1,305 | 1,305 / 1,305 |
| Changed active facts | 207 / 207 | 207 / 207 |
| Deleted-source refusals | 24 / 24 | 24 / 24 |

These are repeated, correlated checks on a small deterministic workload, not
1,512 independent generalization trials. Full replay is available at every
update. The parameter system matched exact SQL correctness on this workload;
this result does not demonstrate a storage or compute benefit.

The independent full audit in
[`../evaluation/AUDIT-longrun-complete.json`](../evaluation/AUDIT-longrun-complete.json)
passed 7,198 checks, covering all 216 phases and 435 completed subprocess
receipts: 216 trainers and 219 readers. It independently reconstructed source
versions and values, training target/feature hashes, parameter continuity,
clean initializations, serial process order and result aggregates.

### What happened at the interruption

`run-01/INFRA_INTERRUPTION.json` records the lost process identities and the
absence of subsequent file growth. At that point 79 complete cycles and the
update of cycle 80 were durable. Seed 732, stage 16's rebuild had a request and
preflight but no checkpoint or completion receipt. A starting child was seen
in the last resource sample, so the absence of an output is **not evidence of
zero work**.

`resume.py` independently verified the saved source state and resumed that
rebuild. `REQUEST_RELOCATION.json` proves that its original request changed
only in the output path. The existing stage-16 update was not rerun. All
original segment files retained the same tree identity throughout recovery.

The interrupted attempt's CPU, gradient-step count and exit status remain
`null`. The gap from the old segment's last sample to the resumed segment's
first sample is **398.263 seconds**. Its resource integral is not reconstructed
by assuming zero usage or extrapolating nearby samples.

## First-chain costs and their limits

The completed child processes consumed **1,700.507 CPU seconds**: 1,264.759
for trainers and 435.749 for readers, including their process startup and
shutdown. Their measured wall durations sum to 1,740.308 seconds. The unknown
interrupted attempt and unrecorded final CPU of the first driver are additional
costs, so these figures are not a complete exact research total.

| Accounted storage | Bytes | Meaning |
| --- | ---: | --- |
| Retained fitted checkpoints | 7,905,954 | All completed fitted parameter versions |
| Initial checkpoint copies | 96,172 | Three pretrained semantic cells |
| Source SQLite files and snapshots | 6,336,512 | Explicit current/historical source evidence |
| Canonical feature cache | 23,189 | Shared, stored input features |
| Shared encoder reference | 127,536,988 | Referenced encoder/tokenizer assets, not copied into each cell |

Source truth and historical checkpoint evidence remain stored. A clean rebuild
of the current cell is not a claim that all historical copies were physically
erased. The shared encoder cannot be omitted when discussing the complete
system's storage requirement.

Each of 219 fresh reader processes executed an eight-address parameter loop
and an exact-SQL loop. Median loop times were **2.210 ms** and **0.0835 ms**,
respectively. Total measured loops were 0.638 seconds and 0.0329 seconds.
These loop measurements exclude shared imports, checkpoint loading,
connection setup and snapshot hashing; they are not standalone deployed
latency measurements. Both the matching SQL accuracy and its lower observed
loop cost must remain visible in any comparison.

The outer resource monitor sampled the driver and descendants every 200 ms,
retaining 7,065 raw samples across the two segments. The largest observed
sequential tree sums were RSS 509,120,512 bytes and PSS 434,688,000 bytes;
independent child peaks were not added. The resumed monitor exited successfully,
but 36 sampling-read errors leave about 18.347 seconds of its memory integral
unknown. Both segments also retain their ordinary sampling gaps. Sampled
integrals are estimates over observed intervals, not exact continuous costs.

## Separate clean cost replication: completed in GitHub Actions

The proposed local `run-03-clean` was **not started**. After the original
archive passed its complete verification, the 200 MiB launch-space guard
failed; a subsequent observation found only 15,626,240 free bytes. No local
clean-run directory, trainer or monitor was created.

The same frozen protocol subsequently completed successfully on an independent
GitHub Actions runner:

- [Run 40681620656](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40681620656),
  job `122793476485`, request `clean-cost-20261028-01`.
- Source commit `773e8c5540521861ab18b1c61268069d6610279a`.
- Started at `2026-10-28 11:39:17 UTC`; all steps succeeded and artifact
  `12814206358` was published at `11:54:18 UTC`.
- Ubuntu 24.04, Intel Xeon Platinum 8370C with four logical CPUs, Python
  3.12.15, pinned CPU Torch 2.8.0+cpu and NumPy 2.3.5. This hardware differs
  from the original local environment; the full receipts are preserved.

The clean execution completed **192 cycles, 216 fits and 219 fresh readers**,
with no execution failures. Both parameter memory and exact SQL reproduced
the table above: active 1,512/1,512, retention 1,305/1,305, changed 207/207 and
revoked 24/24. The independent
[CI audit](../evaluation/AUDIT-longrun-ci.json) passed **8,563 checks**, and the
[cost and tensor-byte audit](../evaluation/AUDIT-longrun-ci-costs.json) passed
**11,609 checks**. They cover all 435 child receipts, replay inputs and sampling
schedules, saved parameter bytes, source access, serial process order and raw
resource samples. These are verification checks, not statistical samples.

The remote experiment consumed the verified canonical cache and did not rerun
the encoder. Historical monotonic timestamps were not compared across hosts.
All 216 fitted parameter digests happened to match the first chain, but
cross-hardware bit equality was not a success requirement. The same seeds,
addresses, targets and schedules make this a reproducibility and cost
replication, **not a second independent generalization sample**. The two runs'
quality denominators must not be pooled to imply additional statistical power.

### Clean cost scopes

The detailed ledger is
[COST_SUMMARY.json](evidence/longrun64x3-clean/COST_SUMMARY.json), backed by the
unchanged preparation, hardware, lifecycle and packaging receipts.

| Measured scope | Time |
| --- | ---: |
| Dependency installation, restore and preparation wall time | 24.251046586 s |
| Lifecycle observation window | 858.478325932 s |
| Completed fit and reader child CPU | 852.535687 s |
| Driver wait4 CPU, including waited descendants | 856.774937 s |
| Monitor subtree CPU measured by its parent | 954.746828 s |
| Outer wrapper plus waited children CPU | 977.339552314 s |
| Separate archive packaging CPU | 4.456184323 s |

The CPU rows are nested accounting scopes. The wrapper already includes its
waited trainer, reader, driver and monitor descendants; those rows must not be
added to it again. Packaging is a later, disjoint process, bringing observed
wrapper-plus-packaging CPU to **981.795736637 seconds**. Checkout/Python setup
CPU, upload CPU and preparation memory/storage integrals were not measured.
Hardware differs, so the shorter elapsed time is not an algorithmic speedup
claim over the first execution.

The uninterrupted lifecycle window contains 3,802 samples and 29 sample-read
errors. RSS/PSS intervals totaling **11.850252394 seconds** and storage
intervals totaling **1.344647791 seconds** remain unknown. Sampled peak tree
RSS is 548,093,952 bytes and peak PSS is 448,604,160 bytes. The monitored storage
root contains lifecycle output and retained evidence; it excludes installed
dependencies, restored prior evidence, repository content, remote storage and
the shared encoder asset. `full_cost_exact` therefore remains **false**.

Each clean reader process runs the parameter loop and then the SQL loop. The
median eight-address slices are **1.320548 ms** and **0.116704 ms** respectively;
their nearest-rank p95 values are 1.382287 ms and 0.141080 ms. The median whole
reader process is 1.344905092 seconds and includes imports, loading, both arms
and shutdown. Checkpoint-load median is 3.310639 ms and excludes imports and
process startup. These scopes are not independent deployment latency or an
uncached storage benchmark. SQL matched correctness with the lower observed
read slice and did not require parameter fitting.

Clean storage includes 7,906,432 bytes of fitted checkpoints, 96,172 bytes of
initial copies, 86,016 bytes of current SQLite files, 6,193,152 bytes of
historical SQLite snapshots and 537,522 bytes of explicit source JSON. The
23,189-byte canonical cache and **127,536,988-byte shared encoder reference**
remain separate accounts. Historical parameter and source copies were retained;
deletion/rebuild does not establish physical erasure.

Across the first chain and clean replication, actual successful work totals
**432 fits, 259,200 gradient steps and 8,294,400 sample presentations**, plus
the original interrupted attempt with unknown steps and CPU. The completed
fit/reader children alone consumed 2,553.042976 CPU seconds across both runs.
Adding the first chain's completed-child CPU to the disjoint clean wrapper
and packaging gives an observed lower bound of 2,682.303025637 CPU seconds.
That lower bound still omits first-chain driver/monitor overhead, interrupted
work, earlier formal studies, other preparation and validation, checkout/setup
and upload. It is not total project compute. The first chain's **398.263-second
unknown interval remains unchanged**, and both executions keep
`full_cost_exact=false`.

The experiment supplies evidence of bounded repeated maintenance with full
replay and source controls. It does not establish storage-compression or
complete-cost advantages over exact SQL, language-access improvement,
spontaneous cell organization, general memory or native serving.

## Complete bounded evidence transport

`pack_evidence.py --kind chain` packages both original segments, every saved
model tensor, SQLite snapshot, request, raw response and resource sample into
`evidence/longrun64x3`. Archive and inventory parts are at most 400,000 bytes.
The raw source directories remain intact. The independent verifier streams
the archive and checks every member's SHA-256 and byte count.

The publication directory also includes unmodified `RAW_FREEZE-run-01.json`
and `RAW_FREEZE-run-02-resume.json`, allowing source-binding checks without
unpacking the archive.

The [clean CI transport](evidence/longrun64x3-clean/README.md) is a separate
**37-file, 8,086,169-byte delivery**. Its 18 parts preserve the original
7,089,136-byte tar without recompression; its SHA-256 is
`20c348466832e026e6d9280ea542f50f252bf9e633f64ea3fec0a0c900442a90`.
It contains the entire outer CI preparation/hardware output and inner
`run-03-clean` tree: **4,153 regular files, 633 directories and 21,766,558 raw
file bytes**, including every actual checkpoint. Three inventory chunks,
GitHub origin metadata, packaging, `RAW_FREEZE-run-03-clean.json`, core raw
receipts, cost summary and verification records accompany the archive. Every
publication file is at most 400,000 bytes. All original ZIP/tar/raw evidence
and the first-chain archive remain intact.

To verify or restore a published transport:

```bash
python -I -B evidence/longrun64x3/restore.py --verify-only
python -I -B evidence/longrun64x3/restore.py --output /absolute/new/directory
python -I -B evidence/longrun64x3-clean/restore.py --verify-only
python -I -B evidence/longrun64x3-clean/restore.py --output /absolute/new/clean-directory
```

The restore destination must not already exist. Restoring evidence does not
run training or download dependencies.

## Reproduction boundary

The historical protocol contains the absolute initial-study path
`/workspace/scratch/76e2020e4b36/memory-adapter-formal-01`. An exact manager rerun
requires that location to be restored; the frozen manager is not silently
parameterized to another input tree. The evidence includes the required
historical training receipt as `INITIAL_TRAINING.json`, plus the inputs and
three initial checkpoints. They can reconstruct the required subset of the
original study tree:

1. Restore `INITIAL_TRAINING.json` as `models/TRAINING.json`.
2. Restore `run-01/inputs/{sources.json,canonical.npz,development-encoder.json,
   training.process.json}` at the initial-study root.
3. Restore each `run-01/inputs/seed-N` as `models/seed-N/semantic`.
4. Use the matching frozen repository runtime modules and the recorded CPU
   Torch/NumPy environment. The maintenance experiment needs the stored
   canonical features; it does not require downloading encoder weights again.

Launch the original manager through `qualification/memory-cell-v9/learning/
resource_monitor.py`, passing a new output directory, a 200 ms interval and a
3,600 second timeout. The resource monitor must watch the complete actual
output directory. Use the recorded Torch interpreter for the manager and its
children. `resume.py` is intentionally specific to the documented interruption
and is not a generic resume command for arbitrary partial runs.

All execution paths here are Python research paths. The named GitHub Actions
run actually executed the full clean Python experiment; these receipts do not
certify a native Agentd runtime. A separate native CI job that only checks
source binding must not be described as having run this maintenance protocol.
