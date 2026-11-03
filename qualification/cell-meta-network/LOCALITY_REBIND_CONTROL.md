# Independent warm control after the original workers terminated

The original main and x230 Runtime jobs reached `timed_out` with exit code 124.
Their lifecycle receipts also contain `state: terminal`, `complete: true`,
`child_reaped: true`, and final `wait4_usage`. The original A/B result remains
valid for its original one-local-worker versus two-distributed-worker question.
Its ready ports must not be reused as evidence of a continuing process.

`locality_parallel_rebind_control.py` starts no workers. It binds a new, fixed
warm experiment to three externally launched Runtime workers, after validating
the original terminal evidence. It reuses the exact binary, model, source
manifests, source content, and already completed central transfer. It neither
transfers nor extracts source data and performs no effect or automatic retry.

This is an independent experiment, not a standalone Python file. It imports the
unchanged `locality_parallel_control.py` for its fixed schedule and concurrent
trial implementation, plus `network_followup.py` and `network_study.py` for the
existing bound RPC client. Deploy those supporting files before this helper.
Importing the v1 control does not run its experiment or reuse its stale workers;
only the v2 command below is executed. The regression command also expects the
v1 test module to be present.

| Slot | Host | Source task | Lifecycle |
|---|---|---|---|
| 0 | main | Original main shard | New job, original main instance may remain, generation greater than 1 |
| 1 | x230 via `x230-ts` | Original x230 shard at its original frozen source root | New job, original x230 instance may remain, generation greater than 1 |
| 2 | main | Original x230 shard in the already populated central root | New job and distinct active instance/socket |

Both arms use two concurrent requests: slots 0+2 locally and slots 0+1 across
hosts. The fixed ABBA/BAAB sequence runs twice, giving eight trials per arm and
eight counterbalanced adjacent pairs. Each new worker receives one actual audit
as a separately recorded warmup. OS page-cache state is uncontrolled. Worker
count is matched; hardware, CPU affinity and host background contention are not
claimed identical. All three workers remain resident during the warm control.

## Immutable original evidence

Retain the old `DEPLOYMENTS.json`, `RESULT.json`, and `CENTRAL_TRANSFER.json`
unchanged. The latter is already embedded in the old result and is verified by
exact JSON value; the old deployment bytes are verified against the result's
recorded SHA256. The existing central source root must be populated, its path
must equal the original deployment path, and the x230 manifest bytes must match
the original digest. Successful new source summaries must match the original
two summaries in every warmup and trial.

The actual original worker executable SHA256 on both nodes was:

```text
2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8
```

The exact unchanged model artifact SHA256 is:

```text
35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e
```

The two old external Runtime terminal receipts are raw JSON with `/job_id` and
`/state` pointers. Their IDs are `1a18bcc7d96-96a-466b` on main and
`1a18bcc7384-96a-4668` on x230. Old lifecycle receipts are the unmodified
`main-worker-lifecycle-v1.json` and `x230-worker-lifecycle-v1.json`. Copy any
remote proof to a new main proof directory byte for byte; retain the copy cost.
Do not edit a receipt to supply a later-known job ID or resource value.

## Launch three new workers through the original Runtime owner

Submit each launch once with a new Runtime operation key. Use the already
deployed executable, model, lifecycle helper and source configurations; do not
rebuild or recopy them to manufacture a fresh setup boundary. Retain external
start receipts and actual job IDs. The following are argv templates, not shell
commands to execute in addition to the Runtime calls:

```text
/usr/bin/python3 -I -S /tmp/hepta-cell-locality-20261030/worker_lifecycle.py --receipt /tmp/hepta-cell-locality-20261030/main-worker-lifecycle-v2.json --worker-sha256 2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8 -- /tmp/hepta-cell-locality-20261030/native-worker /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-main-20261030 2 0 /tmp/hepta-cell-locality-20261030/main-shards.json
/usr/bin/python3 -I -S /tmp/hepta-cell-locality-20261030/worker_lifecycle.py --receipt /tmp/hepta-cell-locality-20261030/x230-worker-lifecycle-v2.json --worker-sha256 2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8 -- /tmp/hepta-cell-locality-20261030/native-worker /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-x230-20261030 2 0 /tmp/hepta-cell-locality-20261030/x230-shards.json
/usr/bin/python3 -I -S /tmp/hepta-cell-locality-20261030/worker_lifecycle.py --receipt /tmp/hepta-cell-locality-20261030/main-second-worker-lifecycle-v1.json --worker-sha256 2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8 -- /tmp/hepta-cell-locality-20261030/native-worker /tmp/hepta-cell-locality-20261030/model.json 35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e cell-locality-main-second-20261030 1 0 /tmp/hepta-cell-locality-20261030/main-shards.json
```

The second argv runs on x230; the other two run on main. The second main worker
may reuse the unchanged main shard configuration, but receives only the x230
manifest audit in this control. Port 0 requests an actual available loopback
port; extract the returned address instead of guessing it.

As soon as each lifecycle receipt is in `ready` state, capture its exact bytes
into a **new immutable ready snapshot**. The live receipt will later change to
terminal and cannot itself be a frozen input. Copy the x230 ready snapshot to
main byte for byte. Keep the final lifecycle file separately after the run.
New setup records include all three new worker starts, proof/configuration
preparation and any proof transfer, as observed. Missing CPU or outer startup
values remain unknown, never zero.

