# Neuron V2 operations and generation handoff runbook

This runbook is the operational companion to `V2_DEVELOPMENT.md`. It describes
implemented inspection and recovery interfaces plus the safe procedure for a
capacity-driven generation handoff. It does not grant release, activation,
rollback or model-selection authority.

## Fixed identities

Every investigation records all of the following before changing process state:

- exact source commit and integration-base commit;
- runtime configuration digest and body-bundle digest;
- generation, subject scope and objective scope;
- generation-store, runtime-index and witness paths;
- current checkpoint anchor and the exact operation key `(tick_id, input digest)`;
- provider execution-ledger identity and the current capacity snapshot.

Never infer an operation state from a log line or a returned error alone. Query
the exact input with `query_input_operation`, or use `query_operation` when the
canonical input digest is already retained.

## Operation-state decision table

| Stable code | Meaning | Required action |
| --- | --- | --- |
| `not_recorded` | Healthy local histories contain no record for the exact key. | Re-run admission only when the caller still owns the original request and authorization. |
| `reserved_not_executed` | A reservation exists without a dispatch fence. | Reconcile the same operation under the exclusive durable owner; never change the key. |
| `outcome_unknown` | Physical execution may have crossed the dispatch boundary. | Query the durable provider ledger. Do not blindly execute again. |
| `failed` | A durable terminal negative transition exists. | Return the recorded failure. Do not reuse the tick ID with changed input. |
| `committed_witness_pending` | The local result is durable but external witness acknowledgement is incomplete. | Reconcile witness CAS and the local acknowledgement before handoff. |
| `committed_witnessed` | The exact local result and witness acknowledgement are durable. | Apply the current authorization policy before exposing the result. |

`NeuronRuntimeV2Error::stable_code()` is a low-cardinality diagnostic family.
`store_outcome_unknown`, `index_outcome_unknown`, `witness_outcome_unknown` and
`model_outcome_unknown` require operation-key reconciliation. They are not
negative results and do not authorize a fresh operation ID.

## Capacity decision table

Read `capacity_snapshot()` before admitting maintenance work. The snapshot counts
retained operations, physical file bytes, already-reserved completion bytes and
optional witness capacity. `action_code()` has three advisory values:

| Action code | Meaning | Host action |
| --- | --- | --- |
| `serve` | Generation, index and witness have ordinary headroom. | Continue normal admission; retain ordinary monitoring. |
| `schedule_generation_handoff` | A record or byte budget reached the 80% warning watermark. | Freeze a handoff window, create and verify the successor configuration and archive plan. |
| `backpressure` | A record/byte budget is exhausted or witness capacity is zero. | Reject new operations. Continue query and reconciliation only. Never delete history to regain space. |

Payload-specific admission remains authoritative and can reject before the
advisory watermark. Alert on the individual generation-store, index and witness
headroom instead of only the aggregate action code.

## Recovery procedure

1. Stop new admission at the owning host; retain the process and all file handles.
2. Query the exact affected operation before attempting a retry.
3. Run local reconciliation. This may finish an already durable store commit,
   complete the discovery index and acknowledge an already observed witness.
4. For `reserved_not_executed` or `outcome_unknown`, query the same durable
   provider owner. Only its current authoritative `NotStarted` result permits
   resuming the same operation.
5. Query the operation again. A read, corruption or poisoning error remains an
   error; never convert it to `not_recorded`.
6. Retain the resulting status, source identity, file identities, capacity and
   provider evidence with the incident record.

A process restart is not a retry policy. Reopen the exact generation-store,
index, witness and provider histories, then follow the same decision table.

## Safe generation handoff

The current implementation deliberately uses explicit generation backpressure
instead of deleting or compacting authoritative V2 operation history. Until a
versioned unified V2 segment manifest is implemented and qualified, use this
procedure:

1. Enter maintenance mode and reject new operations for the current generation.
2. Reconcile the runtime until there is no pending local witness work. Resolve
   every reserved/dispatched provider operation; no `outcome_unknown` operation
   may cross the handoff boundary.
3. Record the final checkpoint anchor, configuration/body digests, capacity
   snapshot, source commit and independently retained witness frontier.
4. Seal the old generation paths read-only and retain the provider execution
   ledger. Produce an authenticated archive digest; do not rename files into a
   new generation or reinterpret their headers.
5. Bootstrap a strictly newer generation on distinct, empty paths with its own
   authenticated model, calibration, OOD and body identities. Never reset the
   generation number to regain capacity.
6. Execute the exact-source source-head and synthetic-merge qualification, then
   target-host canary checks. Promotion remains a separate authority decision.
7. Route new requests only after the successor owner is installed. Historical
   operation queries continue against the retained generation that owns the key.

Rollback is a pointer reversal only before the successor has accepted any
operation and while the predecessor remains quiescent and fully retained. Once
the successor has reserved, dispatched, failed or committed an operation,
returning to the predecessor is a new migration requiring explicit evidence; it
must not be represented as a transparent rollback.

## Filesystem incidents

| Observation | Required response |
| --- | --- |
| Symlink, reparse point, FIFO or non-regular path | Fail closed; restore from an authenticated retained copy. |
| Inode/device identity changed after open | Stop writes and investigate host ownership; do not reopen a replacement as the same history. |
| Link count is not one | Fail closed because another writable name can mutate the owned file. |
| Partial final frame | Reopen through the qualified recovery path; only a verified incomplete tail may be truncated. |
| Complete checksum/frontier mismatch | Treat as corruption, retain evidence and do not truncate through it. |
| Sync result indeterminate or store poisoned | Query after reopening; never write a negative tombstone from absence that is not proven. |

Parent directories are trusted host-owned namespaces in the current contract.
An equally privileged actor replacing ancestor directories is outside this local
file-lock guarantee and belongs in the host threat model.

## Measurement and evidence

The diagnostic lane records complete guarded-call p50/p95/p99, recovery time,
store/index/witness sync time, request time minus measured sync calls, individual
store/index growth and process high-water RSS where the platform exposes it.
These are process observations from a deterministic fixture, not block-device
write accounting, production-model quality evidence or a production SLA.

The only acceptable candidate evidence comes from the committed-source workflow
for the exact source commit and fixed main integration base. Required commands
must actually execute: compile, related regression suites, strict Clippy, format
check, diagnostic parser/tests and the selected diagnostic sample. `skipped`,
`action_required`, queued, cancelled or historical results are not pass receipts.
