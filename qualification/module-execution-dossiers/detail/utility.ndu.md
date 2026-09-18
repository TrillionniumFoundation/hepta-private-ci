# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: deterministic source candidate, policy-bound evaluator, protocol adapter and owner-local durability reference implemented; production writer, independent convergence decision and activation remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations but has no effect, capability, selection, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

## 2. Native operations and contract details

Implemented operations include:

```text
evaluate_candidates_with_policy(set, profile, scalarization, policy)
compatibility_evaluation_policy(profile)
canonical_evaluation_policy_digest(profile, policy)
solve_preference_target(initial, target, eta)
solve_preference_target_with_context_digest(initial, target, eta, context_digest)
canonical_iteration_context_digest(context)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
solve_backward_regression(conditional_moments, covariance_profile)
convert_q32_to_q24(values, profile and units digests)
admit_stochastic_profile_v1(evidence, covariance_profile)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen}
NduDurableProjectionJournalV1::{create, recover, append_projection, select_projection, revoke_projection}
```

The legacy evaluator entrypoint is removed. The former semantics remain available only as the explicit `compatibility_evaluation_policy` (`legacy-sum-max-zero-tolerance-v1`) supplied to `evaluate_candidates_with_policy`. `UtilityProfile` digest v2 additionally binds axis/unit/scale registry and normalization manifests. New integrations use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`, whose digest binds utility, risk, resource and uncertainty aggregation plus per-axis Pareto tolerance.

## 3. State, receipts and authority separation

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` are local deterministic solver evidence. The termination receipt records both terminal residual and the true maximum residual observed across iterations.

They are deliberately not named `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and additionally requires independent evaluator identity, conservation, stability and spectral-radius evidence. A local solver cannot certify itself for activation.

`canonical_iteration_context_digest` is computed before protocol-bound solving and copied into each local receipt. `bind_solver_iteration_receipt_v1` rejects zero/unbound or differently bound context before publication, preventing a local step from being rebound to another subject/objective/generation/event/coefficient tuple. The output carries `AuthorityPosture::DENY_ALL`.

`NduProjectionJournalV1` remains a bounded in-memory/reference journal. Revocation lookup is now scoped by objective + subject + payload. `NduDurableProjectionJournalV1` is a source-implemented writer candidate using a host-authorized locked regular file, fixed canonical frames, write + `sync_all` before memory publication, poison-on-indeterminate-I/O recovery and an independently retained chain anchor that detects wholesale self-consistent rewrites. Host selection, containing-directory durability, schema migration, retention and backup/restore evidence remain separate.

## 4. Aggregation, Pareto and solver semantics

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with one of:

- `Sum`;
- `Maximum`;
- `Minimum`;
- `RequireEqual`.

Every utility, risk, resource and uncertainty axis has exactly one rule. Unexpected axes and missing rules reject. `RequireEqual` detects inconsistent owner values instead of selecting one silently.

Pareto dominance uses registered direction and non-negative absolute tolerance for every utility axis. A candidate is strictly better only beyond the tolerance on at least one axis and not worse beyond tolerance on all others. The tolerance vector and aggregation rules are in the evaluation-policy digest.

The deterministic preference solver uses Q32 nearest/ties-even arithmetic, eta in `[1/16,1/4]`, at most 64 iterations, bounded projection and immutable revision advancement. Parent and child hierarchy levels cannot select new artifacts in the same generation.

The stochastic shadow kernel solves `Z C = B` with centered conditional moments and an admitted covariance convention. Singular or ill-conditioned pilot covariance rejects. This numeric kernel is not a production stochastic policy or efficacy claim.

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

Tests and symbols are recorded in the implementation map. They establish source behavior only, not a production caller, longitudinal utility gain or independent activation certificate.

## 7. Integration, rollback and capability ceiling

Control runtime consumes an opaque NDU evaluation digest plus the complete evaluated/rejected/Pareto/advisory projection through a typed, deny-all owner port. It does not link to or reimplement NDU selection. Learning ledger and learning evaluation consume iteration/evaluation evidence under their own writer and independence rules.

Fallback uses a compatible, selected, non-revoked deterministic predecessor, then a frozen objective baseline or abstain. A revoked projection cannot be restored from an old journal or backup. Rollback is a fresh governed transition, not replay of old authority.

This candidate grants no model, tool, network, filesystem, secret, Matrix, fleet, effect, acceptance, merge, promotion or release authority. Production persistence, exact-head qualification, independent `learning.eval` decision, activation and release remain external to the algorithm kernel.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_candidates_with_policy` in [codex-rs/hepta-ndu/src/evaluator.rs](../../../codex-rs/hepta-ndu/src/evaluator.rs); `estimate_conditional_moments` in [codex-rs/hepta-ndu/src/conditional_moments.rs](../../../codex-rs/hepta-ndu/src/conditional_moments.rs); `solve_backward_regression` in [codex-rs/hepta-ndu/src/covariance.rs](../../../codex-rs/hepta-ndu/src/covariance.rs). Policy-bound utility evaluation and centered conditional covariance solver implemented.
- **State and recovery:** The deterministic Q32 evaluator and native f64 shadow regression are distinct profiles. Regression solves centered Z Sigma = B (rate convention Z Q = B/dt) using scaled Cholesky and bounded diagnostics. Projection journal bytes are an owner-local reference, not activated production storage.
- **Source tests:** [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs), [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs), [codex-rs/hepta-ndu/src/projection_journal_tests.rs](../../../codex-rs/hepta-ndu/src/projection_journal_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md), [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../../docs/readiness/NDU_SYSTEM_EXECUTION.md).
- **Remaining work:** Coordinate/Q24 conversion evidence, stochastic profile admission and independent convergence certificate issuance/validation are source-implemented. Remaining evidence gates are real conditional identification and well-posedness evidence, named-host durable-writer selection plus directory/migration/retention/backup qualification, exact-head/synthetic-merge qualification, external wire admission where required, and activation/release.