## Rebinding configuration

Every `evidence` descriptor specifies an absolute path and SHA256 of actual
bytes. An optional `document_pointer` selects a value inside a provider envelope;
`decode_json_string: true` parses that selected string as JSON. Do not normalize
or rewrite provider evidence merely to fit the validator. Raw terminal receipts
shown above require neither option.

This compact generator illustrates the exact configuration shape. Run it only
after the named old and new proof files exist. `start-job-pointer` below must
match the actual start receipt schema; `/job_id` is appropriate only if the raw
start JSON really contains that field at its root. For an MCP text envelope,
put `document_pointer: /content/0/text` and `decode_json_string: true` in the
descriptor, then retain `job_pointer: /job_id` for the decoded document.

```python
import hashlib, json
from pathlib import Path

proof = Path("ABSOLUTE_IMMUTABLE_PROOF_DIRECTORY")
old_deployment = json.loads(Path("ORIGINAL_DEPLOYMENTS.json").read_bytes())
def evidence(name):
    path = proof / name
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
def read(name):
    return json.loads((proof / name).read_bytes())

binding = {
    "schema": "hepta.source-shard-worker-rebindings.v1",
    "worker_sha256": "2d11c2263a020f8244737aa6c0f7088316fdc2d78bce98f699ff9b4b2083baf8",
    "central_root": old_deployment["central_transfer"]["local_root"],
    "old_workers": [], "fresh_workers": [],
}
for name in ("main", "x230"):
    terminal = evidence(name + "-terminal.json")
    terminal.update(job_pointer="/job_id", state_pointer="/state", terminal_state="timed_out")
    binding["old_workers"].append({"runtime_terminal": terminal,
        "lifecycle_snapshot": evidence(name + "-old-lifecycle.json")})
for name in ("main", "x230", "main-second"):
    start = evidence(name + "-new-start.json")
    start["job_pointer"] = "/job_id"
    ready_evidence = evidence(name + "-new-ready-snapshot.json")
    ready = read(name + "-new-ready-snapshot.json")["ready"]["json"]
    node = {key: ready[key] for key in ("address", "instance", "generation", "artifact_sha256")}
    node.update(name=name, runtime_job_id=read(name + "-new-start.json")["job_id"])
    if name == "x230":
        node["ssh_target"] = "x230-ts"
    binding["fresh_workers"].append({"node": node, "runtime_start": start,
        "lifecycle_ready_snapshot": ready_evidence,
        "setup_receipts": [
            {"stage": "new-runtime-start", "evidence": start},
            {"stage": "new-worker-ready", "evidence": ready_evidence},
            # Append actual preparation/outer startup/proof-copy receipts here.
        ]})
with Path("NEW_REBINDINGS.json").open("x") as stream:
    json.dump(binding, stream, sort_keys=True, indent=2)
    stream.write("\n")
```

The helper validates every referenced setup receipt and adds its raw hash to
the frozen input set. A nonempty receipt list is required for each new worker;
it does not infer unmeasured deployment CPU from a job ID. The inherited
`HEPTA_RUNTIME_JOB_ID` observation is checked for consistency when present, but
never substitutes for the independently pinned external Runtime receipt.

## Execute once and retain both old and new cost windows

```text
python3 /tmp/hepta-cell-convergence-20261030/qualification/cell-meta-network/locality_parallel_rebind_control.py --prior-deployments ORIGINAL_DEPLOYMENTS.json --prior-result ORIGINAL_RUN/RESULT.json --prior-transfer ORIGINAL_RUN/CENTRAL_TRANSFER.json --rebindings NEW_REBINDINGS.json --output NEW_PARALLEL_REBOUND_CONTROL_DIRECTORY
```

The output directory must not exist. The helper freezes proof/source hashes,
opens its own RPC/SSH connections, verifies the actual live binding gate with a
stale-generation rejection, warms each worker once, and performs its 16 fixed
trials. Before completion it rechecks all frozen evidence bytes. It closes only
its own SSH transport. All worker stops remain with the original Runtime owner.

Report the warm medians and paired distributed-minus-local deltas. Reference
the original central transfer once, without repeating it or charging it again
inside this warm window. Keep all original setup, 900-second worker lifecycles,
waiting/tool failures, and all three new worker starts/final lifecycles in the
overall evidence ledger. Do not allocate the same cumulative child CPU twice.
Do not add peak RSS maxima to claim a concurrent measured peak. Cold comparison
is null and `full_cost_exact` remains false: this helper cannot turn the warm
measurement into a complete deployment-cost comparison.

The original Runtime terminal and wrapper direct-child resource completion are
different facts. A `wait4` receipt proves the direct child was reaped and supplies
its final CPU/RSS; it does not prove arbitrary descendant cleanup or a particular
Runtime cgroup policy. Keep the original unit/cgroup evidence separately. New
ready snapshots have incomplete terminal resources until their original jobs
are stopped and reconciled; preserve those later receipts without editing any
frozen snapshot or the completed control result.

Six proof regressions plus the two existing concurrency/input regressions can
be run without a remote worker or model. They are not performance evidence:

```text
python3 -B -m unittest discover -s qualification/cell-meta-network -p 'test_locality_parallel*control.py' -v
```
