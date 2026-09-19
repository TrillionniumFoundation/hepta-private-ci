# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: deterministic source candidate with named read-only control-plane/intelligence composition, policy-bound evaluator, context-bound solver receipts and owner-local durability reference implemented; production writer, independent convergence decision, exact-candidate qualification and activation remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations but has no effect, capability, selection, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

## 2. Native operations and contract details

Implemented operations include:

```text
evaluate_candidates(set, profile, scalarization)
evaluate_candidates_with_policy(set, profile, scalarization, policy)
canonical_evaluation_policy_digest(profile, policy)
solve_preference_target(initial, target, eta, context)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
solve_backward_regression(conditional_moments, covariance_profile)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen}
```

The legacy evaluator is retained as an explicitly deprecated compatibility entry with an explicit `legacy-sum-max-zero-tolerance-v1` policy. New integrations use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`. `UtilityProfile` additionally carries a non-zero immutable `axis_registry_digest`, so units, scales and normalization semantics are part of the canonical profile/evaluation identity rather than an unenforced `profile_id` convention.

## 3. State, receipts and authority separation

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` are local deterministic solver evidence. A local iteration receipt is only constructed inside the solver and carries the canonical digest of the exact subject/objective/generation/event/coefficient context supplied to that solve. The termination receipt records the same context digest plus terminal and maximum residual evidence.

