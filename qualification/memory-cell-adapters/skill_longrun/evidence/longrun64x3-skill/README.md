# Original skill-maintenance CI evidence

The separately frozen skill study completed successfully in
[GitHub run 40742088819](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40742088819),
job `123006077672`, on 2026-10-28. The original artifact is
`memory-adapter-skill-longrun-40742088819-1`, artifact ID `12841410136`.
Its downloaded ZIP was required to match GitHub's advertised byte count and
SHA-256 before extraction. [ARTIFACT_ORIGIN.json](ARTIFACT_ORIGIN.json) retains
the source, workflow and artifact metadata; no signed download URL is retained.

## Exact source and archive identities

| Item | Identity |
|---|---|
| Source commit | `4693e8028fb8563ec730dcb55458a212389154a5` |
| Source tree | `df3224a5a13c1fcc0a41d3b0278a864174e12d7e` |
| Frozen protocol SHA-256 | `8eba86176ea3a42e19cdc7607859d34733ff82e037b3d8200a3b97924cab8c56` |
| Original GitHub ZIP | 14,172,080 B; SHA-256 `07106a74b014414be481a9d35080a3dc0a5323a17d7dc234ec34099dc2429733` |
| Original nested TAR/XZ | 14,171,396 B; SHA-256 `2f621ed540664d2239d13ef1965d62ccbfe1506f185ebfbb640ba5a28438f331` |
| Original TAR members | 5035: 4399 regular files and 636 directories |
| Expanded regular-file bytes | 64,564,040 B |
| Archive root | `memory-adapter-skill-longrun-output` |

The 36 `archive.*.part` files are contiguous slices of the original TAR/XZ,
each at most 400000 bytes. They were not recompressed. The JSONL inventories
record every original file and directory. [ARCHIVE.json](ARCHIVE.json) binds
the parts, inventories and original archive; [VERIFICATION.json](VERIFICATION.json)
records the verified complete restoration.

[SOURCE_BINDING.json](SOURCE_BINDING.json) checks all **19 frozen source and
protocol files** in the original [FREEZE](RAW_FREEZE-run-01-skill.json), plus the workflow
and run request, against their bytes in the source tree above and the current
checkout. Historical absolute labels are mapped explicitly; original requests
and receipts are not rewritten. This binding does not claim native V9 CI
coverage for the residual model.

## Verify and restore

From the repository root, verify the original archive without extracting it:

```bash
python -I -B qualification/memory-cell-adapters/skill_longrun/evidence/longrun64x3-skill/restore.py \
  --verify-only
```

Restore to a new, nonexistent destination:

```bash
python -I -B qualification/memory-cell-adapters/skill_longrun/evidence/longrun64x3-skill/restore.py \
  --output /tmp/hepta-skill-evidence
```

The helper uses its adjacent `ARCHIVE.json`, verifies every part and member,
and refuses unsafe names, links, sparse files, duplicate members or mismatched
bytes. It creates
`/tmp/hepta-skill-evidence/memory-adapter-skill-longrun-output/`, with the actual
experiment under `run-01-skill/`. Retain that layout when passing explicit path
mappings to the auditor. Restoring evidence does not execute a trainer, model
or experiment.

The original output contains all new checkpoints, source snapshots, raw sample
schedules, process requests/stdout/stderr, resource samples and CI accounting
receipts. Installed dependency wheels and the shared encoder weights are not
embedded; their versions, identities and storage reference are retained. The
initial Formal-01 archive remains a separately preserved dependency. This
README, source binding and independent audit summaries are later derived
material; the original TAR bytes remain unchanged.

## Program recovery and actual execution

The fixed protocol executed 64 cycles for each of seeds 731, 732 and 733:
192 update fits, 24 clean rebuilds, **216 fits**, 129600 steps and 4147200 sample
presentations. The 3 initial and 216 post-fit reads used **219 fresh processes**.
Every trainer exited before its post-fit reader began. The independent audit
checked all 435 current-run child-process receipts and decoded all 222
checkpoints, including the separately retained untrained initializations.

| Cycle-end endpoint | Parameter arm | Exact-SQL arm |
|---|---:|---:|
| Active programs recovered exactly | 1512/1512 | 1512/1512 |
| Changed programs | 207/207 | 207/207 |
| Unchanged active programs retained | 1305/1305 | 1305/1305 |
| Revoked requests refused | 24/24 | 24/24 |
| Exact execution status, value and full trace | 1512/1512 | 1512/1512 |

An execution success requires **all four public probes** for that program to
match, including complete traces. All 216 post-fit phases recovered 1704/1704
active programs in each arm. Including the initial reads gives 1728 active
program observations and 6912 actual public-probe executions per arm. The
parameter reader could not access `sources.payload`; exact SQL used the same
immutable source snapshot and interpreter. Stale, revoked and stopped owner
requests were checked for refusal before model forward or explicit value reads.

