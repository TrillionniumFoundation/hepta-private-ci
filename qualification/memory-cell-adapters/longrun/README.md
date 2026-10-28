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
unchanged throughout the first execution and its infrastructure recovery.

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

## Costs and their limits

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

### Separate clean cost replication: running remotely, results pending

The proposed local `run-03-clean` was **not started**. After the original
archive passed its complete verification, the 200 MiB launch-space guard
failed; a subsequent observation found only 15,626,240 free bytes. No local
clean-run directory, trainer or monitor was created.

The same frozen protocol was subsequently launched on an independent GitHub
Actions runner:

- [Run 40681620656](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40681620656),
  job `122793476485`, request `clean-cost-20261028-01`.
- Source commit `773e8c5540521861ab18b1c61268069d6610279a`.
- Started at `2026-10-28 11:39:17 UTC`; last observed at `11:46:00 UTC` with
  checkout and Python setup successful and the replication step in progress.
- Ubuntu 24.04 and Python 3.12, with pinned CPU Torch 2.8.0+cpu and NumPy 2.3.5.
  The runner hardware differs from the original environment; actual hardware,
  dependency and preparation receipts will accompany its results.

**Final remote results and costs are pending.** The requested extra work is
216 fits, 129,600 gradient steps and 4,147,200 sample presentations under the
same seeds, source data and budgets. The remote experiment consumes the
verified canonical cache; it does not rerun the encoder. Historical monotonic
timestamps are not compared across hosts, and matching final parameter bytes
across different CPUs is not a success requirement.

The complete remote artifact must retain its outer preparation and hardware
records as well as the inner `run-03-clean` directory. Its actual costs will be
reported separately and added to research totals. Repeated work does not
replace the original interrupted attempt or remove the unknown terms from
the first execution's costs.

## Complete bounded evidence transport

`pack_evidence.py --kind chain` packages both original segments, every saved
model tensor, SQLite snapshot, request, raw response and resource sample into
`evidence/longrun64x3`. Archive and inventory parts are at most 400,000 bytes.
The raw source directories remain intact. The independent verifier streams
the archive and checks every member's SHA-256 and byte count.

The publication directory also includes unmodified `RAW_FREEZE-run-01.json`
and `RAW_FREEZE-run-02-resume.json`, allowing source-binding checks without
unpacking the archive. A clean replication uses the separate
`evidence/longrun64x3-clean` directory and its own raw FREEZE copy.

To verify or restore a published transport:

```bash
python -I -B evidence/longrun64x3/restore.py --verify-only
python -I -B evidence/longrun64x3/restore.py --output /absolute/new/directory
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

All execution paths here are Python research paths. These receipts do not
certify a native Agentd runtime, and a CI source-binding check must not be
described as CI having rerun the long experiment.
