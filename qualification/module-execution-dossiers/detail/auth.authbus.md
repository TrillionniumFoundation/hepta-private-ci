# auth.authbus: implementation design

Parent: `docs/modules/auth.authbus/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: signed message admission and evidence-owner durable replay/delivery implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** signed authentication in [authbus/src/signed.rs](../../../codex-rs/hepta-authbus/src/signed.rs); durable replay admission/delivery in [evidence authbus_store/outbox](../../../codex-rs/hepta-evidence/src/authbus_store.rs); and current-revision exact-scope policy evaluation through `AuthPolicyStore` in [authbus/src/policy.rs](../../../codex-rs/hepta-authbus/src/policy.rs).
- **Policy state and recovery:** policy revisions/rules are immutable in `hepta_auth_policy_1.sqlite`; complete revisions are digest-bound, activated monotonically, and authorization requires the caller's expected current revision. Missing exact principal/action/resource rules deny. Reopen checks migration identity, policy digests, immutable-rule triggers and current-pointer rollback.
- **Replay/delivery state:** signed admission/delivery retain the evidence SQLite replay high-water and fenced outbox leases. Delivery acknowledgement is not effect terminality.
- **Authority ceiling:** an authenticated message and an allowed `PolicyDecisionV1` establish identity/policy facts only. They do not mint or replace `kernel.authority` final-use authority.
- **Source tests:** [signed_tests.rs](../../../codex-rs/hepta-authbus/src/signed_tests.rs), [policy_tests.rs](../../../codex-rs/hepta-authbus/src/policy_tests.rs), evidence [authbus_store_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_store_tests.rs), and [authbus_outbox_tests.rs](../../../codex-rs/hepta-evidence/src/authbus_outbox_tests.rs). These remain source identities until current workflow receipts are green.
- **Remaining work:** compose issuer trust + durable replay + policy decisions into a named product caller; implement quota registry/reserve/settle; retain final-use authority at the actual effect boundary; and provide external rollback/trusted-time evidence. Production activation and independent acceptance remain false.
