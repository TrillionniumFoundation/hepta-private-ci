# Kernel operations durable store V1

## Scope

`DurableOperationStore` is the authoritative SQLite **source owner** for `operation_ledger` and `cross_owner_outbox`. Its generic `destination_operation_dedup` table remains a qualification/reconciliation primitive; production destination facts stay destination-owned. `automation.taskflow` is the first concrete owner integration and atomically commits its domain mutation plus destination receipt in the automation database. The older BTreeMap ledger/outbox remains an oracle only.

## Durable schema

`operation_ledger` is keyed by `(scope, operation_id)` and stores the canonical semantic digest, predecessor digest, payload digest, destination, owner generation, authority epoch, revision, state, dispatch/indeterminate/terminal evidence digests and timestamps.

`cross_owner_outbox` shares the scoped operation key and stores destination, semantic digest, state, monotonically increasing fence, bounded attempts, next eligible time, worker, lease deadline, claim generation, acknowledgement digest, last error digest and terminal time. A foreign key binds it to the operation row. `(destination, operation_id)` is unique.

`destination_operation_dedup` is keyed by `(destination, operation_id)` and stores immutable semantic identity, terminal outcome and evidence digest for the generic qualification path. Migration `0002_retired_identity_tombstones.sql` adds immutable permanent source and generic-destination tombstones. The automation owner separately uses `0004_kernel_operation_dedupe.sql`, keyed by destination + scope + operation ID, so its task mutation and dedupe evidence share one owner transaction.

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

Source reconciliation verifies destination and semantic identity and then atomically moves `Dispatched`/`Indeterminate` work to `Applied`, `NotApplied` or `Quarantined` while settling the source outbox. Lower observer generations are stale. A higher generation may atomically adopt an unresolved external effect while recording matching terminal evidence; already-terminal history remains generation-fenced and cannot be reassigned by replay. Exact terminal replay is idempotent; changed terminal evidence conflicts.

## Reopen, migration and corruption handling

The store uses the repository `SqliteConfig::open_durable_evidence_pool` profile (WAL, `synchronous=FULL`, foreign keys and bounded busy timeout). SQLx migrations are checksum tracked. Store open performs `quick_check`, `foreign_key_check`, exact required schema-object checks and schema-version validation before returning a writer.

Read-only reopen uses the same integrity checks without running migrations. Required schema objects fail closed if missing.

## Capacity, retention and metrics

The V1 source ceiling is 100,000 operation rows per store. Claim/query batches are capped at 256 and attempts at 32. Lease/retry delays are bounded to 60 seconds in this source profile. New work rejects at the operation ceiling before mutation.

Terminal operations and generic destination receipts have explicit bounded prune APIs. Before a live row is deleted, the same transaction writes its immutable semantic tombstone; exact retired identity reuse is rejected and semantic drift conflicts. Active/unresolved work is never pruned by those APIs. Runtime metrics expose total/pending/unresolved/terminal operation counts, outbox queue/lease/ack/indeterminate counts, cumulative attempts and oldest unresolved age.

Deployment-specific retention periods and alert thresholds are host-profile facts and are not hard-coded as acceptance claims here.

## Recovery invariants

- Crash before atomic intent/outbox commit exposes neither row.
- Crash after commit preserves exactly one semantic operation/outbox identity.
- Expired pre-dispatch claims can be taken over with a higher fence.
- Once `Dispatched` is durable, recovery reconciles rather than resends blindly.
- A higher generation may take ownership only while settling unresolved `Dispatched`/`Indeterminate` work from matching destination evidence.
- Destination terminal identity is first-write immutable, and retention preserves a permanent semantic tombstone before live-row deletion.
- Queue acknowledgement never implies terminal external success.
- A stale generation/fence cannot settle a newer attempt.
- Compensation is a new authorized operation, never history mutation.