They are deliberately not named `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and additionally requires independent evaluator identity, conservation, stability and spectral-radius evidence. A local solver cannot certify itself for activation.

`bind_solver_iteration_receipt_v1` recomputes the canonical subject/objective/body-generation/event/coefficient context digest and rejects any solver receipt created under a different context before publishing the owner-local receipt. Rebinding a valid local receipt to another non-zero context therefore fails closed. The output carries `AuthorityPosture::DENY_ALL`.

`NduProjectionJournalV1` is a bounded durability reference, not a production writer. It provides append-only hash-chain entries, semantic idempotency, selected-projection reconstruction, exact reopen, truncation/tamper detection and revocation non-resurrection. Revocation lookup is scoped by `(objective_digest, subject_digest, payload_digest)`, so equal payload digests in unrelated scopes cannot revoke each other. Production composition still requires a selected store, migration, fsync profile, retention, backup/restore and crash-recovery evidence; the local hash chain is not an external authenticity anchor.

## 4. Aggregation, Pareto and solver semantics

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with one of:

- `Sum`;
- `Maximum`;
- `Minimum`;
- `RequireEqual`.

Every utility, risk, resource and uncertainty axis has exactly one rule. Unexpected axes and missing rules reject. `RequireEqual` detects inconsistent owner values instead of selecting one silently.

Pareto dominance uses registered direction and non-negative absolute tolerance for every utility axis. A candidate is strictly better only beyond the tolerance on at least one axis and not worse beyond tolerance on all others. The tolerance vector and aggregation rules are in the evaluation-policy digest.

The deterministic preference solver enforces `dim(P) <= 64` and every admitted preference value in `[-1,1]`, uses Q32 nearest/ties-even arithmetic, eta in `[1/16,1/4]`, and at most 64 iterations. An already-converged state returns the identical state with zero iterations and no revision churn; exhausting the bound returns unavailable rather than a successful terminal state. Staged updates are checked against a digest-bound concrete subject graph, so only actual parent/child updates are excluded from the same generation while unrelated subjects may advance concurrently.

The stochastic shadow kernel solves `Z C = B` with centered conditional moments and an admitted covariance convention. Singular or ill-conditioned pilot covariance rejects. This numeric kernel is not a production stochastic policy or efficacy claim.

## 5. Capacity and performance profile

Pilot ceilings remain preference dimension 64, utility dimension 8, risk/resource dimension 32, hierarchy depth 4, candidates 128, contributions 4096 and solver iterations 64. Projection and decision journals are bounded to 4096 records per file.

Runtime cost is deterministic and bounded by the declared dimensions. Dense covariance work stays on a bounded slow path. p95/p99 and persistent-state targets remain design targets until measured on a named host with exact source, compiler, build profile and fixture.

## 6. Concrete verification cases

- `NDU-DETAIL-01`: scaled covariance `C=2dt` with true `Z=3` recovers 3, not 6.
- `NDU-DETAIL-02`: correlated covariance recovers the analytic vector; singular covariance rejects.
- `NDU-DETAIL-03`: higher utility with a hard privacy breach is filtered before Pareto analysis.
- `NDU-DETAIL-04`: a concrete parent/child artifact update in one generation rejects, while unrelated subjects may share a generation.
- `NDU-DETAIL-05`: axis-specific maximum aggregation differs from implicit summation and is digest-bound.
- `NDU-DETAIL-06`: `RequireEqual` rejects conflicting owner values.
- `NDU-DETAIL-07`: Pareto tolerance changes the frontier and changes the policy digest.
- `NDU-DETAIL-08`: local solver termination records terminal and maximum residual separately.
- `NDU-DETAIL-09`: protocol publication requires complete objective/subject/event/coefficient context and rejects non-zero context rebinding.
- `NDU-DETAIL-10`: projection journal reopens exactly; tampering, truncation and same-scope revoked-projection resurrection reject without cross-scope revocation bleed.
- `NDU-DETAIL-11`: preference genesis/target bounds, no-op idempotency and bounded-exhaustion-unavailable semantics are enforced at the public API boundary.
- `NDU-DETAIL-12`: the immutable axis registry digest changes the utility-profile digest even when `profile_id` is unchanged.

Tests and symbols are recorded in the implementation map. They establish source behavior and source-level read-only composition only, not activated product execution, longitudinal utility gain or an independent activation certificate.

## 7. Integration, rollback and capability ceiling

`hepta-control-plane::evaluate_prepared_plan_with_ndu` and the request-local context planner are named read-only source callers of the policy-bound evaluator; the intelligence read-only vertical is a second named deny-all composition. They consume the NDU evaluation digest plus the complete evaluated/rejected/Pareto/advisory projection and do not turn advisory output into effect authority. Learning ledger and learning evaluation consume iteration/evaluation evidence under their own writer and independence rules.

Fallback uses a compatible, selected, non-revoked deterministic predecessor, then a frozen objective baseline or abstain. A revoked projection cannot be restored from an old journal or backup. Rollback is a fresh governed transition, not replay of old authority.

This candidate grants no model, tool, network, filesystem, secret, Matrix, fleet, effect, acceptance, merge, promotion or release authority. Production persistence, exact-head qualification, independent `learning.eval` decision, activation and release remain external to the algorithm kernel.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_candidates_with_policy` in [codex-rs/hepta-ndu/src/evaluator.rs](../../../codex-rs/hepta-ndu/src/evaluator.rs); `solve_preference_target` in [codex-rs/hepta-ndu/src/preference.rs](../../../codex-rs/hepta-ndu/src/preference.rs); `bind_solver_iteration_receipt_v1` in [codex-rs/hepta-ndu/src/protocol.rs](../../../codex-rs/hepta-ndu/src/protocol.rs); `estimate_conditional_moments` in [codex-rs/hepta-ndu/src/conditional_moments.rs](../../../codex-rs/hepta-ndu/src/conditional_moments.rs); `solve_backward_regression` in [codex-rs/hepta-ndu/src/covariance.rs](../../../codex-rs/hepta-ndu/src/covariance.rs). Named source composition exists in `hepta-control-plane` and the intelligence read-only vertical; this is not activation evidence.
- **State and recovery:** The deterministic Q32 evaluator and native f64 shadow regression are distinct profiles. Regression solves centered Z Sigma = B (rate convention Z Q = B/dt) using scaled Cholesky and bounded diagnostics. Projection journal bytes are an owner-local reference, not activated production storage.
- **Source tests:** [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs), [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs), [codex-rs/hepta-ndu/src/preference_tests.rs](../../../codex-rs/hepta-ndu/src/preference_tests.rs), [codex-rs/hepta-ndu/src/protocol_tests.rs](../../../codex-rs/hepta-ndu/src/protocol_tests.rs), [codex-rs/hepta-ndu/src/projection_journal_tests.rs](../../../codex-rs/hepta-ndu/src/projection_journal_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md), [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../../docs/readiness/NDU_SYSTEM_EXECUTION.md).
- **Remaining work:** The conditional numeric solver is already implemented; remaining work is production coefficient/profile and consumer admission, coordinate/Q24 conversion evidence, conditional identification and independent FBSDE/convergence qualification.
