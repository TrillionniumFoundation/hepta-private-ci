# channel.matrix storage schema

`MatrixDurableStore` is a per-Agent SQLite owner. The database is opened only under the canonical private Matrix root and verified before serving reads or writes.

## 1. Database identity

- File: `matrix_1.sqlite3`
- Migration owner: `codex-rs/hepta-matrix-store/migrations/`
- Current dispatch schema addition: `0006_matrix_dispatch_ledger.sql`
- Writer: the exact per-Agent `hepta-matrixd` generation admitted by the process lock and supervisor lease
- Durability: SQLite durable-evidence configuration; migration and integrity failure fail startup closed

## 2. Core domains

| Domain | Purpose | Authoritative key |
|---|---|---|
| `matrix_meta` | schema and owner identity | singleton |
| `room_bindings` | enrolled room -> Agent Matrix identity, revision and Matrix-plane generation | room ID |
| `room_threads` | room/binding/generation -> App Server project/thread | composite binding identity |
| `inbox_events` | deduplicated ingress event projection | Matrix event ID |
| `inbox_dispatches` | restart-safe Agentd/App Server dispatch | ingress event ID |
| `outbox_messages` | durable transport queue with stable transaction identity | outbox ID; stable transaction unique |
| sync checkpoint/mutation tables | exact durable `/sync` frontier and redaction/correction lineage | owner checkpoint and source event identity |
| pending approval/control tables | bounded local control state | typed request/approval identity |
| `matrix_dispatch_ledger` | single source of send truth | stable transaction ID |
| `matrix_dispatch_observations` | append-only transport/homeserver/redaction history | observation sequence plus semantic uniqueness |
| `matrix_dispatch_authority_claims` | immutable per-attempt final-use evidence | stable transaction ID + attempt; grant ID unique |

## 3. Dispatch ledger columns

`matrix_dispatch_ledger` binds:

- stable transaction ID;
- unique operation ID;
- logical outbox ID;
- room ID, binding revision and Matrix-plane generation;
- canonical payload SHA-256;
- optional authority epoch, grant ID and matching grant payload SHA-256;
- durable state;
- accepted and terminal event IDs;
- transport, send and redaction observation digests;
- current attempt;
- prepared, updated and terminal-observed timestamps.

Identity columns are immutable by trigger. Rows cannot be deleted. Unique partial indexes protect accepted and terminal event IDs. Unresolved rows have a bounded lookup index over state, update time and transaction ID.

## 4. Authority claims

Each `matrix_dispatch_authority_claims` row records the exact evidence observed when the kernel authority burned the grant nonce:

- operation, subject and destination;
- homeserver, Matrix user, device and session generation;
- authority epoch and revocation revision;
- unique grant ID;
- request, scope and payload digests;
- attempt;
- expiry and claim time.

Claims are immutable and undeletable. They are not reusable permits. Qualified success/redaction requires a matching claim for the exact transaction, operation, payload, attempt and owner subject.

Future schema revisions should additionally persist the serialized `VerifiedUseTokenWitnessV1` digest and claim-time revocation-head digest. Until that migration is present, the epoch/revision and canonical binding are the durable proof surface.

## 5. Observation history

`matrix_dispatch_observations` is append-only. Kinds are:

- `dispatch_started`;
- `transport_accepted`;
- `transport_indeterminate`;
- `transport_rejected`;
- `homeserver_event`;
- `redaction`.

Rows bind transaction, attempt, optional event ID, semantic digest and observation time. Duplicate semantic observations are idempotent. Contradictory identities produce a conflict and no mutation.

## 6. Outbox claim and fencing

`outbox_messages.attempts` is the current lease epoch. Every dispatch result update carries `expected_attempt`; stale workers cannot settle a newer claim. `lease_until_ms` bounds ownership. A clean cancellation should release records that have not entered physical I/O; a record whose effect may have entered remains retry/reconciliation state with the same stable transaction.

The long-term schema target is an explicit random `claim_token` in addition to attempt. Until that migration lands, attempt is the durable fencing token and must never be decremented or reused.

## 7. Sync atomicity

When a `/sync` timeline mutation contains the stable transaction ID of an outbound event, the store performs in one transaction:

1. validate current room binding/generation and authenticated sender;
2. append the homeserver observation;
3. transition the dispatch ledger to qualified or unqualified terminal state;
4. settle the matching outbox row;
5. append the change record;
6. advance the sync checkpoint.

Redaction follows the same rule. The cursor cannot commit without the corresponding correction to durable send truth.

## 8. Startup verification

Store open must verify at least:

- owner identity and schema version;
- migration checksum/history;
- required tables, indexes, views and triggers;
- foreign-key integrity;
- dispatch state constraints;
- immutable identity triggers;
- uniqueness of operation, transaction and event identities;
- no malformed digest, generation or timestamp rows.

A mismatch is corruption or an unsupported predecessor, never an invitation to rebuild from a projection silently.

## 9. Retention and backup

Dispatch identities, authority claims and observations are audit evidence and require an authenticated retention/archival policy before compaction. Backups must preserve SQLite consistency and the matching authority frontier. Restore qualification must prove that redacted/revoked content cannot reappear through stale indexes, session stores or outbox rows.
