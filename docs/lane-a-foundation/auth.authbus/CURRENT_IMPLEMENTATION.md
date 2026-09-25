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
  `AuthBusAuthorityStore`, `PolicyDecision`, `QuotaReservation`,
  `Settlement` in `codex-rs/hepta-authbus/src/{host,authority_store,quota_store,settlement_store}.rs`;
- issuer/trusted-time lifecycle in
  `codex-rs/hepta-authbus/src/{trust,trust_store}.rs`;
- authority rollback/restart reconciliation in
  `codex-rs/hepta-authbus/src/recovery.rs` and migration
  `0004_recovery_retention.sql`;
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
- a production-durable `kernel.operations` transaction owner. AuthBus binds the
  supplied stable operation ID but does not replace that owner;
- generic provider/effect coverage beyond the registered Agentd signed-text and
  Bao KV-v2 read paths;
- distributed multi-host AuthBus ownership or consensus;
- independent security acceptance, canary/promotion or release.

## Known limits and non-claims

`AuthBusAuthorityStore` remains a lower-level source API for focused tests and
owner construction; production mutation is expected to pass through
`AuthBusAuthorityHost` so external checkpoint publication cannot be skipped.
The external checkpoint file hardening currently relies on Unix ownership,
single-link, private-directory and fsync semantics.

The Bao path consumes a caller-provided stable operation identity because the
repository's current `kernel.operations` implementation is still a bounded
in-memory reference model. This candidate therefore proves AuthBus binding to
that identity, not durable cross-owner operation-ledger closure.

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
