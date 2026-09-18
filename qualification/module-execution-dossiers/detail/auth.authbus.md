# auth.authbus: implementation design

Parent: `docs/modules/auth.authbus/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: signed admission/replay plus the policy/quota/reservation source candidate are implemented through the existing evidence owner; exact-candidate execution and independent/production acceptance remain separately gated in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-authbus`, `codex-rs/hepta-authbus-p1-3-qualification`.
Packages: `AUTHBUS-P1.3-V12`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`authorize(principal, action, policy_revision) -> PolicyDecision`; `reserve(quota_key, amount, operation_id, expected_revision) -> Reservation`; `settle(reservation_id, observed_cost, terminal_evidence) -> Settlement`. Authorization does not itself execute secrets/providers. Quota reservation and eventual settlement use the stable operation identity; cancellation and expiry are explicit transitions.

## 3. State records and transaction design

`auth_policy` binds versioned allowed/denied operations and principal scope. `quota_registry` binds exact units, limit, period and consumed/reserved amounts. `quota_reservation` binds operation, amount, expiry, policy revision, state and settlement digest. Reservation updates conserve available+reserved+consumed under a single-writer transaction; same-ID changed-amount requests conflict.

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

- **Implemented entrypoints:** `authenticate` in [codex-rs/hepta-authbus/src/signed.rs](../../../codex-rs/hepta-authbus/src/signed.rs); `admit_authbus_message` in [codex-rs/hepta-evidence/src/authbus_store.rs](../../../codex-rs/hepta-evidence/src/authbus_store.rs); `enqueue_authbus_message` in [codex-rs/hepta-evidence/src/authbus_outbox.rs](../../../codex-rs/hepta-evidence/src/authbus_outbox.rs); `authorize_authbus` in [codex-rs/hepta-evidence/src/authbus_control_store.rs](../../../codex-rs/hepta-evidence/src/authbus_control_store.rs); `reserve_authbus_quota` in [codex-rs/hepta-evidence/src/authbus_control_store.rs](../../../codex-rs/hepta-evidence/src/authbus_control_store.rs); `settle_authbus_reservation` in [codex-rs/hepta-evidence/src/authbus_control_store.rs](../../../codex-rs/hepta-evidence/src/authbus_control_store.rs); `dispatch_provider_effect_with_authbus_qualification` in [codex-rs/hepta-evidence/src/authbus_effect.rs](../../../codex-rs/hepta-evidence/src/authbus_effect.rs).
- **Authentication and delivery:** `authenticate` in [codex-rs/hepta-authbus/src/signed.rs](../../../codex-rs/hepta-authbus/src/signed.rs), `admit_authbus_message` in [codex-rs/hepta-evidence/src/authbus_store.rs](../../../codex-rs/hepta-evidence/src/authbus_store.rs), and `enqueue_authbus_message` plus fenced outbox recovery in the evidence owner.
- **Policy and quota control source candidate:** [codex-rs/hepta-authbus/src/control.rs](../../../codex-rs/hepta-authbus/src/control.rs) defines typed policy, authorization, quota and reservation semantics. [codex-rs/hepta-evidence/src/authbus_control_store.rs](../../../codex-rs/hepta-evidence/src/authbus_control_store.rs) persists immutable policy revisions, quota conservation and reservation transitions under immediate SQLite transactions.
- **Effect ordering:** [codex-rs/hepta-evidence/src/authbus_effect.rs](../../../codex-rs/hepta-evidence/src/authbus_effect.rs) is a qualification-only composition that rechecks authorization, reserves quota before the provider-effect boundary, holds indeterminate outcomes, and settles Completed only from separate observed-cost evidence.
- **Trust, rollback and replay retirement:** [codex-rs/hepta-evidence/src/authbus_trust_store.rs](../../../codex-rs/hepta-evidence/src/authbus_trust_store.rs) owns managed issuer enrollment/revocation/rotation/retirement, a monotonic local hash-chain checkpoint, external checkpoint comparison, and tombstoned replay-epoch retirement. An independently retained checkpoint is still an external prerequisite; a SQLite backup cannot self-prove freshness.
- **Host composition:** Agentd's restricted signed-text profile loads its owner-controlled allowlist and reconciles issuer/key state against the managed registry at admission and delivery boundaries. It remains a narrow text-to-existing-thread caller, not a general provider/effect dispatcher.
- **Tests:** [codex-rs/hepta-evidence/src/authbus_control_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_control_tests.rs) implements BUS-01 through BUS-04 with real SQLite contention/race/reopen coverage and adds rollback/retirement/effect-ordering cases. Lane A runs the AuthBus qualification crate and records exact-head plus synthetic-merge Agentd product-test execution through `hepta_ci_exec.py`.
- **Remaining gates:** independently governed rollback-checkpoint retention/trusted time, production effect caller enrollment, independent semantic/security review, target-host measurements, operator acceptance, canary, promotion and release. These are not granted by this source change.
