# context.compiler recovery and release runbook

This runbook governs the V3 provider-bound context path. It does not authorize a
release. Operators must attach receipts for one immutable source commit and its
deterministic merge tree before any state field is promoted.

## 1. Normal attempt sequence

1. Verify the externally signed context-authority snapshot.
2. Compile and serialize the exact selected context.
3. Build the final provider request and compute its exact-body digest.
4. Execute the immutable tokenizer bundle over those exact bytes.
5. Acquire the external attempt lease/idempotency grant.
6. Append `Prepared` and `LeaseAcquired` journal records.
7. Persist and fsync the durable provider intent/recovery archive.
8. Append `DurableIntentCommitted`.
9. Revalidate expiry, revocation frontier, lease, generation anchor, and body.
10. Cross the physical transport boundary using the same body object.
11. Append `TransportCommitted` when independently observed by the transport owner.
12. Reconcile an independently authenticated terminal attestation.
13. Append `TerminalObserved`, settle the lease, and append `LeaseSettled`.

No missing step is inferred from a later local callback.

## 2. Crash-point matrix

The qualification suite must inject a process stop immediately before and after:

- tokenizer process/object acquisition;
- tokenizer input write and result read;
- lease acquisition;
- durable intent file write;
- data-file fsync;
- rename;
- containing-directory fsync;
- transport commit;
- provider acknowledgement;
- terminal receipt persistence;
- lease settlement.

For every point, the test records whether transport is known not to have occurred,
may have occurred, or is independently confirmed. `may have occurred` remains
unresolved and blocks blind replay.

## 3. Restart protocol

On startup:

1. Verify directory ownership, mode, no-follow traversal, schema, checksums, and
   the external generation anchor.
2. Read the append-only journal and verify every previous-record digest.
3. Reject sequence, event, clock, body, attempt, or generation rollback.
4. Reconstruct each recoverable preparation/final-request binding from its
   canonical archive.
5. For an unresolved attempt, query the external lease and provider reconciler.
6. Accept a final state only with an exact-attempt/exact-body terminal attestation.
7. Never delete unresolved intent to restore availability.
8. Fence the writer and require reopen after uncertain durability or poisoned
   synchronization state.

Legacy digest-only pre-send records remain unresolved and require governed manual
reconciliation; they are never upgraded into authenticated evidence.

## 4. Filesystem and restore exercises

Before acceptance, execute all of the following against the selected host:

- replace the tokenizer executable path after custody acquisition;
- replace the vocabulary path after custody acquisition;
- insert symlinks at every store component;
- exchange a regular file for a directory, FIFO, device, or socket;
- change owner and permission bits;
- race rename/path substitution against open and persistence;
- restore an older valid state file;
- restore an older valid backup directory;
- restore state without the matching external generation anchor;
- truncate or reorder append-only journal records;
- replay a terminal for a different exact body or attempt.

All cases must fail closed without provider dispatch.

## 5. Multi-process and multi-host qualification

Run at least two independent Agentd processes and, for production topology, two
hosts against the same external lease authority. Submit identical and conflicting
attempt/idempotency keys concurrently. Acceptance requires:

- exactly one lease grant for identical semantics;
- a conflict for changed exact body or wire semantics;
- no process-local fallback after lease service failure;
- deterministic recovery after leader or host death;
- successful settlement or an explicitly unresolved state, never double send.

## 6. Real provider reconciliation E2E

The E2E harness must use a non-production provider tenant and bind:

- provider, endpoint, model, and request kind;
- exact encoded body digest;
- tokenizer custody/execution receipt;
- external lease grant;
- transport commit evidence;
- canonical provider receipt;
- independent terminal attestation;
- durable context-delivery receipt.

Tests must include delivered, rejected, not-dispatched, timeout/indeterminate,
connection reset after write, process death after write, and late final receipt.

## 7. Named-host performance and backlog profile

For each selected host image, retain p50/p95/p99 and maximum values for:

- cold and warm tokenizer execution;
- compile/serialize/final-body proof;
- lease acquisition and settlement;
- durable intent and terminal persistence;
- restart and unresolved-attempt reconciliation;
- peak RSS and allocation volume;
- concurrent admission and dispatch capacity;
- sustained unresolved backlog and drain rate.

