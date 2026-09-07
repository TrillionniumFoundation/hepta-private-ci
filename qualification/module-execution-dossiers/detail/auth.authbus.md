# auth.authbus: implementation design

Parent: `docs/modules/auth.authbus/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-authbus`, `codex-rs/hepta-authbus-p1-3-qualification`.
Packages: `AUTHBUS-P1.3-V12`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
