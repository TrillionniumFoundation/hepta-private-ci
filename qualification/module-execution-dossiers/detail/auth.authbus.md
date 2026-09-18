# auth.authbus: implementation design

Parent: `docs/modules/auth.authbus/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: signed message admission and evidence-owner durable replay/delivery implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-authbus`, `codex-rs/hepta-authbus-p1-3-qualification`.
Packages: `AUTHBUS-P1.3-V12`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`authorize(principal, action, policy_revision) -> PolicyDecision`; `reserve(quota_key, quota_revision, amount, operation_id, effect_digest, expiry) -> Reservation`; `begin_effect(reservation, expected_principal, expected_action, expected_scope, expected_effect) -> EffectStarted`; `settle(reservation_id, observed_cost, terminal_evidence) -> Settlement`. Authorization does not itself execute secrets/providers. Reservation persists the complete semantic binding. Cancellation/expiry are legal only before EffectStarted; after that point unknown outcomes remain held/quarantined until reconciliation.

## 3. State records and transaction design

`auth_policy` binds versioned allowed/denied operations and principal scope. `quota_registry` binds an immutable unit, explicit fixed window, limit and consumed/reserved amounts. `quota_reservation` binds operation, principal, action, scope, quota revision, amount, expiry, final-effect digest, state and settlement digest. Reservation updates conserve available+reserved+consumed under a single-writer transaction; any same-operation semantic drift conflicts. SQLite triggers independently enforce binding immutability and legal state transitions.

## 4. Deterministic algorithm and scheduling

Check current policy/revocation, reserve before effect dispatch, then settle only from observed cost/terminal disposition. Expired reservations do not prove an external effect did not occur; indeterminate costs remain held or quarantined under policy. Refunds cannot make total available exceed the configured endowment. Reconcile after crash before accepting new reservations.

## 5. Capacity and performance profile

Pilot reservation request <= 16 KiB, batch <= 128, per-principal active reservation cap fixed by policy. Measure contention, lease expiry backlog, reconciliation time and conservation residual; no floating-point currency or quota arithmetic.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BUS-01: simultaneous last-unit reservations cannot both succeed.
- BUS-02: duplicate settlement is idempotent; altered cost conflicts.
- BUS-03: expiry racing a terminal result preserves accounting and does not double-refund.
- BUS-04: revoked policy and stale reservation cannot authorize a secret effect.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Map existing P1.3 qualification cases to product callers instead of replacing them. Restore must reconcile durable reservations with actual effects and current revocations before reopening issuance.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `authenticate`, `admit_authbus_message`, `enqueue_authbus_message`, `authorize_and_reserve_authbus`, `begin_authbus_effect`, `settle_authbus_reservation`, `pending_authbus_effect_reservations`, `retire_authbus_replay_epoch`, and candidate `consume_kv_v2_with_authbus`.
- **Authentication / admission:** `authenticate` in `codex-rs/hepta-authbus/src/signed.rs`; durable admission and outbox in `codex-rs/hepta-evidence/src/authbus_store.rs` and `authbus_outbox.rs`.
- **Policy and quota candidate:** pure contract types live in `codex-rs/hepta-authbus/src/control.rs`. Durable policy revisions, quota registry, reservations, final-use validation, settlement, cancellation, expiry, quarantine and reconciliation live in `codex-rs/hepta-evidence/src/authbus_control.rs` under migration 0011.
- **Transaction boundary:** `authorize_and_reserve_authbus` evaluates the exact current non-revoked policy revision and reserves integer quota inside one `BEGIN IMMEDIATE` transaction. `begin_authbus_effect` uses the owner clock after acquiring the write lock, revalidates principal/action/scope/effect and policy/quota revisions, then durably commits EffectStarted. Cancel/expiry cannot cross that marker. Settlement binds non-empty terminal evidence and observed cost; queue acknowledgement is not effect terminality.
- **Recovery / rollback candidate:** migration 0012 and `authbus_recovery.rs` bind the SQLite lineage to a separately supplied host restore-checkpoint witness. Agentd requires the witness alongside the trust file. Replay epoch retirement checks the witness, active outbox, tombstone and replay deletion atomically; an actual old-database restore is exercised by the recovery test.
- **Key lifecycle:** Agentd trust supports the current key plus at most four bounded previous epochs with independent revocation and optional validity windows. Admission/dispatch resolve fresh registrations.
- **Qualification:** `hepta-authbus-p1-3-qualification` now requires source SHA, source tree, binary digest, runner identity, command digest and successful exit status, all bound into the qualification digest. Lane A native qualification includes the real Agentd AuthBus product test.
- **Native tests:** `authbus_control_tests.rs` executes BUS-01 through BUS-04 against real SQLite and additionally covers semantic binding drift, owner-clock expiry, quota windows, DB triggers and crash-after-effect-start recovery. `authbus_recovery_tests.rs` restores a real older SQLite image and verifies replay retirement tombstones. Bao tests cover request mismatch, timeout quarantine, consumer-indeterminate reconciliation and successful settlement.
- **Composition limit:** Agentd signed-text is the narrow authentication/delivery caller and Bao has a candidate reservation-aware effect wrapper. This still does not establish production implementation, activation, acceptance or release until exact-candidate CI and external gates close.