The receipt binds host image digest, kernel, filesystem, CPU, memory, toolchain,
provider fixture, command lines, raw logs, and artifact digests. Results from an
unnamed GitHub-hosted runner do not qualify a production host.

## 8. Canary, activation, and rollback

Activation requires an operator-controlled protected environment and an external
approval receipt. The canary sequence is:

1. read-only dry run;
2. shadow final-body proof with transport denied;
3. limited non-production provider sends;
4. bounded production canary with explicit allowlist;
5. observation window and independent review;
6. gradual promotion.

Rollback disables new V3 admission but preserves journal, lease, and unresolved
attempt reconciliation. It must not switch unresolved V3 attempts to a legacy
path or delete V3 state. Schema rollback restores a compatible binary/state pair
and retains the external generation anchor.

## 9. Promotion rule

Only externally retained, exact-SHA receipts may change:

- `exactHeadExecution`;
- `independentAcceptance`;
- `activation`;
- `release`.

Generated source, unit tests, a successful materialization bundle, or a merged PR
cannot change those fields by itself.

## 10. Current lifecycle implementation (2026-09-29)

Sections 1-8 above are the full required production contract, not a declaration
that all external capabilities have been consumed by the current product owner.
The current consumer trace in `CURRENT_STATE.json` is authoritative about source
composition. In particular, authenticated App Server ingress and consumption of
`ContextSecurityCapabilitiesV3` by the physical-send owner remain open source
work. A local intent/byte verifier is not an independent provider attestation.

The lifecycle follow-up keeps `AgentdPromptPipelineOwner`,
`AgentdExactContextDeliveryOwner`, the runtime projection and the existing prompt
extension as the same execution chain. It adds no executor or authority store.

| State | Raw exact context | Persistent identity | Permitted next action |
|---|---|---|---|
| Validated but unpublished | Caller-owned only | None | Fail without publishing either usable stage. |
| Staged | Retained, at most 256 live turns | Runtime projection | Prepare or explicitly clear an unused turn. |
| Preparing | Retained under exclusive turn reservation | No claim inferred yet | Complete preparation; reject concurrent prepare/clear. |
| Durable pre-send | Retained while live | Exact preparation, request proof and recovery archive | Same-body send after final checks; never blind replay. |
| Indeterminate | Retained while live | Pre-send plus nonfinal observation history | Reconcile that exact attempt; no clear or resend. |
| Final tool continuation | Retained | Immutable final receipt | Continue the same live turn, or explicitly abort it. |
| Final end-turn/rejection | Released after preparation settles | Attempt, proof and all observations retained | Query/reconcile history only; do not resurrect the turn. |
| Explicitly retired settled turn | Released in both owners | Runtime schema-2 retirement plus history | Reopen without raw context; historical retries grant no new dispatch. |

### Coordinated publication and cleanup

`compile_and_stage_v3` calls `stage_with`: the exact owner holds its state lock,
validates capacity/current stage identity, publishes the runtime projection, and
only then inserts the exact stage. No tokenizer, provider effect or await occurs
inside this publication interval. Lock order is exact-state then runtime-state;
callbacks must not reenter the exact owner. Runtime validation/capacity failures
leave no new exact stage. An uncertain runtime directory sync poisons the runtime
owner; the possibly persisted projection does not recreate exact authorization
after restart.

Use `AgentdPromptPipelineOwner::clear_turn` for coordinated explicit aborts. It
refuses cleanup while a preparation or unresolved durable attempt exists, then
retires the runtime projection before removing the exact raw context. The public
method is not yet a proved authenticated ingress/lifecycle consumer. Calling the
lower-level runtime-only cleanup is not proof of two-owner retirement.

The runtime snapshot writes schema 2 with a canonical `retired` identity list.
Schema 1 remains readable only with no retirement entries. Retirement requires
existing dispatch history, no raw stage and no unresolved attempt. The history
still rejects a new dispatch with that turn identity. An older binary that does
not understand schema 2 must not be installed over it; schema rollback remains a
governed compatible binary/state operation, never stripping retirement markers.

### Completion headroom is not physical disk reservation

