# auth.authbus: implementation design

Parent: `docs/modules/auth.authbus/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: signed admission/replay, durable authorization/quota/reservation owner,
external rollback witnesses and the bounded Bao final-use composition are
source-implemented in the current candidate; exact-candidate qualification and
independent activation/acceptance remain separate gates. Common requirements:
`../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-authbus`, `codex-rs/hepta-authbus-p1-3-qualification`.
Packages: `AUTHBUS-P1.3-V12`.

Do not create a second authority or execution spine. The replay store remains
the evidence owner; policy/quota/trust facts remain in the AuthBus authority
owner; final-use authority remains kernel-owned.

## 2. Public operations and contract details

`authorize(principal, action, policy_revision) -> PolicyDecision`;
`reserve(quota_key, amount, operation_id, expected_revision) -> Reservation`;
`cancel(reservation_id, expected_revision)`;
`mark_dispatch_attempted(reservation_id, effect_digest)`;
`settle(signed_terminal_evidence, trusted_time) -> Settlement`.
The owner resolves issuer purpose, epoch, signing key and lifecycle inside
the settlement transaction; caller-provided issuer snapshots are not inputs.
Authorization and reservation never grant provider authority.

## 3. State records and transaction design

`auth_policy` has a current head plus immutable revision history.
`quota_registry` stores exact integer limit/available/reserved/consumed values.
`quota_reservation` binds operation, amount, effect digest, policy
identity/revision/decision digest, expiry, immutable dispatch time and lifecycle. Terminal rows can move
to an immutable archive without permitting operation-ID reuse. Issuer lifecycle
and trusted-time floor are durable owner facts.

Every owner table mutation marks the authority frontier dirty in the same
SQLite commit. The external witness advances by CAS only to the exact
recomputed successor frontier; acknowledgement loss is recoverable.

## 4. Deterministic algorithm and scheduling

Verify signed trusted time; evaluate current policy; atomically reserve; recheck
policy and commit `DispatchAttempted` immediately before the effect boundary;
consume kernel final-use authority; classify the observed result; settle only
with signed terminal evidence. Timeout/transport ambiguity becomes
`Indeterminate` and retains reserved quota. Restart reconciles all
`DispatchAttempted` rows before new issuance.

## 5. Capacity and performance profile

Active reservations are bounded globally at 16,384 and per principal at 1,024.
Terminal history is compacted in bounded batches of at most 1,024 while the
archive preserves idempotency identities. Policy, quota and active issuer
registries are bounded. No floating-point quota arithmetic is used. Target-host
latency, contention, recovery and disk budgets remain measurement gates.

## 6. Concrete verification cases

- BUS-01: simultaneous last-unit reservations cannot both succeed.
- BUS-02: duplicate settlement is idempotent; altered cost conflicts.
- BUS-03: expiry/restart/timeout after dispatch retains quota until signed terminal evidence.
- BUS-04: revoked/stale policy cannot cross the dispatch boundary.
- BUS-05: revocation while awaiting the writer, key rotation, wrong issuer purpose and forged keys cannot settle new results.
- BUS-06: delayed success/no-effect survives uncertainty and reopen; evidence before dispatch is refused.
- BUS-07: concurrent/cross-process writers and alternate witness paths are fenced; failed publication is repaired before new mutation.
- BUS-08: version-4 terminal/archive migration preserves queryability without fabricating dispatch times.
- BUS-09: lock identity loss permanently fences the old handle; a fresh host recovers an unacknowledged local commit using the original operation.
- Restore: an external authority/replay witness newer than a restored database fails closed.
- DB bypass: illegal reservation transitions and deletion of live rows are rejected by SQLite.
- Product path: Bao TLS read binds operation identity, quota reservation, exact final-use tuple and signed terminal settlement.

The source contains focused tests for these cases. Passing exact-head and
synthetic-merge execution receipts are still required before changing the
qualification claim.

## 7. Integration, rollback and capability ceiling

Agentd is the named signed-message product caller. The Bao KV-v2 read adapter is
the bounded source-composed provider path for policy/quota/final-use settlement.
Both remain inactive without independently provisioned trust/checkpoint inputs.

AuthBus binds but does not implement the repository's durable
`kernel.operations` owner. Restoring any AuthBus database requires the matching
external witness; a newer witness with an older database is rollback, not a
recovery opportunity.

## 8. Current native implementation

- **Implemented entrypoints:** `SignedMessage::authenticate`;
  `HeptaEvidenceStore::enqueue_authbus_message`;
  `AuthBusAuthorityHost::{authorize,reserve,cancel_reservation,mark_dispatch_attempted,settle}`;
  `BaoClient::consume_kv_v2_with_authbus`.
- **State and recovery:** replay/outbox state is in the evidence SQLite owner;
  policy/quota/reservation/issuer/trusted-time state is in the AuthBus authority
  SQLite owner. Each has a separate externally retained checkpoint protocol.
  Pre-crash dispatch attempts reconcile to `Indeterminate` before new quota issuance.
- **Source tests:** authbus authority/quota/settlement/recovery tests, evidence
  replay/outbox/recovery tests, Agentd signed-text product tests and Bao HTTPS
  AuthBus product tests.
- **Implementation and operating references:**
  `docs/lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md`,
  `codex-rs/hepta-authbus/SIGNED_ADMISSION.md`,
  `codex-rs/hepta-agentd/AUTHBUS_TEXT.md`.
- **Remaining work:** exact-head and synthetic-merge qualification on the
  unchanged candidate; production-durable `kernel.operations` composition;
  externally operated trust/time/checkpoint provisioning; target-host
  crash/capacity qualification; independent security review and operator
  activation/acceptance. No source change self-grants promotion or release.
