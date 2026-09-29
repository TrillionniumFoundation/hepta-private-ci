# Neuron V2 operations and generation handoff runbook

This runbook is the operational companion to `V2_CONTROL_PLANE.md` and
`V2_DEVELOPMENT.md`. It describes implemented inspection and recovery interfaces
plus the safe procedure for a capacity-driven generation handoff. It does not
grant release, activation, rollback or model-selection authority.

## Fixed identities

Every investigation records all of the following before changing process state:

- exact source commit and integration-base commit;
- runtime configuration digest and body-bundle digest;
- controller lifecycle state, execution epoch and active/retained generations;
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
| `reserved_not_executed` | A reservation exists without a dispatch fence. | In `Serving`, preserve it for the same live-admitted operation. In `Quiescing`, close it through controller recovery before seal. |
| `outcome_unknown` | Physical execution may have crossed the dispatch boundary. | Query the durable provider ledger. Do not blindly execute again. |
| `failed` | A durable terminal negative transition exists. | Return the recorded failure. Do not reuse the tick ID with changed input. |
| `committed_witness_pending` | The local result is durable but external witness acknowledgement is incomplete. | Reconcile witness CAS and the local acknowledgement before handoff. |
| `committed_witnessed` | The exact local result and witness acknowledgement are durable. | Apply the current authorization policy before exposing the result. |

`NeuronOperationStatusV2::action_code()` and
`AgentdNeuronRecoveryReportV2::action_code` expose the same low-cardinality
operator actions: `admit_original_request`, `resume_or_close_unexecuted`,
`reconcile_provider`, `return_terminal_failure`, `reconcile_witness` and
`check_current_use`. These are advice, not capabilities; hosts must still use the
separate new-work, exact-recovery, truth-query and current-use boundaries.

`NeuronRuntimeV2Error::stable_code()` is a low-cardinality diagnostic family.
`store_outcome_unknown`, `index_outcome_unknown`, `witness_outcome_unknown` and
`model_outcome_unknown` require operation-key reconciliation. They are not
negative results and do not authorize a fresh operation ID.

A stale invocation prepared before quiesce returns admission `Revoked`. Confirm
that `stale_invocation_rejections` increased and do not reconstruct an execution
path around the lifecycle controller.

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

1. Query the exact affected operation before attempting recovery.
2. Run local reconciliation. This may finish an already durable store commit,
   complete the discovery index and acknowledge an already observed witness.
3. While the controller remains `Serving`, call ordinary recovery. It may query
   the same durable provider operation, but it preserves a reservation or an
   authoritative provider `NotStarted` result. It never calls provider `execute`.
4. If the preserved operation should continue, invoke the same operation through
   `tick_guarded` with current admission. Do not change its key or input.
5. To retire the generation, call `begin_quiesce` first. This closes new work and
   advances the execution epoch, invalidating all previously prepared invocations.
6. In `Quiescing`, controller recovery may close a proven-unexecuted reservation
   as terminal `AdmissionDenied`. Unknown provider outcomes remain pending and
   must be resolved; they cannot be force-closed.
7. Query the operation again. A read, corruption or poisoning error remains an
   error; never convert it to `not_recorded`.
8. Retain the resulting status, action code, source identity, file identities,
   capacity, execution epoch and provider evidence with the incident record.

A process restart is not a retry policy. Reopen the exact generation-store,
index, witness and provider histories, reconstruct the active and retained handle
topology, then follow the same decision table.

## Safe generation handoff

The current implementation deliberately uses explicit generation backpressure
instead of deleting or compacting authoritative V2 operation history. Until a
versioned unified V2 segment manifest is implemented and qualified, use this
procedure:

1. Call `begin_quiesce`. Confirm the controller snapshot reports `Quiescing` and
   `accepting_new_work == false`. Do not rely on callers voluntarily discarding
   old invocations; epoch validation rejects them at actual execution entry.
2. Resolve every reserved/dispatched provider operation through controller
   recovery. No `outcome_unknown` operation may cross the handoff boundary.
3. Call `seal`. `controller_busy` means an invocation admitted by the previous
   epoch is still in flight. Keep admission closed and retry after it drains;
   never mark the generation sealed manually.
