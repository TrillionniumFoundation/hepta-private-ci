# P3 deployment recipe and cost windows

This recipe uses the existing native worker and `locality_study.py`; it creates
no separate worker owner. Replace path labels with the actual isolated paths.
Both workers are launched and later stopped by the existing Runtime process
owner. Do not attach an extra persistent RPC client during the comparison.

## 1. Freeze and retain the actual inputs

The main Git snapshot has already been frozen. Reuse it, including its original
`manifest.json` bytes and `FREEZE.json`; do not re-run the extraction to obtain a
more favorable cost. The x230 input is an existing plain source directory:

```text
python3 source_shard.py freeze-tree --source-root /home/qian/hepta-runtime-optimization-20261029-r5/source-r5b --output /tmp/hepta-cell-locality-20261030/x230-tree-snapshot
python3 source_shard.py pack --snapshot /tmp/hepta-cell-locality-20261030/x230-tree-snapshot --output /tmp/hepta-cell-locality-20261030/x230-shard.tar.gz
```

Run these commands on x230. Retain the freeze receipt, archive receipt, helper
SHA256, actual Runtime job IDs and outer process resource receipts. The archive
receipt is `/tmp/hepta-cell-locality-20261030/x230-shard.tar.gz.receipt.json`.
Copy only the small manifest and receipts to main before worker registration;
the study itself performs and charges the actual archive transfer. Do not copy
the archive to main in advance. Preserve manifest bytes exactly, because their
SHA256 is the request identity. The main v1 and remote v2 schemas may coexist.

## 2. Register the source roots

Create a **new empty** directory on main, for example
`/tmp/hepta-cell-locality-20261030/central-x230`. It must exist before worker
startup, because `ShardStore::load` canonicalizes each registered root. It must
still be empty at study startup, because archive extraction refuses preexisting
contents. Loading a shard validates metadata; it does not require source files
to have arrived. An audit before the copy fails; an audit after the copy uses
the same worker and registered root without restarting it.

Main's shard configuration has two bindings:

```json
{
  "schema": "hepta.source-shard-deployment.v1",
  "shards": [
    {
      "manifest": "ABSOLUTE_MAIN_SNAPSHOT/manifest.json",
      "root": "ABSOLUTE_MAIN_SNAPSHOT/source"
    },
    {
      "manifest": "/tmp/hepta-cell-locality-20261030/x230-manifest.json",
      "root": "/tmp/hepta-cell-locality-20261030/central-x230"
    }
  ]
}
```

x230's configuration has one binding:

```json
{
  "schema": "hepta.source-shard-deployment.v1",
  "shards": [
    {
      "manifest": "/tmp/hepta-cell-locality-20261030/x230-tree-snapshot/manifest.json",
      "root": "/tmp/hepta-cell-locality-20261030/x230-tree-snapshot/source"
    }
  ]
}
```

The main-local copy of `x230-manifest.json` must be byte-identical to the x230
manifest. Do not reserialize it after calculating the digest. Use the *outer
manifest digest*, not `source_tree_sha256`, in `manifest_sha256` RPC fields.

## 3. Start the existing native worker on each host

Use the compiled `codex-hepta-cell-meta-worker` binary, the same model artifact,
a distinct instance name per host, generation 1, and port 0. These are worker
argv templates submitted through the existing Runtime process owner:

```text
WORKER /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-main-20261030 1 0 MAIN_SHARDS_CONFIG
WORKER /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-x230-20261030 1 0 X230_SHARDS_CONFIG
```

`model.json` is the exact UTF-8 `artifact_json` string extracted from
`codex-rs/hepta-neuron/tests/fixtures/residual-memory/seed-731-semantic.json`:
62,792 bytes, SHA256 equal to the argument above. The fixture wrapper itself
is not a model artifact. The worker binary, model and helper deployment bytes,
verification and elapsed times are setup costs, even though AuditShard does not
invoke the model. Neither input source shard is uploaded from main to x230.

Save each exact ready JSON line and the corresponding actual Runtime job ID.
The ready `address` is already `127.0.0.1:ACTUAL_PORT`; do not guess the port.
The worker's `startup_ns` covers its own model/config load and listener setup;
Runtime scheduling and process-launch delays belong to the outer startup
receipt. Record each host's `SC_CLK_TCK` separately to interpret process ticks.

## 4. Assemble the actual deployment JSON

Use two node entries in this exact order: main then x230. Main has no
`ssh_target`; x230 uses the existing reachable alias `x230-ts`. Below, uppercase
strings mean actual values extracted from files/ready receipts, not literals to
submit. The integer archive size must come from the actual pack receipt.

