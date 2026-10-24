# Fixed six-head graph: native cold dispatch qualification

This is a separately registered serving-placement experiment. Its graph is
shared frozen projected features → six original warmup readouts → an equal-weight
mean in canonical head order. It uses all linear/gated heads for seeds 7, 17, 29
and all 480 rows. Selection was specified before retention outcomes; this code
does not read those outcomes, task labels or controlled-arm heads.

It tests numerical parity and measured costs of one fixed graph through the
existing native process owner. It does not test cell learning, splitting, learned
edges, optimizer migration, agent task competence or general intelligence.

## Frozen comparison

| Arm | Native workers | Placement | CPU ceiling / memory ceiling per worker |
|---|---|---|---|
| A | One worker, all six heads | main | 200% / 2 GiB |
| B | Two concurrent workers, fixed 3+3 shards | main + main | 100% / 1 GiB each |
| C | Two concurrent workers, same 3+3 shards | main + pocket4 | 100% / 1 GiB each |

Every worker uses one NumPy thread. Own CPU ceilings sum to 200%, and own memory ceilings sum to 2 GiB; actual used
CPU is measured and need not be equal. Shards are `[0,3,4]` and `[1,2,5]` in the
fixed seed-major/head-minor index order. In C, shard `block % 2` goes to pocket4;
the other goes to main. All six permutations of A/B/C define six sequential
blocks. There are 18 graphs and 30 primary workers; both nodes of B/C are submitted
with `Promise.all`, without a serial fallback.

The primary descriptive comparison is paired C−B owner critical-path time.
C−A answers the operational split-versus-monolithic question; B−A shows the
additional-process/sharding cost. The machines and possibly their numerical
environments differ. The result concerns these actual deployment stacks; it
cannot isolate physical network latency or a pure hardware-location effect.

Fresh Python processes and full portable inputs are required for every primary
worker. Existing OS and service caches are not flushed. The first block is kept,
not discarded as warmup. No persistent process, daemon, new port, SSH channel,
artificially amplified kernel or extra model is introduced.

## Explicit admission stages

1. Review and commit the protocol, worker, exporter, reducer, reporter and owner
   adapter template before graph inference. Preserve their exact source hashes.
2. Stage only the standalone `cell_graph_worker.py` on main and pocket4 under
   experiment-owned paths. Record staging bytes, API calls and wall/CPU costs
   that are actually available. Run it with `--inventory`: this imports NumPy and
   records metadata, but performs no inference or model/checkpoint read.
3. Freeze both exact environment inventories and separate prior evidence of two
   physical hosts. A hostname hash alone is not physical-machine proof. The
   environment freeze includes executable, Python, NumPy, BLAS configuration,
   worker source hash and the original native process owner. Do not modify an
   existing environment to obtain a preferred timing result.
4. Export only the six initial `CellTrainingState` checkpoints and fixed common
   `projected_features.npz`. The exporter verifies complete saved state integrity
   and transfers only the readout parameters needed for serving. Optimizer state
   is preserved by the original study, but is not part of this inference payload.
5. Freeze the graph-content hash, environment-content hash and generated 30-request
   dispatch census. Bind the actual native API adapter, worker paths, reducer
   location/environment and start arguments before execution.
6. Execute the fixed blocks, then the three separately recorded idempotency
   lookups. Produce a complete-census report, including failures and missing costs.

The protocol freezes policy and selection rules first; input hashes are obtained
by deterministic export and frozen before the benchmark. There is no post-output
choice of head, row, backend, tolerance, block or graph topology.

## Commands and artifacts

The root executor supplies actual paths; no remote operations are performed by
these preparation commands themselves. From `qa/stem-bakeoff`:

```bash
python cell_graph_worker.py --inventory

python cell_graph_benchmark.py freeze-environments \
  --main MAIN_INVENTORY.json --pocket4 POCKET4_INVENTORY.json \
  --physical-attestation PHYSICAL_HOST_EVIDENCE.json \
  --protocol cell_graph_protocol.json --expected-protocol-sha256 PROTOCOL_SHA \
  --output NEW_ENVIRONMENT_FREEZE.json

python cell_graph_benchmark.py export --run ORIGINAL_RETENTION_RUN \
  --protocol cell_graph_protocol.json --expected-protocol-sha256 PROTOCOL_SHA \
  --output NEW_GRAPH_EXPORT_DIRECTORY

python cell_graph_benchmark.py prepare \
  --graph NEW_GRAPH_EXPORT_DIRECTORY/graph.json \
  --environments NEW_ENVIRONMENT_FREEZE.json \
  --protocol cell_graph_protocol.json --expected-protocol-sha256 PROTOCOL_SHA \
  --expected-graph-sha256 EXPORTED_GRAPH_SHA \
  --expected-environment-sha256 ENVIRONMENT_FREEZE_SHA \
  --output NEW_REQUEST_DIRECTORY
```

Every request contains exact little-endian float64 tensors encoded as base64,
their sizes/shapes/hashes, fixed head IDs and the frozen environment hash. This
preserves numeric bytes without decimal roundtrip ambiguity. Requests are below
the 1 MiB native stdin bound. The cold worker command is:

```bash
FROZEN_PYTHON ABSOLUTE_STAGED_WORKER.py \
  --expected-request-sha256 REQUEST_SHA
```

The original native process owner supplies the **exact request file bytes** as
stdin and applies the declared 10-second CPU, 45-second wall and CPU-quota limits.
There is no worker-side path in an input request and no arbitrary code execution.
The standalone worker creates no child processes. Its source and environment
identity are checked in every invocation.

Worker stdout consists of two JSON lines, together bounded by 196,608 bytes:
the first includes the full per-head probability tensors and measured phases;
the second hashes the first and reports actual first-line JSON serialization and
stdout-write costs. The tiny final trailer's own write and interpreter execution
before the first Python timestamp remain inside external owner wall time, but
are explicitly outside the internal phase counters. Full stdout must be paginated
without truncation; a single truncated read cannot qualify a graph.

The reducer receives a frozen dispatch ID plus one collection record and writes
`receipt.json` and, only on complete success, `predictions.npz`. It verifies every
worker identity, complete output trailer, original head indices and array digest.
It restores canonical indices before `np.stack(...).mean(axis=0)`, so partition
or return order cannot alter the reducer order.

```bash
python cell_graph_reduce.py --dispatch DISPATCH.json --graph-id b0-A \
  --owner-input COLLECTION.json --expected-dispatch-sha256 DISPATCH_SHA \
  --output NEW_GRAPH_EVIDENCE/reduction

python cell_graph_report.py --dispatch DISPATCH.json \
  --expected-dispatch-sha256 DISPATCH_SHA \
  --evidence ALL_GRAPH_EVIDENCE_ROOT --output NEW_REPORT.json
```

Evidence layout is `<root>/<graph_id>/{collection.json,owner.json,reduction/...}`;
recovery records are `<root>/recovery/b0-{A,B,C}-s0.json`. The root owner preserves
raw native API receipts and their hashes in addition to these normalized records.

## Native owner adapter contract

`cell_graph_owner.js` defines `executeCellGraph` and `recoverCellGraphNode`. It is
an orchestration template, not a new runtime client or transport. Root binds the
following operations to the already configured native process tools:

| Adapter method | Required behavior |
|---|---|
| `submit(request)` | Read/hash exact frozen stdin; call original process_start once with fixed executable/argv/cwd/resources/idempotency key; retain full actual start arguments and native receipt. Return job ID, start-argument hash, native-receipt hash and authoritative `start_disposition`. |
| `collect(request, submitted, instrument)` | Operate only on that job ID. Wrap every process_status/read in `instrument`. Retain exact stdout bytes, final exit status, actual quota receipt and any available process CPU/RSS. Paginate until authoritative completion; never silently truncate. |
| `reduce(collection, graph)` | Use one fixed reducer host/environment for every arm; include its real invocation, load, aggregation and output path in the outer owner interval. Return the exact reducer receipt hash and status. |
| `reconcile(request, job_id, instrument)` | Account for a failed newly created job under its original owner. Instrument status/terminate/kill calls in a separate six-call/30-second cleanup lane. Do not start a substitute or terminate an unrelated/unadmitted reused job. |
| `publish(...)` | Exclusively preserve collection, owner events and raw receipt provenance. No overwriting failed evidence. |
| `replayOriginalStart(request, original)` | Replay byte-identical original process_start arguments and idempotency key once after the primary census. Require an authoritative reused job with the original ID. |
| `publishRecovery(...)` | Preserve replay results and extra API/read/load costs separately. |

Actual tool names, schemas and job-receipt fields must be bound and reviewed by
the root operator. The template does not claim this binding is already complete.
The native receipt that proves own configured cgroup ceilings and whether the job was created
or reused must be retained. If those facts cannot be established, do not invent
them: the cold comparison is not qualified.

A successful primary collection contains:

- `request_id`, `host`, `request_sha256`, `idempotency_key`, `job_id`;
- `original_start_arguments_sha256`, `start_disposition="created"`, and
  `start_disposition_receipt_sha256`;
- authoritative `status="completed"`, `exit_code=0`, `stdout_complete=true`,
  `truncated=false`, `stderr_bytes`, `stdout_base64` and `stdout_sha256`;
- `authoritative_status_sha256`; the worker itself emits verified own cgroup
  ceiling strings and their digest. The reducer derives `own_cgroup_cpu_quota_percent`,
  `own_cgroup_memory_max_bytes` and `quota_receipt_sha256` from that validated output;
- optional actual `native_process_cpu_ns` / `native_process_peak_rss_bytes`.
  An unavailable value stays null, not zero.

Primary starts must be **newly created**. Receiving a cached job for a repeated
idempotency key is a failed cold observation; a fresh-key retry would hide that
failure and is not permitted. The planned recovery lookups instead require
`start_disposition="reused"`, the same job ID, exact original argument hash and
byte-identical full stdout. This detects recomputation even if predictions match.

## Time, memory and cost interpretation

The existing external graph owner measures its entire submit → complete
authoritative collection → reduction path in one invocation. B/C calls overlap
through `Promise.all`; node wall times are not added as critical-path latency.
The template uses one owner `Date.now` millisecond timeline. It rejects backward
movement; undetected forward adjustment remains a disclosed limitation. Remote
monotonic clocks are only used for within-process phases and are never subtracted
across hosts. If the root owner has a verified monotonic clock, adopting it needs
an explicit pre-run adapter freeze, not a post-result timing substitution.

Actual dispatch/read/status work carries the data. Logical stdin/stdout and API
payload sizes are distinct from TLS/compressed wire bytes, which this interface
does not expose. The measured enclosing path includes actual transfer and broker
delays; it does not identify a pure physical network latency.

Worker CPU is additive across independent processes, but internal phase counters
are subsets of each worker. Reducer CPU is separate. Fresh executable-entry counters include NumPy imports
and CLI setup; function-body counters are separately named subsets. Library calls
report fresh-process counters as null. Final receipt/CLI output remains outside
those CPU counters and inside the external owner wall path. Process RSS values are
individual high-water marks, including Python/NumPy; their sum is neither a
simultaneous peak nor unique physical memory. No worker spawns children, so its
self scope covers its computation process tree. It reads only `/proc/self/cgroup`
and its own `cpu.max`/`memory.max` under `/sys/fs/cgroup`, rejects path traversal,
and verifies fixed local caps before inference. These are own configured
ceilings, not effective capacity under unknown ancestors, affinity and host load. Existing service-daemon CPU/RSS and
external JavaScript-owner CPU/RSS may be unavailable and must remain explicitly
unmeasured. This experiment therefore cannot establish total-system net benefit
from a partial resource sum.