Before admitting work or additional retained state, exact persistence reserves
64 KiB for each unresolved final record; the runtime projection reserves 128 KiB
per unresolved terminal, including the maximum bounded token-position payload.
Record serialization enforces these bounds. Unknown observations retain the
reservation. Final settlement may consume its own reserved headroom. Old stores
are not claimed to have made historical reservations; reconciliation proceeds
only when the real serialized state still fits.

This is serialized-state admission accounting, not preallocation or a guarantee
against ENOSPC, I/O faults, power loss, malicious path replacement or rollback.
Neither 256, 1024 nor 4096 is raised. History counts remain bounded and eventual
history exhaustion still requires the migration below rather than data deletion.

## 11. Measurement interpretation and exact native evidence

`context_diagnostics` exposes raw-free counts and seventeen phase distributions.
Each phase retains at most 256 samples with nearest-rank p50/p95/p99, plus
saturating lifetime count/total and maximum. No samples means null latency, not a
zero-cost claim. Timers include error/cancellation scopes when those scopes exit.
Telemetry failure cannot authorize a request. These are process-local values;
restart resets them and does not invent an old monotonic-clock start time.

The phases cover compile/serialize, stage publication, request preparation,
cold/warm tokenizer configuration, artifact checks, tokenizer subprocess,
registry wait, final proof, pre-send persistence, terminal persistence, store
encoding, file write/sync, rename/directory sync, open/replay, live attempt through
persisted final, and recovered reconciliation. A live-attempt timer starts at
final-request observation and ends only after final persistence, so it includes
the intervening transport/response interval; it is not full user-turn latency.
Recovered reconciliation is measured separately and cannot reconstruct the lost
pre-crash duration.

Nested phase intervals overlap. Do not add their quantiles, subtract unrelated
quantiles, or count repeated command suites as additional distinct tests.
`staged_payload_bytes` covers only canonical exact payload lengths, not runtime
copies, allocator metadata, total heap or RSS. Allocation counts, queue fairness,
physical cancellation, target-host RSS and real provider latency remain distinct
measurements and acceptance obligations.

The read-only exact-candidate runner requires seventeen fully qualified native
names, not merely an aggregate pass count. The lifecycle command also requires
one bounded `CONTEXT_OWNER_PROFILE` line for 257 sequential completed turns on
the actual exact owner. That test uses a real signed local registry, files and a
real tokenizer protocol subprocess, but reuses one compilation and makes no real
provider request. Its profile is explicitly a protocol fixture, not authenticated
App Server E2E, immutable tokenizer qualification or selected-host acceptance.
The receipt binds the source/base/tested trees, command exit, required names,
observed names and log/artifact digests. SKIP, missing output, malformed profiles,
wrong counts or an aggregate-only pass fail the command's evidence gate.

## 12. Retained history migration still required

Raw-context retirement and schema-2 retirement markers are not an append-only
journal, compaction or archive implementation. The current whole-JSON store still
clones/validates/encodes bounded history on mutation. Do not claim constant-I/O
lookup or unbounded service life from the lifecycle improvement.

The remaining versioned migration must stay inside the existing durable owner:

1. Define a new immutable record format binding predecessor digest, generation,
   exact attempt/body/proof identity, canonical recovery archive and terminal.
2. Preserve every legacy pre-send and terminal; digest-only legacy rows remain
   unresolved and cannot be upgraded into authenticated dispatch evidence.
3. Write and sync a complete migrated segment before publishing a checkpoint.
   Checkpoints bind the entire segment set and the independent generation anchor.
4. Retain exact-attempt tombstones in a queryable bounded index/segment layout;
   archive retirement cannot make an old attempt admissible again.
5. Exercise every write/sync/rename/checkpoint/anchor cut, old valid backup,
   substituted path, concurrent writer and cross-host duplicate attempt on the
   selected host. Missing segments or a mismatched frontier fail closed.
6. Measure cold replay, warm lookup, sustained backlog growth and terminal drain
   with the same source/tree before choosing rollover/retention thresholds.

Until that source migration, native execution and independent host evidence exist,
capacity exhaustion is explicit backpressure. Operators must not edit JSON,
delete unresolved history, reset the owner or switch an unresolved V3 operation
to a legacy path to regain apparent availability.
