# `auth.authbus` current implementation

## Current executable contract

The current candidate has two deliberately separated surfaces.

The signed-admission surface verifies issuer-bound Ed25519 messages, consumes durable replay state in the canonical EvidenceStore, and supports fenced durable delivery. Successful admission still grants no effect authority; `VerificationReceipt` remains `AuthorityPosture::DENY_ALL`.

The control surface adds versioned authorization policy, integer quota accounting, reservation/final-use validation and observed-cost settlement in the same EvidenceStore lineage. `authorize_and_reserve_authbus` evaluates the current non-revoked policy revision and reserves quota inside one `BEGIN IMMEDIATE` transaction. `validate_authbus_reservation_for_effect` rechecks policy revocation/revision and reservation expiry immediately before an adapter crosses an effect boundary. Settlement is allowed from active or quarantined reservations only when terminal evidence is non-empty; cancellation/expiry release reserved quota, while quarantine holds it until observed settlement or explicit reconciliation.

## Durable state

Evidence migrations 0009/0010 retain signed replay/outbox state. Migration 0011 adds:

- `authbus_policy_heads` and immutable revision rules;
- `authbus_quota_registry` using fixed-width integer counters;
- `authbus_quota_reservations` with active/settled/cancelled/expired/quarantined states.

Migration 0012 adds independently checked restore-checkpoint bindings and replay-epoch tombstones. The host must retain the checkpoint generation/digest outside the SQLite backup lineage. Restoring an older database while presenting the newer external checkpoint fails closed. Replay-key retirement is permitted only after external checkpoint verification and after all active outbox rows for the issuer/epoch are gone; a tombstone remains so pruning cannot reopen replay.

## Accounting invariants

Quota arithmetic is integer-only. For each quota key:

`reserved + consumed <= endowment`

Active and quarantined reservations contribute to `reserved`; settled observed cost contributes to `consumed`; cancelled and expired reservations contribute to neither. `reconcile_authbus_quota` recomputes the derived counters from durable reservations and fails closed if the resulting state violates the endowment.

## Trust and key lifecycle

Agentd trust remains owner-controlled and fail-closed. The trust file now supports the current key epoch plus at most four previous epochs, each with independent revocation and optional validity windows. This permits bounded overlap during key rotation so already-enqueued messages do not become orphaned merely because the current epoch advanced. Every admission, claim, renewal and acknowledgement still resolves a fresh trusted registration.

## Product composition

The narrow Agentd signed-text path remains the authentication/delivery caller. In addition, `hepta-bao-adapter::BaoClient::consume_kv_v2_with_authbus` is a source-candidate effect composition: it revalidates a reservation immediately before the HTTPS/final-use boundary; pre-boundary failures cancel, definitive provider observations settle one quota unit, and timeout/transport/consumer-indeterminate outcomes quarantine without automatic effect retry. This candidate still requires exact-head product qualification and independent review before it can establish production composition.

## Verification

Native evidence tests now include the target BUS cases:

- BUS-01: two independent handles cannot both reserve the final quota unit;
- BUS-02: duplicate settlement is idempotent and altered settlement conflicts;
- BUS-03: expiry racing terminal settlement leaves one terminal transition and reconciles conservation;
- BUS-04: policy revocation blocks final-use validation and subsequent reservations.

Additional recovery tests cover external-checkpoint mismatch and replay-epoch retirement tombstones. The Lane A native qualification script now includes the P1.3 qualification crate and the real `hepta-agentd/tests/authbus_text_product.rs` process test.

The qualification crate requires execution provenance containing source SHA, source tree, binary digest, runner identity, command digest and a zero exit code; these fields are bound into the qualification digest.

## Remaining non-claims

This candidate still requires exact-head and synthetic-merge CI success, independent semantic/security review, target-host measurements, operator acceptance and production enrollment. No source change self-grants activation, promotion or release. Exactly-once external effects are not claimed; effect consumers must retain idempotency and reconciliation.
