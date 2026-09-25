# `auth.authbus` current implementation

## Current executable contract

The current candidate contains two deliberately separate AuthBus surfaces.

Signed message ingress verifies issuer-bound Ed25519 claims and consumes replay
state in the existing evidence SQLite owner. `SignedMessage::authenticate`
binds issuer/key epoch, message, subject, scope, payload, sequence and expiry.
`HeptaEvidenceStore::enqueue_authbus_message` atomically advances replay and
inserts the immutable delivery. Agentd's signed-text ingress is a named product
caller: it binds the Agent subject/thread scope, uses the durable outbox, and
delivers through the existing App Server queue.

Production-configured signed ingress also requires an independently retained
replay checkpoint outside the Agent home. Agentd opens and reconciles that
witness before attaching the ingress. Every successful replay mutation is
published as local-pending -> external fsync/rename/directory-sync -> local
promotion before admission success is reported. An older restored evidence
database therefore fails closed against the newer external witness.

The policy/quota owner is `AuthBusAuthorityHost`, backed by
`AuthBusAuthorityStore`. It owns durable policy revisions, issuer lifecycle,
trusted-time floor, quota registry, reservation state and settlement. The host
requires its own independently retained authority checkpoint outside the
authority database directory. Every authoritative table mutation marks the
semantic frontier dirty in the same SQLite commit; the host publishes the exact
successor frontier before returning from mutating owner operations.

Trusted time can no longer be fabricated by external callers:
`TrustedTimeSample` is opaque outside the crate and is produced by verification
of a signed `SignedTrustedTimeAttestation` from an active registered
`TrustedTime` issuer. Policy decisions remain `AuthorityPosture::DENY_ALL`;
they permit reservation decisions but do not mint final-use authority.

Quota accounting uses checked integer
`available + reserved + consumed == limit` semantics. A reservation binds the
stable operation ID, quota, amount, effect digest, policy identity/revision and
decision digest. The lifecycle is
`Held -> DispatchAttempted -> {Indeterminate, Settled, Released}` with
`Held -> {Cancelled, Expired}` for proven pre-dispatch terminal outcomes.
Restart detects pre-crash `DispatchAttempted` rows, blocks new reservation
issuance, and converts them to `Indeterminate`; their quota remains held until
authenticated terminal evidence arrives. Terminal rows may be moved to an
immutable archive without freeing their operation identity for reuse.

`BaoClient::consume_kv_v2_with_authbus` is the current source-composed external
effect path. It combines the caller-supplied durable operation identity,
AuthBus policy/quota reservation, the exact `FinalUseBinding`, a durable
dispatch fence immediately before the existing final-use protected HTTPS call,
and independently signed settlement evidence. Timeout, transport loss,
consumer-indeterminate or ambiguous final-use failure preserves the reservation
as indeterminate instead of refunding it.

The legacy `PreverifiedAuthEnvelope` / `ReplayWindow` API remains an
in-process compatibility surface. It does not authenticate signatures, survive
restart, reserve quota or grant effect authority.

## Public symbols and source bindings

- signed authentication: `IssuerRegistration`, `SignedMessageClaims`,
  `SignedMessage::authenticate`, `AuthenticatedMessage` in
  `codex-rs/hepta-authbus/src/signed.rs`;
- durable authority owner: `AuthBusAuthorityHost`,
  `PolicyDecision`, `QuotaReservation`,
  `Settlement` in `codex-rs/hepta-authbus/src/{host,authority_store,quota_store,settlement_store}.rs`;
- issuer/trusted-time lifecycle in
  `codex-rs/hepta-authbus/src/{trust,trust_store}.rs`;
- authority rollback/restart reconciliation in
  `codex-rs/hepta-authbus/src/recovery.rs` and migration
  `0004_recovery_retention.sql` and `0005_dispatch_boundary.sql`;
- durable signed ingress/replay/outbox in
  `codex-rs/hepta-evidence/src/authbus_{store,outbox,outbox_worker,recovery}.rs`;
- Agentd source composition in
  `codex-rs/hepta-agentd/src/{authbus_ingress,authbus_checkpoint,runtime}.rs`;
- final-use/quota provider composition in
  `codex-rs/hepta-bao-adapter/src/https_consumer.rs`.

## Durability and activation

Policy, quota, reservation, issuer and trusted-time state use WAL SQLite with
FULL synchronous writes and `BEGIN IMMEDIATE` serialization. Policy revisions
are retained in an append-only history; revoked policy heads can be retired only
after live reservation references are gone. Retired issuer epochs remain
tombstones while no longer consuming active-lifecycle capacity.

Both replay state and the policy/quota/trust state have separate external
anti-rollback witnesses. These are source-implemented host protocols, not proof
that a production operator has provisioned independent checkpoint storage or
trust roots. Product source composition exists for Agentd signed text and the
Bao read boundary; activation, target-host qualification and operator acceptance
remain separate gates.

## Target-only design

The following are not established by this candidate:

- a production deployment of independently governed trusted-time/checkpoint and
  issuer-key services;
- qualification of restart recovery across the existing `kernel.operations`
  durable transaction owner and both AuthBus owners. AuthBus binds the supplied
  stable operation ID but does not replace the operation owner;
- generic provider/effect coverage beyond the registered Agentd signed-text and
  Bao KV-v2 read paths;
- distributed multi-host AuthBus ownership or consensus;
- independent security acceptance, canary/promotion or release.

## Known limits and non-claims

`AuthBusAuthorityStore` is crate-private. The public mutation boundary is
`AuthBusAuthorityHost`; there is no public raw-store accessor or caller-supplied
settlement issuer registration.
The external checkpoint file hardening currently relies on Unix ownership,
single-link, private-directory and fsync semantics.

