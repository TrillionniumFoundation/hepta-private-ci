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

`operation_id` is globally unique within the backend's documented retention horizon. The backend must not silently rebind it.

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
3. attempt `INSERT` of `operation_id` and `semantic_digest`;
4. if a row exists with the same digest, return that row without a second side effect;
5. if a row exists with a different digest, return conflict and perform no side effect;
6. in the same transaction, create an outbox/queue record or otherwise atomically establish dispatch responsibility;
7. commit before returning `accepted`.

A database insert followed by a non-atomic best-effort queue publish is insufficient unless an outbox or equivalent recovery mechanism closes the gap.

## HTTP semantics

- `202`: accepted or previously accepted with identical semantics;
- `409`: operation ID already exists with different semantics;
- `412`: displayed generation/revision/snapshot is stale;
- `401`: session expired or no longer valid;
- `403`: permission/CSRF/origin denied;
- `422`: invalid bounded input;
- `429`/`503`: no acceptance unless the response includes an existing operation record; client still performs lookup after uncertain transport failure.

Every accepted response returns the same `operationId`, `semanticDigest`, `status`, and server-generated `auditTraceId`.

## Lookup and recovery

The backend exposes authenticated lookup by `operation_id` and `semantic_digest`. It returns:

- `found: false` only when no durable ledger record exists;
- active state (`accepted`, `pending`, or `indeterminate`);
- terminal state (`succeeded`, `failed`, `rejected`, or `cancelled`) with audit trace and optional outcome digest.

A client seeing timeout, abort after dispatch, connection reset, malformed acknowledgement, or acknowledgement identity mismatch treats the submission as indeterminate and performs lookup. It does not generate a replacement operation ID and does not automatically resend.

## Generation fencing

Before execution, the runtime owner revalidates the generation/revision contract or consumes a server-issued fence tied to the admitted record. Queue delay must not permit an operation admitted for an old generation to mutate a new owner generation.

## Terminality

Only the runtime owner or its durable terminal observer may transition to a terminal state. Browser close, process restart, local pending eviction, request acknowledgement, or audit-log delivery is not terminal evidence.

## Retention and replay

The operation ledger retention horizon must exceed all client retry/recovery windows and incident-response windows. Deletion requires a tombstone or namespace epoch that prevents an old operation ID from being rebound. Backup/restore procedures must preserve uniqueness and terminal facts.

## Qualification evidence

Production evidence must demonstrate:

- concurrent inserts for one operation ID create one row and one side effect;
- identical replay returns the same record;
- digest conflict returns 409 with no side effect;
- crash between admission and dispatch is recovered from the outbox;
- accepted response loss is recovered by lookup;
- generation rollover fences delayed work;
- backup/restore does not reopen operation IDs;
- metrics and audit traces correlate one-to-one with ledger records.
