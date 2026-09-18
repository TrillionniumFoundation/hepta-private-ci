# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: deterministic source candidate, policy-bound evaluator, context-bound preference solver/protocol adapter, stochastic evidence admission and owner-local checkpointable durability reference implemented; source-level read-only callers are composed, while the production writer, independently issued convergence decision and activation remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations but has no effect, capability, selection, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

## 2. Native operations and contract details

Implemented operations include:

```text
evaluate_candidates(set, profile, scalarization)
evaluate_candidates_with_policy(set, profile, scalarization, policy)
canonical_evaluation_policy_digest(profile, policy)
solve_preference_target(initial, target, eta)  # deprecated local/unbound compatibility
solve_preference_target_with_context(initial, target, eta, context_digest)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
solve_backward_regression(conditional_moments, covariance_profile)
admit_stochastic_evidence_binding_v1(binding, covariance_profile, objective_class, now)
solve_backward_regression_with_admission(moments, covariance_profile, admission, now)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen, checkpoint}
```

The legacy evaluator is retained as a compatibility entry with an explicit `legacy-sum-max-zero-tolerance-v1` policy. New integrations use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`, whose digest binds utility, risk, resource and uncertainty aggregation plus per-axis Pareto tolerance.

## 3. State, receipts and authority separation

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` are local deterministic solver evidence. The termination receipt records both terminal residual and the true maximum residual observed across iterations.

