# ui.control server idempotency and ambiguity contract

## Normative rule

The browser's in-memory pending map is a duplicate-suppression aid. **The server operation ledger is the final idempotency authority.** A production backend must commit the operation identity before invoking any runtime side effect.

## Operation identity

A mutation is identified by:

```text
operation_id       client-generated stable identifier
semantic_digest    SHA-256 over the canonical operation intent domain
session_id         authenticated session
connection_generation
runtime_generation
displayed_revision
snapshot_digest
action
target_id
reason
```

`operation_id` is globally unique within the backend's documented retention horizon. The backend must not silently rebind it. An identical semantic digest is not sufficient for replay: the complete immutable authority and snapshot binding above must also match the admitted row.

## Atomic admission

Conceptual schema:

```sql
CREATE TABLE ui_control_operation (
  operation_id TEXT PRIMARY KEY,
  semantic_digest CHAR(64) NOT NULL,
  session_id TEXT NOT NULL,
  connection_generation BIGINT NOT NULL,
  runtime_generation BIGINT NOT NULL,
  displayed_revision BIGINT NOT NULL,
  snapshot_digest CHAR(64) NOT NULL,
  action TEXT NOT NULL,
  target_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  state TEXT NOT NULL,
  audit_trace_id TEXT NOT NULL UNIQUE,
  outcome_digest CHAR(64),
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
```

Admission transaction:

1. authenticate session and verify expiry/revocation/permission revision;
2. verify CSRF, Origin, request bounds, generation, revision, and snapshot digest;
3. attempt `INSERT` of `operation_id` and the complete immutable operation binding;
4. if a row exists and every semantic, session, generation, revision, snapshot, action, target, and reason field matches, return that row without a second side effect;
5. if any binding field differs—including the same semantic digest under another session or principal—return conflict and perform no side effect;
6. in the same transaction, create an outbox/queue record or otherwise atomically establish dispatch responsibility;
7. commit before returning `accepted`.

A database insert followed by a non-atomic best-effort queue publish is insufficient unless an outbox or equivalent recovery mechanism closes the gap.

## HTTP semantics

- `202`: accepted or previously accepted with an identical complete semantic and authority binding;
- `409`: operation ID already exists with different semantics, session authority, generation, revision, snapshot, target, action, or reason;
- `412`: displayed generation/revision/snapshot is stale;
- `401`: session expired or no longer valid;
- `403`: permission/CSRF/origin denied;
- `422`: invalid bounded input;
- `429`/`503`: no acceptance unless the response includes an existing operation record; client still performs lookup after uncertain transport failure.

Every accepted response returns the same `operationId`, `semanticDigest`, `status`, and server-generated `auditTraceId`. The `auditTraceId` is allocated with the durable ledger row, not per HTTP attempt, worker attempt, lookup, or session. Identical admission, pending lookup, terminal lookup, restart reconciliation, and same-principal post-session-switch lookup must all return that exact trace identity.

## Lookup and recovery

The backend exposes authenticated lookup by `operation_id` and `semantic_digest`. It returns:

- `found: false` only when no durable ledger record exists;
- active state (`accepted`, `pending`, or `indeterminate`);
- terminal state (`succeeded`, `failed`, `rejected`, or `cancelled`) with the original audit trace and optional outcome digest.

A client seeing timeout, abort after dispatch, connection reset, malformed acknowledgement, or acknowledgement identity mismatch treats the submission as indeterminate and performs lookup. It does not generate a replacement operation ID and does not automatically resend.

Once any accepted response or authenticated lookup has established an `auditTraceId`, every later observation for the same operation and semantic digest must preserve it. A missing or changed trace is an operation-ledger identity contradiction, not a new operation and not a harmless logging change. The client keeps the operation unresolved, emits an acknowledgement-mismatch/durability failure, and does not erase, retry, or replace the admitted identity.

An authenticated `found: false` response is a point-in-time absence observation, not final non-admission. A request already dispatched by this or another tab can commit after lookup. The client therefore retains the exact identity and scoped recovery record as `indeterminate`, continues bounded lookup, and neither reports a terminal result nor silently submits a replacement. If an accepted acknowledgement has already established an audit trace, absence contradicts backend durability and raises `UI_CONTROL_ACK_MISMATCH` without clearing the operation.

Final non-admission needs a separately versioned backend-owned transaction that binds the exact operation and permanently fences all delayed admission attempts, including in-flight workers, outboxes and session switches. A plain SELECT, browser lock, elapsed timeout or client process restart cannot supply that guarantee. The current V1 lookup has no such receipt and the client does not invent one. An operator must preserve unresolved records until backend-owned reconciliation establishes a supported terminal observation. This can retain genuinely unsent crash records; closing them safely is an explicit backend integration requirement.

Pending and transiently failed lookups use bounded round-robin scheduling with per-operation exponential backoff. Backoff must not allow early permanent-pending records to starve later identities, and one poison lookup must not prevent unrelated operations from being queried.

## Generation fencing

Before execution, the runtime owner revalidates the generation/revision contract or consumes a server-issued fence tied to the admitted record. Queue delay must not permit an operation admitted for an old generation to mutate a new owner generation.

## Terminality

Only the runtime owner or its durable terminal observer may transition an **accepted** operation to a runtime terminal state. Browser close, process restart, local pending eviction, request acknowledgement, or audit-log delivery is not terminal evidence. An absence observation remains indeterminate and cannot authorize terminal cleanup.

## Retention and replay

The operation ledger retention horizon must exceed all client retry/recovery windows and incident-response windows. Deletion requires a tombstone or namespace epoch that prevents an old operation ID from being rebound. Backup/restore procedures must preserve uniqueness, the original audit trace identity, and terminal facts.

## Qualification evidence

Production evidence must demonstrate:

- concurrent inserts for one operation ID create one row and one side effect;
- identical replay returns the same record and audit trace;
- digest conflict returns 409 with no side effect;
- a second authenticated identity cannot rebind the same operation ID even when it reuses the original semantic digest, and the rejected attempt leaves the original audit trace unchanged;
- crash between admission and dispatch is recovered from the outbox;
- accepted response loss is recovered by lookup;
- pending, terminal, restart-reconciled, and same-principal post-session-switch lookups retain the admission audit trace;
- an absent lookup before delayed admission retains the exact recovery identity; subsequent admission is observed without mutation replay;
- final non-admission, when supported by a versioned backend contract, durably prevents every delayed admission path;
- generation rollover fences delayed work;
- backup/restore does not reopen operation IDs or replace their audit traces;
- metrics and audit traces correlate one-to-one with ledger records.
