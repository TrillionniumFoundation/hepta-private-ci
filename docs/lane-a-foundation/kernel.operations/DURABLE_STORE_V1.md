# Kernel operations durable store V1

## Scope

`DurableOperationStore` is the authoritative SQLite owner for `operation_ledger`, `cross_owner_outbox` and the repository reference implementation of destination-side operation deduplication. The older BTreeMap ledger/outbox remains an oracle only.

## Durable schema

`operation_ledger` is keyed by `(scope, operation_id)` and stores the canonical semantic digest, predecessor digest, payload digest, destination, owner generation, authority epoch, revision, state, dispatch/indeterminate/terminal evidence digests and timestamps.

`cross_owner_outbox` shares the scoped operation key and stores destination, semantic digest, state, monotonically increasing fence, bounded attempts, next eligible time, worker, lease deadline, claim generation, acknowledgement digest, last error digest and terminal time. A foreign key binds it to the operation row. `(destination, operation_id)` is unique.

`destination_operation_dedup` is keyed by `(destination, operation_id)` and stores immutable semantic identity, terminal outcome and evidence digest.

## Atomic publication

`prepare_intent` uses one `BEGIN IMMEDIATE` transaction. The operation row and outbox row commit together or neither becomes visible. An existing scoped operation is replayable only when the complete semantic identity matches and its paired outbox row still matches; an operation without the paired outbox is corruption, not a recoverable partial success.

## Claims, leases and owner takeover

Only pending operations can be claimed for dispatch. A claim binds worker ID, owner generation, fence, attempt count and lease deadline. The fence increments on every claim/renew/retry. An unexpired lease excludes another worker. After expiry a non-stale generation can take over, updating the operation owner generation and revision before receiving a new fence. Every stale lease is rejected by renew/retry/dispatch/ack paths.

Attempts are capped. Exhaustion quarantines both operation and outbox with a deterministic evidence digest rather than retrying forever.

## Authority and dispatch

`DurableDispatcher` never mints authority. It obtains a real `VerifiedUseToken` through `FinalUseAuthority::claim` for the durable operation's exact final-use binding. The lease is checked before and after claim.

The store persists `Dispatched` before synchronous adapter entry. `FinalUseAuthority::with_verified_use` then revalidates the token immediately around that adapter boundary. This deliberately prefers a conservative false-positive "may have crossed" record over an unsafe false-negative that could cause a duplicate retry after a crash.

A transport acknowledgement is stored on the outbox but the operation remains `Dispatched`. If the adapter cannot supply a trustworthy acknowledgement the operation/outbox becomes `Indeterminate`. Neither state permits blind resend.

## Destination dedupe and reconciliation

A destination receipt is first-write immutable. Exact replay returns the same receipt; a changed semantic digest, outcome or evidence digest conflicts.

Source reconciliation loads the receipt from the destination authority, verifies destination and semantic identity, verifies the current owner generation, and then atomically moves the operation to `Applied`, `NotApplied` or `Quarantined` while settling the source outbox. Exact terminal replay is idempotent; changed terminal evidence conflicts.

## Reopen, migration and corruption handling

The store uses the repository `SqliteConfig::open_durable_evidence_pool` profile (WAL, `synchronous=FULL`, foreign keys and bounded busy timeout). SQLx migrations are checksum tracked. Store open performs `quick_check`, `foreign_key_check`, exact required schema-object checks and schema-version validation before returning a writer.

Read-only reopen uses the same integrity checks without running migrations. Required schema objects fail closed if missing.

## Capacity, retention and metrics

The V1 source ceiling is 100,000 operation rows per store. Claim/query batches are capped at 256 and attempts at 32. Lease/retry delays are bounded to 60 seconds in this source profile. New work rejects at the operation ceiling before mutation.

Terminal operations and destination receipts have explicit bounded prune APIs. Active/unresolved work is never pruned by those APIs. Runtime metrics expose total/pending/unresolved/terminal operation counts, outbox queue/lease/ack/indeterminate counts, cumulative attempts and oldest unresolved age.

Deployment-specific retention periods and alert thresholds are host-profile facts and are not hard-coded as acceptance claims here.

## Recovery invariants

- Crash before atomic intent/outbox commit exposes neither row.
- Crash after commit preserves exactly one semantic operation/outbox identity.
- Expired pre-dispatch claims can be taken over with a higher fence.
- Once `Dispatched` is durable, recovery reconciles rather than resends blindly.
- Destination terminal identity is first-write immutable.
- Queue acknowledgement never implies terminal external success.
- A stale generation/fence cannot settle a newer attempt.
- Compensation is a new authorized operation, never history mutation.