4. Confirm there is no pending operation and no pending witness acknowledgement.
   Record the final checkpoint anchor, configuration/body digests, capacity
   snapshot, source commit and independently retained witness frontier.
5. Seal the old generation paths read-only and retain the provider execution
   ledger. Produce an authenticated archive digest; do not rename files into a
   new generation or reinterpret their headers.
6. Construct a strictly newer generation on distinct, empty paths with its own
   authenticated model, calibration, OOD and body identities. Never reset the
   generation number to regain capacity.
7. Call `reload`. The controller closes and drains the successor before replay
   validation. A failed reload leaves the predecessor sealed and active; it does
   not reopen old work.
8. Execute the exact-source source-head and synthetic-merge qualification, then
   target-host canary checks. Promotion remains a separate authority decision.
9. Route new requests only after the successor snapshot reports `Serving` and
   `accepting_new_work == true`. Historical operation queries continue against
   the retained generation that owns the key; retained handle clones remain
   non-writable.

Rollback is a pointer reversal only before the successor has accepted any
operation and while the predecessor remains quiescent and fully retained. Once
the successor has reserved, dispatched, failed or committed an operation,
returning to the predecessor is a new migration requiring explicit evidence; it
must not be represented as a transparent rollback.

## Control-state and filesystem incidents

Controller construction now preserves the direct control-state code instead of
collapsing every state-file problem into `controller_poisoned`:

| Stable code | Required response |
| --- | --- |
| `control_state_invalid` | Verify immediate parent/file type, Unix owner-only parent and file permissions, link count, parent identity and opened-file identity. Do not replace the state from an untrusted path. |
| `control_state_corrupt` | Retain the exact bytes, verify the canonical digest and reconstruct only from matching durable generation histories. |
| `control_state_io` | Restore the host-owned namespace or storage dependency; do not fabricate an empty topology. |
| `controller_poisoned` | Reconstruct the in-process controller and execution fence from durable state. Do not interpret this as an operation retry. |

| Observation | Required response |
| --- | --- |
| Immediate parent is a symlink, non-directory or Unix-shared namespace | Fail closed before fencing handles; provision an authenticated owner-private directory. |
| Symlink, reparse point, FIFO or non-regular state path | Fail closed; restore from an authenticated retained copy. |
| Parent or file inode/device identity changed during a read/publication | Stop writes and investigate host ownership; do not reopen a replacement as the same history. |
| Link count is not one | Fail closed because another writable name can mutate the owned file. |
| Unix group/other permission bits are present | Fail closed and restore the parent and file under the private owner-only contract. |
| Partial final frame | Reopen through the qualified recovery path; only a verified incomplete tail may be truncated. |
| Complete checksum/frontier mismatch | Treat as corruption, retain evidence and do not truncate through it. |
| Sync result indeterminate or store poisoned | Query after reopening; never write a negative tombstone from absence that is not proven. |
| Owner or controller poisoned | Stop serving, reconstruct from durable handles and histories, and resume only after reconciliation. |

The immediate control-state parent is an owner-private host namespace and is
identity-checked across reads and publications on Unix. An equally privileged
actor replacing a higher ancestor or mutating the namespace through host-level
mount operations remains outside this local file contract and belongs in the
host threat model.

## Measurement and evidence

The diagnostic lane records complete guarded-call p50/p95/p99, recovery time,
receipt encoding and full-receipt materialization, store/index/witness sync time,
request time minus measured sync calls, individual store/index growth and process
high-water RSS where the platform exposes it. These are process observations from
a deterministic fixture, not block-device write accounting, production-model
quality evidence or a production SLA.

Operational snapshots additionally expose the oldest current `OutcomeUnknown`
lower-bound age, witness backlog age, capacity trends, stale invocation counts,
owner busy/poisoned counts and preserving-versus-closing recovery counts.
`pending_operation_action_code()`, `capacity_action_code()` and controller
`lifecycle_action_code()` project those facts into low-cardinality operator
advice. Age values reset on owner reconstruction; durable records remain
authoritative.

The only acceptable candidate evidence comes from the committed-source workflow
for the exact source commit and fixed main integration base. Required commands
must actually execute: compile, related regression suites, strict Clippy, format
check, diagnostic parser/tests and the selected diagnostic sample. `skipped`,
`action_required`, queued, cancelled or historical results are not pass receipts.