They are deliberately not named `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and additionally requires independent evaluator identity, conservation, stability and spectral-radius evidence. A local solver cannot certify itself for activation.

`solve_preference_target_with_context` receives the canonical subject/objective/generation/event/coefficient context digest before iteration and copies it into every local solver receipt. `bind_solver_iteration_receipt_v1` recomputes the canonical context digest and rejects unbound or rebound receipts before publishing an owner-local protocol representation. The output carries `AuthorityPosture::DENY_ALL`.

The legacy `solve_preference_target` remains a deprecated local-diagnostic compatibility entry and deliberately emits unbound receipts that cannot cross the protocol publication boundary. Preference vectors are 1–64 dimensions with values in `[-1,1]`; an already-converged request is a zero-iteration no-op, and the canonical context-bound entry reports the 64-iteration bound as unavailable rather than returning a successful new state.

`NduProjectionJournalV1` is a bounded durability reference, not a production writer. It provides append-only hash-chain entries, semantic idempotency, selected-projection reconstruction, exact reopen, truncation/tamper detection and revocation non-resurrection. Revocations are scoped by objective + subject + payload digest. `checkpoint` binds record count and current hash-chain head for external trusted signing/anchoring. Production composition still requires a selected store, migration, atomic publication, fsync profile, retention, backup/restore and trusted anchor evidence.

## 4. Aggregation, Pareto and solver semantics

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with one of:

- `Sum`;
- `Maximum`;
- `Minimum`;
- `RequireEqual`.

Every utility, risk, resource and uncertainty axis has exactly one rule. Unexpected axes and missing rules reject. `RequireEqual` detects inconsistent owner values instead of selecting one silently.

Pareto dominance uses registered direction and non-negative absolute tolerance for every utility axis. A candidate is strictly better only beyond the tolerance on at least one axis and not worse beyond tolerance on all others. The tolerance vector and aggregation rules are in the evaluation-policy digest.

The deterministic preference solver uses Q32 nearest/ties-even arithmetic, eta in `[1/16,1/4]`, at most 64 iterations, bounded projection and immutable revision advancement only when a state change is needed. Hierarchy validation carries explicit subject and parent IDs; direct system→domain→agent→episode parent/child updates cannot share a generation, while unrelated subjects are not rejected merely because their classes differ.

The stochastic shadow kernel solves `Z C = B` with centered conditional moments and an admitted covariance convention. Singular or ill-conditioned pilot covariance rejects. The owner-local stochastic admission additionally binds coefficient manifest, normalization/runtime/conditioning, Q24 conversion, conditional-identification, well-posedness, independent convergence, rollback, objective-class, expiry and covariance-profile digests before the bound regression entry can be used. This remains evidence binding, not evidence authentication, artifact selection, a production stochastic policy or an efficacy claim.

## 5. Capacity and performance profile

Pilot ceilings remain preference dimension 64, utility dimension 8, risk/resource dimension 32, hierarchy depth 4, candidates 128, contributions 4096 and solver iterations 64. Projection and decision journals are bounded to 4096 records per file.

Runtime cost is deterministic and bounded by the declared dimensions. Dense covariance work stays on a bounded slow path. p95/p99 and persistent-state targets remain design targets until measured on a named host with exact source, compiler, build profile and fixture.

## 6. Concrete verification cases

- `NDU-DETAIL-01`: scaled covariance `C=2dt` with true `Z=3` recovers 3, not 6.
- `NDU-DETAIL-02`: correlated covariance recovers the analytic vector; singular covariance rejects.
- `NDU-DETAIL-03`: higher utility with a hard privacy breach is filtered before Pareto analysis.
- `NDU-DETAIL-04`: simultaneous parent/child artifact update rejects.
- `NDU-DETAIL-05`: axis-specific maximum aggregation differs from implicit summation and is digest-bound.
- `NDU-DETAIL-06`: `RequireEqual` rejects conflicting owner values.
- `NDU-DETAIL-07`: Pareto tolerance changes the frontier and changes the policy digest.
- `NDU-DETAIL-08`: local solver termination records terminal and maximum residual separately.
- `NDU-DETAIL-09`: protocol publication requires complete objective/subject/event/coefficient context.
- `NDU-DETAIL-10`: projection journal reopens exactly; tampering, truncation and revoked-projection resurrection reject.
- `NDU-DETAIL-11`: preference dimensions/values reject outside 1–64 and [-1,1]; already-converged state is a zero-iteration no-op.
- `NDU-DETAIL-12`: canonical solver exhaustion is unavailable rather than a successful state transition.
- `NDU-DETAIL-13`: local receipts cannot be rebound to another canonical subject/objective/generation context.
- `NDU-DETAIL-14`: equal projection payload digests in different objective/subject scopes revoke independently and checkpoint identity survives reopen.
- `NDU-DETAIL-15`: axis-semantics changes alter utility/evaluation identity; stochastic evidence admission rejects missing, expired or mismatched evidence.

Tests and symbols are recorded in the implementation map. They establish source behavior only, not a production caller, longitudinal utility gain or independent activation certificate.

## 7. Integration, rollback and capability ceiling

Control runtime consumes an opaque NDU evaluation digest plus the complete evaluated/rejected/Pareto/advisory projection through a typed, deny-all owner port. Current source-level callers include `evaluate_prepared_plan_with_ndu` and request-local `plan_observed_context`; the read-only Intelligence vertical also invokes the policy-bound evaluator. These callers execute the owner implementation but do not grant effect, promotion or release authority. Learning ledger and learning evaluation consume iteration/evaluation evidence under their own writer and independence rules.

Fallback uses a compatible, selected, non-revoked deterministic predecessor, then a frozen objective baseline or abstain. A revoked projection cannot be restored from an old journal or backup. Rollback is a fresh governed transition, not replay of old authority.

This candidate grants no model, tool, network, filesystem, secret, Matrix, fleet, effect, acceptance, merge, promotion or release authority. Production persistence, exact-head qualification, independent `learning.eval` decision, activation and release remain external to the algorithm kernel.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_candidates_with_policy` in [codex-rs/hepta-ndu/src/evaluator.rs](../../../codex-rs/hepta-ndu/src/evaluator.rs); `solve_preference_target_with_context` in [codex-rs/hepta-ndu/src/preference.rs](../../../codex-rs/hepta-ndu/src/preference.rs); `bind_solver_iteration_receipt_v1` in [codex-rs/hepta-ndu/src/protocol.rs](../../../codex-rs/hepta-ndu/src/protocol.rs); `estimate_conditional_moments` in [codex-rs/hepta-ndu/src/conditional_moments.rs](../../../codex-rs/hepta-ndu/src/conditional_moments.rs); `solve_backward_regression` in [codex-rs/hepta-ndu/src/covariance.rs](../../../codex-rs/hepta-ndu/src/covariance.rs); and stochastic evidence admission in [codex-rs/hepta-ndu/src/stochastic_admission.rs](../../../codex-rs/hepta-ndu/src/stochastic_admission.rs).
- **Composition:** [codex-rs/hepta-control-plane/src/planner_ndu.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu.rs), [codex-rs/hepta-control-plane/src/planner_context.rs](../../../codex-rs/hepta-control-plane/src/planner_context.rs) and [codex-rs/hepta-intelligence/src/vertical.rs](../../../codex-rs/hepta-intelligence/src/vertical.rs) are source-level read-only consumers of the policy-bound evaluator. This is composition evidence, not activation/release evidence.
- **State and recovery:** The deterministic Q32 evaluator and native f64 shadow regression are distinct profiles. Preference state enforces 1–64 dimensions and [-1,1], context-bound receipts are non-rebindable, and projection revocation is objective/subject scoped. Regression solves centered Z Sigma = B (rate convention Z Q = B/dt) using scaled Cholesky and bounded diagnostics. Projection journal bytes plus checkpoint digest remain an owner-local reference, not activated production storage.
- **Source tests:** [codex-rs/hepta-ndu/src/preference_tests.rs](../../../codex-rs/hepta-ndu/src/preference_tests.rs), [codex-rs/hepta-ndu/src/protocol_tests.rs](../../../codex-rs/hepta-ndu/src/protocol_tests.rs), [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs), [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs), [codex-rs/hepta-ndu/src/projection_journal_tests.rs](../../../codex-rs/hepta-ndu/src/projection_journal_tests.rs) and inline stochastic-admission tests. These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md), [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../../docs/readiness/NDU_SYSTEM_EXECUTION.md).
- **Remaining work:** The repository now contains source-level stochastic evidence binding and `learning.eval` convergence-certificate admission. Remaining production work is canonical external/wire admission, a selected durable writer with migration/fsync/retention/backup qualification, authenticated real coefficient/conversion/identification/well-posedness/convergence evidence, target-host performance qualification, operator acceptance, activation and release.