The Bao path consumes a caller-provided stable operation identity. The repository
already exposes `DurableOperationStore` in `kernel.operations` as a
production-oriented SQLite owner alongside explicitly separate reference
models. AuthBus tests prove binding to the supplied identity; they do not alone
qualify crash/restart recovery across that existing operation owner and both
AuthBus owners.

Queue acceptance is not provider/model terminality. AuthBus receipts and policy
decisions do not grant final-use authority. An indeterminate reservation is not
automatically retried or refunded.

## Verification

Focused native tests cover signed-field substitution, replay contention and
reopen, outbox crash-after-send-before-ack, last-unit reservation races,
idempotent settlement, explicit cancellation, database-level illegal
state/deletion rejection, terminal compaction, real old-database rollback
detection and restart reconciliation. Bao product tests exercise real local TLS
through policy -> reserve -> dispatch fence -> final-use -> signed settlement,
plus timeout/indeterminate quota holding. Agentd product tests exercise the real
daemon/App Server signed-text queue with the external replay witness.

These are source test identities until the exact source-head and deterministic
synthetic-merge workflows for this unchanged candidate reach terminal success.

## Integration prerequisites

Production enrollment must provide independently governed issuer keys,
revocation feeds, trusted-time attestations and both external checkpoint stores.
A provider host must supply the canonical operation identity and current
`FinalUseAuthority`; the same final payload/effect binding must be used for the
reservation and final-use grant. Operators must complete target-host
crash/power-loss, capacity, backup/restore and independent security
qualification before activation.

## Correctness continuation: settlement and owner protocol

`AuthBusAuthorityHost::settle(evidence, time)` resolves the evidence issuer ID,
key epoch and `Settlement` purpose from durable state in the same write
transaction as quota settlement. New settlement requires an active issuer at
admission, including after writer-lock waiting. Revoked/retired epochs cannot
submit new results even with earlier observation times. An exact retry of an
already committed terminal receipt returns its original result after issuer
revocation or expiry; no new effect or quota consumption is created.

`dispatched_at_ms` is written once with `Held -> DispatchAttempted` and included
in the checkpoint digest. `updated_at_ms` tracks later local state changes.
A legitimate observation after dispatch but before `Indeterminate` may arrive
late, including after restart. A pre-dispatch observation remains invalid.
Migration 0005 backfills legacy `DispatchAttempted` rows from their exact last
update. Legacy indeterminate/terminal rows retain an unknown boundary rather
than a fabricated time. Terminal rows remain readable and archiveable; an
indeterminate row with no proven boundary cannot be newly settled/refunded.
Migration 0005 retains the local frontier dialect. An already published v4
witness is validated and promoted with the v1 digest, then separately advanced
to the v2 digest that binds dispatch time. Once v2 is committed, a legacy digest
cannot downgrade the owner. Migration regressions cover both sides of external
publication and a second crash after local legacy promotion.

An async permit and stable private database/checkpoint lock files serialize the
complete predecessor-recovery, local commit, external publication and local
promotion sequence. Database locks also fence alternate checkpoint names.
Contention returns `OwnerBusy` before a mutation. The locks are not taken on
the witness inode replaced by rename. The raw store is not publicly writable.

Every write first reconciles an interrupted predecessor. A publication error
does not assert that SQLite rolled back: query/retry the same operation rather
than inventing a replacement identity. Before promoting a visible external
witness, the host repeats file and directory fsync and verifies identity.
Bootstrap creates an external witness only over a pristine authority owner.

Replay recovery verifies pending generation and semantic frontier before
returning an unpublished checkpoint to its host. Corrupt pending metadata is
not published just because its external predecessor matches local state.

New regression sources include `host_tests.rs` (concurrent writers, separate
process locking, alternate witness paths, failed publication and lost ACK),
`settlement_boundary_tests.rs` (revocation during lock waiting, forged signing
key and delayed success/no-effect after restart), and `migration_tests.rs`
(real version-4 terminal/archive migration). The evidence owner's
`authbus_outbox_tests.rs` exercises signed enqueue, external publication before
local promotion, reopen, exact delivery, ACK and a second reopen without
redelivery. These are source identities, not executable pass receipts.

An earlier review misidentified workflow job 107538163316 as an AuthBus outbox
failure. Its retained raw log instead shows Worker/App Server fixture failures
including an unconfigured Codex executable. The newly added AuthBus regression
is independent evidence; it must not be described as turning that nonexistent
historical AuthBus test green. Execution reports must identify the exact source,
command, selected tests, terminal result and any skipped/blocked work.


## Live writer-lock identity

Each stable database/checkpoint lock is bound to its opened inode and private
canonical path. The host checks both identities before and after taking the OS
locks, and before and after checkpoint synchronization. Deletion, replacement,
additional hard links, non-private file/directory permissions or owner drift
fence the affected handle. Restoring a name or permissions does not reactivate a
handle that observed an unsafe identity: recovery requires a fresh host open.

If the identity changes after a local operation commits, the call does not
acknowledge a published result. A newly opened host reconciles the existing
dirty frontier and the caller retains the original operation identity. This is
not evidence that the local transaction rolled back, and not permission to
redispatch an external effect. Private directories and the local OS remain
trusted: these checks are not distributed ownership or protection against a
privileged adversary replacing paths continuously inside filesystem calls.

`host_lock_tests.rs` covers replaced and deleted database/checkpoint locks,
permission/link drift, permanently fenced handles, safe new-owner reopening,
and lost acknowledgement after a committed mutation. Execution evidence must
still bind the unchanged candidate rather than these source test names.
