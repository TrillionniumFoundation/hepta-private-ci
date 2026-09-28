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
