# P3: registered source-shard locality, with an honest local baseline

This continuation asks whether a useful native subtask benefits from executing
where its input already resides. It audits actual fixed source snapshots from
the existing Git objects on `main` and the already deployed source tree on
`x230`. The latter is not a Git repository: read-only Git probes returned 128,
and no fetch was attempted. Each selected source file is read
once per task, checked against its registered SHA256 and byte length, and counted
for newline bytes. The result is a small manifest/content summary. Duplicate
file contents are excluded when freezing the workload; no repeated eight-vector
loop, artificial delay, or redundant forward pass creates the workload.

This is a source-integrity task, not a neural learning benchmark. The original
native residual model remains available through the worker's existing `read`
operation, with unchanged instance/generation/artifact fencing. `audit_shard`
does not invoke that model. Its results therefore cannot establish improved
model quality, beneficial cell division, autonomous agents, or general
intelligence.

## Read-only registered work

The Runtime process owner launches and later terminates each isolated worker.
The worker still binds loopback, and the coordinator owns only its SSH
forwarders. A trusted startup configuration binds each manifest digest to one
local root. Requests may select registered manifest digests, not arbitrary
filesystem paths. The reader enforces bounded regular files, rejects relative
parent/absolute paths and source changes, and returns no partial successful
summary. The stale-generation probe must leave the file-work counter unchanged.
These experiment fences do not replace Agentd publication or effect authority.

`source_shard.py freeze` reads a specified immutable commit through `git cat-file`
and writes only a new snapshot directory. It does not edit, reset, stash, or
check out the source worktree. `GIT_NO_LAZY_FETCH=1` prevents a partial clone
from silently fetching missing input from elsewhere and being counted as
existing local data. The actual source commit, prefixes, excluded files, bytes,
manifest identity, and extraction cost are recorded.

`source_shard.py freeze-tree` handles an existing plain source tree. The actual
input for this run is
`/home/qian/hepta-runtime-optimization-20261029-r5/source-r5b` on `x230`.
It writes only a new snapshot, rejects symlinks in the selected source paths,
and bounds the inventory to 4,096 files, 4 MiB per file, and 64 MiB total.
Selected extensions are `.rs`, `.py`, `.toml`, `.md`, and `.lock`; build/cache
directories are excluded. Each opened source file must match its original
device/inode/mode/size/mtime/ctime fingerprint before and after reading, and
the complete selected inventory is compared again before publishing a manifest.
These checks detect ordinary concurrent source changes; they do not freeze
the source filesystem or turn its contents into an upstream commit.

Its v2 manifest explicitly sets `source_commit=null` and records a
`source_tree_sha256`: SHA256 of a domain tag plus each selected, deduplicated
file's UTF-8 path length/path, byte length, and content SHA256, in path order.
The worker requires exactly one origin identity: a valid commit or a matching
tree digest. A missing, forged, or simultaneous pair is rejected. The manifest
digest still identifies the entire requested workload. This tree identity
covers the registered source subset, not unselected files or upstream history.

The remote source snapshot must come from that node's pre-existing source.
Only the helper, compiled worker, and existing 62,792-byte residual model are
deployed from main; their setup/transfer costs remain explicit. If a source
snapshot is absent, the run fails instead of replacing it with duplicated main
data. The registered workload is a bounded source subset, not an assertion that
every repository file was audited.

## Arms and measurements

| Arm | Initial setup | Repeated task |
|---|---|---|
| Local only | Pack the actual remote snapshot, transfer its compressed bytes once, verify the archive identity, and extract into a new local root | Main audits both snapshots; the local copy is reused |
| Distributed | Deploy the remote worker and transport; keep the actual remote data on its source node | Main and x230 audit their own snapshots concurrently and return summaries |

The coordinator verifies identical per-shard output summaries across all trials.
There are two ABBA blocks: local, distributed, distributed, local. Workers and
connections persist through these paired measurements. OS page-cache state is
not controlled: these are warm-process measurements, and neither the second
trial nor a new worker is labelled a cold disk.

Worker cold-start/deployment receipts are separate from the task window.
Compression, upload/download, archive extraction, connection startup,
application bytes, native read/hash time, process CPU ticks, coordinator CPU,
SSH client CPU, and failure costs are retained where observed. Shared and
overlapping windows must not be added twice. The local arm does not repeatedly
download the same immutable snapshot just to make distribution look faster.

If all external setup windows are supplied, the result computes a conditional
repeat-count break-even using measured persistent-task medians. When the
distributed task is slower, there is no positive throughput saving to amortize
extra setup. When setup coverage is incomplete, the result leaves break-even
unknown rather than filling missing cost with zero.

`full_cost_exact=false` remains required: page-cache state, remote SSH server
CPU, source-copy SSH framing bytes, complete worker resident-byte integrals,
and hardware energy are not fully measured. Any positive result is specific
to these source shards, hardware, placement, cache state, and reuse contract.

## Execution

Build the standalone worker from `native-worker/Cargo.toml`. Its original CLI
accepts an optional final `SHARD_CONFIG` path:

```text
worker MODEL ARTIFACT_SHA256 INSTANCE GENERATION PORT [SHARD_CONFIG]
```

Use port 0 to let the OS select a loopback port and retain the ready receipt and
Runtime job ID. Supply those actual identities to `locality_study.py`; its
deployment file also contains the two manifest digests, actual remote archive
size/SHA256, and a new empty centralized-copy root. The SSH target is explicit
(the observed reachable alias in this run is `x230-ts`).

```text
python source_shard.py freeze --repo EXISTING_REPO --commit FIXED_SHA --output NEW_SNAPSHOT
python source_shard.py freeze-tree --source-root EXISTING_NODE_SOURCE --output NEW_SNAPSHOT
python source_shard.py pack --snapshot NEW_SNAPSHOT --output NEW_ARCHIVE.tar.gz
python locality_study.py --deployments ACTUAL_DEPLOYMENTS.json --output NEW_EVIDENCE
```

Python behavior tests verify fixed-commit extraction despite a dirty worktree,
plain-tree identity without a Git claim, content deduplication, snapshot
round-trip, source mutation/symlink rejection, and archive path confinement.
Native tests verify actual content reads, post-registration tampering, unknown
shard identities, invalid paths, and exactly one verified source identity.
Test definitions are not performance evidence;
retain the actual run receipts and failed attempts beside any result report.
