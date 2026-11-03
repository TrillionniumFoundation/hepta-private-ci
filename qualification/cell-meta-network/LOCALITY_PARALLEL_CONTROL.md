# Warm locality control with matched worker concurrency

The first source-shard comparison preserves its original meaning: one main
worker handled both shards serially, while main+x230 used two workers. That
confounds physical placement with worker concurrency. Do not rewrite its
results as evidence that physical distribution itself improved performance.

`locality_parallel_control.py` adds a separate, fixed warm control:

| Arm | First shard | Second shard | Concurrent worker requests |
|---|---|---|---:|
| parallel_local | Original main worker | Additional worker on main, reading the existing central copy | 2 |
| distributed | Original main worker | Original x230 worker, reading its original local snapshot | 2 |

Both arms use the same two-thread coordinator executor and one audit per
worker per task. All three workers and their RPC connections persist through
the control; only two workers perform source work in each measured trial. The
unused worker remains idle. This is not a measurement of complete deployment
RSS or an assertion of identical hardware, CPU affinity, or measured CPU quotas.

## Immutable inputs and fixed schedule

The helper validates the original deployment SHA against the old RESULT.json,
the exact old CENTRAL_TRANSFER.json, both original successful source summaries,
the exact remote manifest, and the already populated central root. It does not
upload, download, decompress, re-freeze, or otherwise rewrite either shard.
It does not use old performance measurements to select its schedule.

Before timing, each worker performs one actual audit to verify the original
summary and warm its request path. Those three audits are recorded separately.
Measured order is fixed at ABBA/BAAB twice: 16 trials, eight per arm, with eight
adjacent pairs split equally between local-first and distributed-first. The
helper has no repetition argument, adaptive stopping, retries or new effects.
OS page-cache state is not controlled; no cold-disk inference is valid.

Stale instance/generation/artifact binding remains the original worker's gate.
The helper probes stale generations and requires no audit counter increment,
then checks exactly one successful audit on each of the two active workers for
every trial. Every result must equal the original immutable source summary.

## Deployment and command

Finish the original A/B coordinator before connecting this helper. Retain the
original two workers, their actual Runtime job IDs, instances and generations.
Start one additional main worker through Runtime, using the same compiled
binary/model and a distinct instance, job and loopback port. Its configuration
only needs the original x230 manifest mapped to the existing filled
`central-x230` root. No original worker or source data is replaced.

Write a new additional-worker JSON from the actual ready/lifecycle receipts:

```json
{
  "node": {
    "name": "main-second",
    "address": "127.0.0.1:ACTUAL_NEW_PORT",
    "instance": "ACTUAL_NEW_INSTANCE",
    "generation": 1,
    "artifact_sha256": "35e0f96a2e7bf1a21a7e937ed009bbef9002c547781b8de12acbc5aae024e15e",
    "runtime_job_id": "ACTUAL_NEW_RUNTIME_JOB"
  },
  "source_root": "ABSOLUTE_EXISTING_CENTRAL_ROOT",
  "manifest_sha256": "SHA256_OF_EXACT_ORIGINAL_X230_MANIFEST_BYTES",
  "setup_receipts": [
    {"stage": "additional-main-worker", "runtime_job_id": "ACTUAL_NEW_RUNTIME_JOB", "ready_receipt": "ACTUAL_RECEIPT_PATH"}
  ]
}
```

Use actual values. Record measured additional worker startup costs and later
terminal resources in the receipt list or its immutable referenced files;
unobserved values remain explicit unknowns. The helper owns no worker lifecycle.

```text
python3 /tmp/hepta-cell-convergence-20261030/qualification/cell-meta-network/locality_parallel_control.py --prior-deployments ORIGINAL_DEPLOYMENTS.json --prior-result ORIGINAL_RUN/RESULT.json --prior-transfer ORIGINAL_RUN/CENTRAL_TRANSFER.json --additional-worker ACTUAL_ADDITIONAL_WORKER.json --output NEW_CONTROL_EVIDENCE_DIRECTORY
```

The new output directory must not exist. The helper freezes its source/input
hashes, retains every completed trial and any failure, and closes only its
owned SSH forwarding process. Retain Runtime terminal resource receipts for
all worker lifecycles after the entire experiment is complete.

## Cost interpretation

Report warm task medians and the eight paired distributed-minus-local deltas.
Task timings include the same coordinator executor creation in both arms.
Instrumentation timings separately include before/after stats RPCs. Application
bytes are reported separately for task-only and instrumented windows. Worker
counters, native read/hash time, coordinator CPU, owned SSH CPU, connection
startup and the three warmups remain observable evidence.

The original centralized transfer is referenced, never performed or charged
again. Additional main worker setup is a separate incremental receipt; its cold
startup is not concealed inside warm task savings. Existing worker terminal
usage may cover both the original experiment and this control, so do not charge
the same full lifecycle to each run independently. This helper leaves cold-cost
comparison null and `full_cost_exact=false`; any combined cold analysis needs
the full external receipts and a clear, nonduplicated accounting boundary.

Two unit regressions check actual simultaneous dispatch using a barrier and
verify that altered transfer identities, roots, or reused local sockets are
rejected. The fixture performs no artificial sleep and supplies no performance
evidence. Physical-node timings come only from the actual Runtime-owned workers.
