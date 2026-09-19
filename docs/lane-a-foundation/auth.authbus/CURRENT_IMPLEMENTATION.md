# `auth.authbus` current implementation

## Current executable contract

The current candidate has two deliberately separated surfaces.

The signed-admission surface verifies issuer-bound Ed25519 messages, consumes durable replay state in the canonical EvidenceStore, and supports fenced durable delivery. Successful admission still grants no effect authority; `VerificationReceipt` remains `AuthorityPosture::DENY_ALL`.

The control surface adds versioned authorization policy, fixed-window integer quota accounting, exact reservation binding and observed-cost settlement in the same EvidenceStore lineage. `authorize_and_reserve_authbus` persists principal, action, scope, quota revision and the adapter's complete final-effect digest under one semantic binding digest. `begin_authbus_effect` takes the EvidenceStore write lock, reads the owner clock, rechecks the exact principal/action/scope/effect binding plus current policy/quota revisions, and atomically moves `Active -> EffectStarted` before an adapter may cross the external boundary. Once that marker commits, cancellation and expiry cannot refund the reservation. Settlement is accepted only from `EffectStarted` or `Quarantined`; indeterminate outcomes remain fully reserved until terminal reconciliation.

## Public symbols and source bindings

- Signed authentication: `IssuerRegistration`, `SignedMessageClaims::signing_bytes`, `SignedMessage::authenticate` and `AuthenticatedMessage` in `codex-rs/hepta-authbus/src/signed.rs`.
- Legacy deny-all replay model: `PreverifiedAuthEnvelope`, `TrustedReplayContext`, `ReplayWindow` and `VerificationReceipt` in `codex-rs/hepta-authbus/src/lib.rs`.
- Pure policy/quota/reservation types: `PolicyRule`, `PolicyRevision`, `QuotaConfig`, `Reservation`, `ReservationState` and `Settlement` in `codex-rs/hepta-authbus/src/control.rs`.
- Durable admission/outbox: `HeptaEvidenceStore::admit_authbus_message` plus the AuthBus outbox APIs in `codex-rs/hepta-evidence/src/authbus_store.rs`, `authbus_outbox.rs` and `authbus_outbox_worker.rs`.
- Durable authorization/quota control: `install_authbus_policy`, `configure_authbus_quota`, `authorize_and_reserve_authbus`, `begin_authbus_effect`, `settle_authbus_reservation`, cancellation/expiry/quarantine and recovery scanning in `codex-rs/hepta-evidence/src/authbus_control.rs`.
- Replay/restore recovery: checkpoint verification and `retire_authbus_replay_epoch` in `codex-rs/hepta-evidence/src/authbus_recovery.rs`.
- Physical schemas: EvidenceStore migrations `0009` through `0012`.
- Narrow hosts/consumers: Agentd signed-text ingress in `codex-rs/hepta-agentd` and the candidate `BaoClient::consume_kv_v2_with_authbus` effect composition in `codex-rs/hepta-bao-adapter/src/https_consumer.rs`.

## Durability and activation

Evidence migrations 0009/0010 retain signed replay/outbox state. Migration 0011 adds immutable policy revisions, a fixed-window quota registry, semantically bound reservations and fail-closed database triggers. Migration 0012 adds restore-checkpoint bindings and replay-epoch tombstones.

Quota arithmetic is integer-only. For each current quota revision/window, `reserved + consumed <= endowment`. Every quota revision also carries a bounded `max_active_per_principal`; Active, EffectStarted and Quarantined reservations count toward that principal cap and contribute to `reserved`. Settled observed cost contributes to `consumed`; cancelled and expired reservations contribute to neither. A quota revision cannot advance while quota remains held, same-window revision changes cannot erase prior consumption, and a new window cannot overlap its predecessor.

Agentd trust remains owner-controlled and fail-closed. The trust file supports the current key epoch plus at most four bounded previous epochs with independent revocation and optional validity windows. Normal AuthBus startup is verify-only and requires a separately supplied restore-checkpoint witness whenever trust is enabled. Replay-key retirement verifies that witness inside the same `BEGIN IMMEDIATE` transaction as active-outbox inspection, tombstone creation and replay deletion.

The current source candidate composes two callers: the narrow Agentd signed-text path for authentication/delivery and the Bao KV-v2 wrapper for an exact reservation-bound effect. Neither composition is production-accepted merely because the source exists.

## Target-only design

The repository does not itself provide an independently governed trusted-time service, an independently retained production checkpoint service, managed issuer enrollment/key-rotation ceremony, operator-controlled target-host provisioning, or independent product/security acceptance. Broader provider/effect families must bind their own final payload and observed-cost semantics before using the AuthBus control surface.

## Known limits and non-claims

The legacy `ReplayWindow` remains process-local. SQLite durability does not by itself prevent rollback if the external checkpoint witness is restored with the same backup. The current owner clock is the local host wall clock and is not an independently governed trusted-time source. Bao accounting currently represents the bounded KV-v2 read profile and must not be generalized to unrelated effect cost semantics without a new binding/profile.

Neither admission, reservation, EffectStarted nor queue acknowledgement proves an external effect completed. Exactly-once external effects are not claimed. Indeterminate outcomes remain held/quarantined until a current-fence reconciler records terminal evidence.

No source change self-grants production activation, independent acceptance, promotion or release.

## Verification

Native source tests include:

- signed-field substitution, issuer/key epoch, revocation, expiry and scope checks;
- replay reopen, contention, bounded outbox leases/fences and crash-after-send recovery;
- BUS-01 last-unit contention and BUS-02 settlement idempotency/conflict;
- BUS-03 EffectStarted versus expiry and BUS-04 policy revocation;
- full semantic/idempotency binding, owner-clock expiry, quota-window rollover and same-window consumption preservation;
- SQLite binding/state/delete triggers, crash/reopen after EffectStarted and failed-settlement recovery;
- actual old-SQLite restore detection and replay-retirement tombstones;
- Bao request-binding drift, timeout quarantine, consumer-indeterminate reconciliation, settlement-failure recovery and successful settlement.

These test identities are source evidence only. Exact-head and deterministic synthetic-merge workflows must execute successfully for the candidate SHA before qualification is claimed.

## Integration prerequisites

A selected host must provision current issuer registrations, independently retain and present the restore-checkpoint witness outside the SQLite backup lineage, govern clock integrity, register the exact effect binding/cost profile, and retain terminal reconciliation for indeterminate effects. Before production use, run exact-head and synthetic-merge qualification, native Agentd/Bao product tests, independent semantic/security review, target-host rollback/fault measurements, operator acceptance and the normal activation/promotion gates.
