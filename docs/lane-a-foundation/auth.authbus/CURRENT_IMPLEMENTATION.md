# `auth.authbus` current implementation

## Current executable contract

The current candidate has two deliberately separated surfaces.

The signed-admission surface verifies issuer-bound Ed25519 messages, consumes durable replay state in the canonical EvidenceStore, and supports fenced durable delivery. Successful admission still grants no effect authority; `VerificationReceipt` remains `AuthorityPosture::DENY_ALL`.

The control surface adds versioned authorization policy, fixed-window integer quota accounting, exact reservation binding and observed-cost settlement in the same EvidenceStore lineage. `authorize_and_reserve_authbus` persists principal, action, scope, quota revision and the adapter's complete final-effect digest under one semantic binding digest. `begin_authbus_effect` takes the EvidenceStore write lock, reads the owner clock, rechecks the exact principal/action/scope/effect binding plus current policy/quota revisions, and atomically moves `Active -> EffectStarted` before an adapter may cross the external boundary. Once that marker commits, cancellation and expiry can never refund the reservation. Settlement is accepted only from `EffectStarted` or `Quarantined`; indeterminate outcomes remain fully reserved until terminal reconciliation.

## Durable state

Evidence migrations 0009/0010 retain signed replay/outbox state. Migration 0011 adds:

- `authbus_policy_heads` and immutable revision rules;
- `authbus_quota_registry` using fixed-width integer counters plus immutable unit and explicit non-overlapping window start/end;
- `authbus_quota_reservations` with immutable principal/action/scope/quota/effect binding and active/effect-started/settled/cancelled/expired/quarantined states;
- database triggers that reject reservation identity drift, illegal state transitions and deletion of held reservations.

Migration 0012 adds restore-checkpoint bindings and replay-epoch tombstones. First enrollment is an explicit provisioning operation through `initialize_authbus_restore_checkpoint`; Agentd has no authority to initialize a missing checkpoint row. Normal startup is verify-only and requires a separate `--authbus-restore-checkpoint generation:digest` host witness whenever AuthBus trust is enabled. The witness must live outside the Agent-home SQLite backup lineage, so a deleted/pre-checkpoint database and a real old SQLite restore both fail closed instead of being silently reinitialized. Replay-key retirement verifies the current checkpoint inside the same `BEGIN IMMEDIATE` transaction as active-outbox inspection, tombstone creation and replay deletion; conflicting tombstone reuse fails.

## Accounting invariants

Quota arithmetic is integer-only. For each quota key:

`reserved + consumed <= endowment`

Active, EffectStarted and Quarantined reservations contribute to `reserved`; settled observed cost contributes to `consumed`; cancelled and expired reservations contribute to neither. Reconciliation is scoped to the current quota revision/window and fails closed if a held reservation crosses revisions or if the endowment invariant is violated. A quota revision cannot advance while any amount remains held; a new window cannot overlap its predecessor.

## Trust and key lifecycle

Agentd trust remains owner-controlled and fail-closed. The trust file now supports the current key epoch plus at most four previous epochs, each with independent revocation and optional validity windows. This permits bounded overlap during key rotation so already-enqueued messages do not become orphaned merely because the current epoch advanced. Every admission, claim, renewal and acknowledgement still resolves a fresh trusted registration.

## Product composition

The narrow Agentd signed-text path remains the authentication/delivery caller. In addition, `hepta-bao-adapter::BaoClient::consume_kv_v2_with_authbus` computes the complete existing `FinalUseBinding`, derives its exact AuthBus effect digest, requires matching subject/action/scope semantics, commits `EffectStarted`, and only then enters the final-use/HTTPS path. Invalid request syntax can cancel while still Active; after EffectStarted, authority/transport/timeout/consumer-indeterminate failures are held or quarantined rather than refunded. Definitive provider observations settle one quota unit. This candidate still requires exact-head product qualification and independent review before production composition is claimed.

## Verification

Native evidence tests now include the target BUS cases:

- BUS-01: two independent handles cannot both reserve the final quota unit;
- BUS-02: duplicate settlement is idempotent and altered settlement conflicts;
- BUS-03: once EffectStarted is durable, expiry cannot refund even when wall-clock expiry races terminal settlement;
- BUS-04: policy revocation blocks effect-start and subsequent reservations.

Additional tests cover full semantic/idempotency binding, owner-clock expiry, quota-window rollover, SQLite fail-closed triggers, crash/settlement-store failure after EffectStarted, Bao request-binding drift, timeout quarantine and quarantine-to-settlement reconciliation. Recovery qualification restores an actual older SQLite image and verifies it fails against the newer external checkpoint witness, and replay-epoch retirement tests retain tombstones. The Lane A native qualification script now includes the P1.3 qualification crate and the real `hepta-agentd/tests/authbus_text_product.rs` process test.

The qualification crate requires execution provenance containing source SHA, source tree, binary digest, runner identity, command digest and a zero exit code; these fields are bound into the qualification digest.

## Remaining non-claims

This candidate still requires exact-head and synthetic-merge CI success, independent semantic/security review, target-host measurements, operator acceptance and production enrollment. No source change self-grants activation, promotion or release. Exactly-once external effects are not claimed; effect consumers must retain idempotency and reconciliation.