[AUDIT-skill-longrun.json](../../../evaluation/AUDIT-skill-longrun.json) reports
**28467 checks passed**, no failed check, and `quality_all_correct=true`.
Its bounded detail parts retain every comparison and phase record. Check
counts and repeated workflow observations are not independent statistical
trials. Exact SQL achieved the same quality, so this study does not demonstrate
a quality advantage for parameter storage.

## Observed costs and remaining unknowns

[COST_SUMMARY.json](COST_SUMMARY.json) binds the complete audit, raw cost
inventory, sampling coverage and [separate packaging receipt](PACKAGING.json).
The following CPU scopes are nested, except for the later packaging process:

| CPU scope | Seconds |
|---|---:|
| Fit children | 433.334382 |
| Reader children | 228.331255 |
| Fit and reader children combined | 661.665637 |
| Manager including waited descendants | 664.500067 |
| Monitor launcher including manager tree | 751.157676 |
| Entire wrapper including all waited children | 767.541729018 |
| Separate packaging | 18.2249502 |
| **Disjoint wrapper plus packaging** | **785.766679218** |

Only the last two disjoint scopes are added. Adding worker, manager or monitor
CPU again would double-count work already inside the wrapper. Checkout, Python
setup, upload, acquisition and local audit costs are outside this sum. The
wrapper wall was 687.657296069 seconds; its maintenance observation window was
669.297076051 seconds. Preparation, child-process and packaging timings are
preserved separately.

Resource sampling recorded 2913 samples and 46 process-exit-related errors.
RSS/PSS has **20.962605019 seconds unknown**, with approximately 96.867967%
coverage. Storage has **0.009797947 seconds unknown**, with approximately
99.998536% coverage. Observed RSS/PSS peaks were **690384896 / 521078784 B**;
these are sampled peaks, not exact continuous maxima. Logical and allocated
storage peaks were 64489266 and 74301440 B. `full_cost_exact=false` remains.

Median timing slices were:

| Slice | Median |
|---|---:|
| Parameter loop over eight workflows | 1.010242 ms |
| Exact-SQL loop over eight workflows | 0.123206 ms |
| Checkpoint load | 2.649081 ms |
| Entire fresh-reader process | 1.021130909 s |

Both arms share each fresh process and run in parameter-then-SQL order. Loop
timings exclude common startup and loading; a fresh process does not imply an
empty filesystem cache. These are not isolated service latencies. The runner
used an AMD EPYC 9V45 with 4 logical CPUs, Python 3.12.15, CPU Torch 2.8.0 and
NumPy 2.3.5. The semantic clean run used different hardware, so cross-run timing
differences do not establish an algorithmic speedup.

The 216 newly fitted checkpoints occupy 13105634 B. All 222 retained checkpoint
directories, including original and untrained initializations, occupy
13413236 B. The three final current checkpoints occupy 163998 B in total.
Raw int64 training schedules occupy another 33177600 B. Source SQLite,
versioned source JSON, canonical features and the 127536988 B shared encoder
reference are accounted separately. The encoder was not reexecuted or copied
into this maintenance run. Historical artifacts remain for audit; revocation
and clean rebuilding do not erase historical archives.

## Audit serialization failure and retained repair

The first audit invocation completed its comparisons and wrote 57 partial
check files, but its reused semantic report writer put all 216 rich phase
records into one batch exceeding 400000 bytes. It exited 1 without emitting a
complete summary. Its complete original output, process receipt and source
identities are retained in
[skill-audit-serialization-failure](../../../evaluation/skill-audit-serialization-failure/README.md).
It remains a failed audit invocation.

The repair added a skill-specific serializer that checks encoded byte sizes
and splits oversized batches without dropping or changing records. The main
auditor changed only its report-writer import. The legacy semantic writer,
all audit comparisons, thresholds, runtime source files, model parameters,
protocol and original evidence were unchanged. Two invented-data writer
regressions passed. A second invocation wrote to a new directory and emitted
the complete passing audit. All 57 earlier check files are byte-identical to
their counterparts in that completed invocation. No fit was rerun.

[skill-audit-formal-process](../../../evaluation/skill-audit-formal-process/README.md)
retains the second invocation's exact source identities, stdout, stderr and
process receipt, including the disclosed post-formal serialization repair.
The auditor imports no Torch model, trainer, owner or runtime interpreter. It
uses independent NumPy float32 arithmetic over saved tensors and an independent
integer interpreter; that arithmetic replay is explicitly disclosed.

## Interpretation

This experiment establishes finite-horizon maintenance for eight known
canonical skill addresses under full current-source replay. It does not
establish open-world skill acquisition, general program synthesis, growth in
memory capacity, emergent topology, native Agentd execution of the residual
model, physical erasure or a full lifecycle cost advantage. The native Hepta V9
execution route remains separate evidence. The unchanged semantic experiments
and their previously measured costs also remain separate records.