```json
{
  "nodes": [
    {
      "name": "main",
      "address": "127.0.0.1:ACTUAL_MAIN_PORT",
      "instance": "cell-locality-main-20261030",
      "generation": 1,
      "artifact_sha256": "35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e",
      "runtime_job_id": "ACTUAL_MAIN_WORKER_JOB"
    },
    {
      "name": "x230",
      "address": "127.0.0.1:ACTUAL_X230_PORT",
      "instance": "cell-locality-x230-20261030",
      "generation": 1,
      "artifact_sha256": "35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e",
      "runtime_job_id": "ACTUAL_X230_WORKER_JOB",
      "ssh_target": "x230-ts"
    }
  ],
  "manifest_sha256": ["SHA256_OF_EXACT_MAIN_MANIFEST_BYTES", "SHA256_OF_EXACT_X230_MANIFEST_BYTES"],
  "central_transfer": {
    "remote_archive": "/tmp/hepta-cell-locality-20261030/x230-shard.tar.gz",
    "archive_bytes": 1,
    "archive_sha256": "ACTUAL_ARCHIVE_SHA256",
    "local_root": "/tmp/hepta-cell-locality-20261030/central-x230",
    "manifest": "/tmp/hepta-cell-locality-20261030/x230-manifest.json"
  },
  "setup_receipts": [],
  "external_setup_wall_seconds": null
}
```

Replace the example `archive_bytes=1` with the actual integer and populate
`setup_receipts` from observed records. Leaving `external_setup_wall_seconds`
null is intentional if complete, nonoverlapping arm setup windows cannot be
established. Missing costs must not be represented as zero. The driver retains
the receipt list without interpreting or summing it. For each receipt record:

- `id`, `stage`, `host`, `arm` (`shared`, `local_only`, `distributed`, or
  `experiment_development`), actual `runtime_job_id`, and `exit_code`/terminal
  status;
- observed start/end timestamps, wall seconds, process/child CPU seconds with
  their accounting scope, and peak RSS where measured;
- transferred byte counts and payload SHA256 where applicable;
- `included_in` or an equivalent parent-window identifier when a smaller
  helper receipt is already included in an outer process measurement;
- an explicit null and reason for unobserved quantities.

At minimum retain these stages:

| Stage | Allocation | Exact evidence |
|---|---|---|
| Git probes, cancelled/failed build attempts, final build and tests | Experiment development; reported separately from deployment amortization | Original job IDs, terminal status, wall/CPU/cancellation receipts and output |
| Main snapshot freeze and x230 tree freeze | Shared input preparation | Both original FREEZE.json files plus outer job usage |
| Helper deployment and metadata/config exchange | Record actual allocation; shared portions appear in both counterfactual arms once | Payload bytes/hashes, transfer receipt and elapsed time |
| Main worker/model setup and cold process start | Shared | Binary/model hashes and sizes, ready JSON, Runtime process startup and later usage |
| x230 archive compression | Local-only | Actual .tar.gz.receipt.json plus outer process usage |
| Extra x230 binary/model deployment and worker cold start | Distributed | Transfer, payload verification, ready JSON and Runtime startup receipts |
| Remote archive download and local extraction | Driver measures local-only setup | CENTRAL_TRANSFER.json; do not add this again to external setup |
| Persistent RPC connection startup | Driver measures | connection_startup_seconds; do not add it again to external setup |
| Audits, stats and owned SSH teardown | Driver measures, with distinct task/instrumented windows | Trial files, RESULT.json and SSH counters |
| Worker shutdown and lifecycle resources | External actual lifecycle | Terminal Runtime receipts for the two exact owned jobs |

When supplying complete arm-level external setup totals, the accepted shape is
`{"local_only": L, "distributed": D}` with measured seconds. Include relevant
external input/deployment setup in each arm, counting shared setup once per
arm. Exclude the driver's archive transfer/extraction and its RPC connection
startup; the driver already adds their measured values. Sum sequential,
nonoverlapping stages only. For overlapping setup use the actual elapsed
critical path, not the sum of parallel wall times. Keep development failures
visible separately; do not silently merge them into a successful build time.

The comparison uses:

```text
local setup       = external local setup + central transfer/extraction
network setup     = external distributed setup + remote RPC startup
common main RPC startup cancels from the difference
```

The automatic positive amortization count is only populated if distributed
persistent tasks are faster. If they are slower but their setup is cheaper,
report the finite crossover from the two measured affine cost curves
separately; a null positive-amortization field does not mean all setup costs
are equal.

## 5. Run once, preserve outcomes, close the owned workers

```text
python3 /tmp/hepta-cell-convergence-20261030/qualification/cell-meta-network/locality_study.py --deployments ACTUAL_DEPLOYMENTS.json --output NEW_EVIDENCE_DIRECTORY
```

The output directory must not exist. The patched driver first transfers and
extracts the remote archive, then opens persistent RPC connections. This order
avoids the worker's 30-second idle socket timeout during a slower source copy.
It verifies stale-generation rejection, runs two ABBA blocks and checks equal
per-shard summaries. The root used for the central copy stays filled afterward;
a failed run is retained, and any authorized repeat needs a new empty root,
updated binding and fresh output directory rather than overwriting evidence.

After the driver closes only its owned SSH children, stop the two exact
Runtime worker jobs and retain their terminal resource receipts. Do not stop
unrelated host processes. No cold-disk claim is valid: OS page cache remains
uncontrolled. Do not edit executed source files before retaining their
FREEZE.json hashes and completed or failed run evidence.
