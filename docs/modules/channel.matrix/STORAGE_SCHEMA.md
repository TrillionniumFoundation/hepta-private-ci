# channel.matrix storage schema

`MatrixDurableStore` is the single per-Agent SQLite writer for Matrix ingress and egress. It opens only below the canonical private Matrix root, under the process lock and exact supervisor lease, and verifies migrations and integrity before serving work.

## 1. Database identity

- File: `matrix_1.sqlite3`
- Migration owner: `codex-rs/hepta-matrix-store/migrations/`
- Dispatch truth: `0006_matrix_dispatch_ledger.sql`
- Random claim fencing and append-only attempt evidence: `0007_matrix_claim_fencing.sql`
- Writer: one exact per-Agent `hepta-matrixd` process generation
- Durability: SQLite durable-evidence configuration; migration, fingerprint or integrity mismatch fails startup closed

## 2. Core domains

| Domain | Purpose | Authoritative key |
|---|---|---|
| `matrix_meta` | schema and owner identity | singleton |
| `room_bindings` | enrolled room, user, revision and Matrix-plane generation | room ID |
| `room_threads` | room/binding/generation to App Server project/thread | composite binding identity |
| `inbox_events` | deduplicated ingress projection | Matrix event ID |
| `inbox_dispatches` | restart-safe Agentd/App Server dispatch | ingress event ID |
| `outbox_messages` | bounded transport queue and stable transaction identity | outbox ID; transaction unique |
| sync checkpoint/mutation tables | durable `/sync` frontier and correction/redaction lineage | owner checkpoint/source event |
| pending approval/control tables | bounded local control state | typed request/approval identity |
| `matrix_dispatch_ledger` | one source of logical-send and terminal truth | stable transaction ID |
| `matrix_dispatch_observations` | append-only transport/homeserver/redaction observations | sequence plus semantic uniqueness |
| `matrix_dispatch_authority_claims` | immutable request/grant claim evidence | transaction + attempt; grant unique |
| `matrix_dispatch_attempt_claims` | immutable random-capability lease identity | transaction + attempt |
| `matrix_dispatch_active_claims` | current claim phase | stable transaction ID |
| `matrix_dispatch_authority_witnesses` | verified-use witness and revocation-head digests | transaction + attempt |
| `matrix_dispatch_attempt_events` | complete append-only attempt lifecycle | event sequence |

## 3. Dispatch ledger

`matrix_dispatch_ledger` binds the stable transaction, unique operation, outbox identity, room, binding revision, Matrix-plane generation, canonical payload digest, optional replacement target, authority/grant binding, state, accepted/terminal event IDs, observation digests, attempt and timestamps.

Identity columns are immutable by trigger. Rows cannot be deleted. Unique partial indexes protect accepted and terminal event IDs. A terminal homeserver observation must satisfy the authority-claim invariant; SDK/HTTP return cannot set `succeeded`.

## 4. Random-capability claim fencing

Each outbox claim increments the durable attempt and uses `lease_epoch = attempt`. The owner mints an opaque 32-byte process-local capability from two independent UUIDv4 draws. Only its SHA-256 digest is persisted.

`matrix_dispatch_attempt_claims` records:

- stable transaction;
- attempt and lease epoch;
- unique capability digest;
- claimed and lease-expiry timestamps.

`matrix_dispatch_active_claims` references that complete identity and permits only `claimed`, `authorized` and `dispatching`. Updates and closures require the live attempt/lease/token identity. An expired claim receives an `expired` event before replacement. Claim identities and history are immutable and undeletable.

## 5. Authority evidence

The legacy `matrix_dispatch_authority_claims` row binds operation, subject, destination, homeserver, Matrix user, device, session generation, request/scope/payload digests, authority epoch, revocation revision, grant ID, attempt, expiry and claim time.

Migration 7 adds `matrix_dispatch_authority_witnesses`, bound by foreign key to the exact random claim. It persists:

- authority epoch and revocation revision;
- grant ID;
- `VerifiedUseTokenWitnessV1` digest;
- claim-time revocation-head digest;
- witness-recorded time.

The witness is immutable audit evidence, not reusable authority. The raw final-use token and raw claim capability never enter SQLite.

## 6. Attempt event history

`matrix_dispatch_attempt_events` is append-only and records:

- `claimed`, `prepared`, `authorized`, `dispatching`;
- `transport_accepted`, `indeterminate`, `retry_scheduled`;
- `confirmed`, `redacted`, `permanently_rejected`;
- `revoked`, `canceled`, `expired`.

Each event binds transaction, attempt, lease epoch, capability digest, optional event ID, typed failure class, optional retry hint, optional detail digest and timestamp. Failure classes distinguish rate limiting, DNS, TLS, connect timeout/failure, read timeout, connection reset, response loss, server unavailability, permanent rejection and authority denial.

## 7. Sync atomicity

For a `/sync` mutation containing the outbound transaction identity, one transaction:

1. validates room binding, generation and authenticated sender;
2. appends the homeserver observation;
3. transitions the dispatch ledger to qualified or explicitly unqualified terminal state;
4. appends the corresponding attempt event through migration triggers;
5. settles the matching outbox row;
6. appends the change record;
7. advances the sync checkpoint.

Redaction follows the same rule. The cursor cannot commit without the matching durable correction.

## 8. Startup verification

Store open verifies at least:

- owner identity, schema version and migration history;
- required tables, indexes, views and triggers from migrations 1-7;
- foreign-key and integrity checks;
- dispatch-state constraints and terminal-authority invariant;
- immutable/delete-prevention triggers;
- uniqueness of operation, transaction, event, grant and claim-token identities;
- active-claim phase/lease consistency;
- digest, generation, attempt and timestamp bounds.

A mismatch is corruption or unsupported schema, never silent projection rebuild.

## 9. Retention, backup and restore

Dispatch identities, grants, witnesses, claim digests, observations and attempt events are audit evidence. Compaction requires authenticated archival and cannot delete unresolved or terminal lineage. A backup must preserve a consistent SQLite snapshot together with matching authority-frontier metadata. Restore qualification must prove revoked/redacted content, expired active claims and stale session/outbox state cannot resurrect or re-enter physical I/O.