## Failure and recovery rules

Missing/invalid output, changed environment, reused primary job, unmet quota,
dispatch errors, timeout or a failed reducer stays in the 18-graph census.
Successfully completed siblings retain their measured work; unavailable failed
process costs remain unknown. The report cannot select only successful pairs.
There is no serial fallback, missing-head substitution, best block or alternative
functional reference after failure.

After the primary census, exactly `b0-A-s0`, `b0-B-s0`, `b0-C-s0` are looked up with
the original start arguments/idempotency keys. This tests completed-job identity
and output reuse, not a crash, SIGKILL, power loss or distributed optimizer-state
recovery. Its API/read/load costs are measured separately. Returned historical
worker CPU/RSS is not charged as new computation.

## Functional and statistical gates

The fixed functional reference is `b0-A`. Every per-head probability must agree
within `atol=1e-12, rtol=1e-12`, every per-head argmax and mean argmax must match,
and bitwise equality plus maximum error are reported. The tolerance is declared
before inference for cross-BLAS floating-point variation; it cannot be widened
after observing outputs. No label payload or task accuracy is involved.

All 18 graphs must pass the complete functional/cost-admission census before
qualified paired summaries. Report every raw value and paired difference, arm
median/min/max and failure. Six scheduled blocks do not support a reliable tail,
population generality or a claimed confidence interval. Any speed advantage
would be a result for this fixed serving workload and actual host/service stack.

## Local verification

From `qa/stem-bakeoff`:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -W error -m unittest test_cell_graph_benchmark -v
node test_cell_graph_owner.js
```

Tests use freshly constructed numerical/ownership fixtures only. They compare
all six readout calculations bitwise to original `NumpyCellHead`, exercise real
cold subprocess serialization, verify full-state source export, canonical shard
reassembly, unknown failure costs, complete-census blocking, concurrent submission
and exact original-job recovery. They are implementation checks, not benchmark
outcomes. An initial test exposed that `platform.platform()` can spawn `uname -p`;
the worker now uses the `os.uname()` syscall and verifies zero child CPU usage.

## Independent review corrections before any graph run

Review found that checking only before a final read could admit a call finishing
after the60-second bound. Primary and recovery paths now check after awaits too;
the completed native event and known costs remain in evidence. These checks
cannot interrupt an uninterruptible tool Promise. The native45-second process
limit is separate. Failed-job cleanup is explicitly instrumented in its own
six-call/30-second lane, within the enclosing owner wall interval.

Recovery requires an authoritative successful original, complete two-line
stdout/hash/probabilities/local-cap proof and nonempty identities. Missing fields
cannot qualify through None-equals-None, and recovery event lists must contain one
exact start plus only completed status/read calls with raw receipt hashes and
after-census intervals. A failed primary reference is never promoted.

The original reducer timer began after NumPy import. Revised receipts retain
body counters and add fresh executable-entry counters including import/CLI work,
with explicit remaining publication/pre-entry limits. No complete process CPU
benefit is inferred from a body timer.

Local tests exercise subprocess arithmetic/import/serialization with constructed
limits injected because this scratch lane cannot provision native systemd
cgroups. Separate parser/mismatch tests mock exactly three known self-kernel
files. They do not certify actual native quota enforcement. Independent root
main/pocket4 metadata probes verified100%/1GiB availability; each actual benchmark
worker must attest its own requested cap again before inference. The initial
platform.platform/uname child-process failure log is preserved.

The exact preflight environments are main Python3.13.12/NumPy2.2.6 and pocket4
Python3.14.4/NumPy2.3.5. Those differences are part of the observed deployment
stacks. The bound environment file additionally captures actual BLAS and kernel
metadata before any graph inference. A native process_start response exposes
reused=false for a new job and reused=true for an idempotent lookup; the adapter
normalizes these actual values into created/reused and retains the raw receipt.
