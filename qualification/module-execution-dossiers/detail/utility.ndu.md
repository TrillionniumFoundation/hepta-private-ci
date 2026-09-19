# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: deterministic source candidate, policy-bound evaluator, context-bound protocol adapter, scoped projection journal, anchored durable-file adapter candidate and Q24 coefficient materialization implemented; the independent convergence decision kernel is implemented by `learning.eval`. Product-composed production writing, authenticated independent evidence, activation and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations but has no effect, capability, selection, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

## 2. Native operations and contract details

Implemented operations include:

```text
evaluate_candidates(set, profile, scalarization)
evaluate_candidates_with_policy(set, profile, scalarization, policy)
canonical_evaluation_policy_digest(profile, policy)
solve_preference_target(initial, target, eta, canonical_context_digest)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
solve_backward_regression(conditional_moments, covariance_profile)
materialize_q24_coefficient_candidate_v1(estimate, covariance_profile, coefficient_manifest_digest, operating_region_digest)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen}
DurableNduProjectionStoreV1::{create, recover, migrate_reference, append_projection, select_projection, revoke_projection, backup, restore_backup}
```

The legacy evaluator is retained as a deprecated compatibility entry with an explicit `legacy-sum-max-zero-tolerance-v1` policy. Lane D semantic CI forbids new callers outside the compatibility definition/tests. New integrations use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`, whose digest binds utility, risk, resource and uncertainty aggregation plus per-axis Pareto tolerance. Utility-profile V2 additionally binds a nonzero immutable axis-registry digest covering units, scales and normalization semantics.

## 3. State, receipts and authority separation

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` are local deterministic solver evidence. The termination receipt records both terminal residual and the true maximum residual observed across iterations.

They are deliberately not named `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and additionally requires independent evaluator identity, conservation, stability and spectral-radius evidence. A local solver cannot certify itself for activation.

Each local solver iteration receipt is created with a crate-sealed canonical context digest. `bind_solver_iteration_receipt_v1` recomputes the digest over subject, class, objective, generation, event and coefficient and rejects rebinding before publishing revision, residual, projection count and state evidence. The output carries `AuthorityPosture::DENY_ALL`.

`NduProjectionJournalV1` is a bounded semantic journal. It provides append-only hash-chain entries, semantic idempotency, selected-projection reconstruction, exact reopen, truncation/tamper detection and revocation non-resurrection; revocations are scoped by objective + subject + payload.

`DurableNduProjectionStoreV1` is an owner-local durable-file candidate using an explicitly supplied regular file, exclusive lock, store binding, `sync_all()` before commit, externally retained current anchors, fail-closed unwitnessed-tail recovery, bounded retention, migration and digest/anchor-bound backup/restore. It does not provide ambient path authority, directory-fsync ownership, product scheduling or authenticated anchor custody, so it is not yet a product-composed production writer.

## 4. Aggregation, Pareto and solver semantics

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with one of:

- `Sum`;
- `Maximum`;
- `Minimum`;
- `RequireEqual`.

Every utility, risk, resource and uncertainty axis has exactly one rule. Unexpected axes and missing rules reject. `RequireEqual` detects inconsistent owner values instead of selecting one silently.

Pareto dominance uses registered direction and non-negative absolute tolerance for every utility axis. A candidate is strictly better only beyond the tolerance on at least one axis and not worse beyond tolerance on all others. The tolerance vector and aggregation rules are in the evaluation-policy digest.

The deterministic preference solver uses Q32 nearest/ties-even arithmetic, enforces at most 64 preference dimensions and values in `[-1,1]`, eta in `[1/16,1/4]`, and at most 64 iterations. Already-converged inputs are zero-iteration revision-preserving no-ops; exhaustion is explicit unavailable and exposes no usable terminal state. Staged updates carry artifact and direct-parent identities, so only an actual same-generation parent/child pair conflicts; unrelated subjects are not rejected merely because their classes differ.

The stochastic shadow kernel solves `Z C = B` with centered conditional moments and an admitted covariance convention. Singular or ill-conditioned pilot covariance rejects. Solver output is sealed to the admitted profile; Q24 materialization uses signed nearest/ties-even conversion, rejects overflow, binds units/profile/manifest/operating-region provenance and reports a conservative conversion-error bound. This numeric path is still not a learned/identified production stochastic policy or efficacy claim.

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
- `NDU-DETAIL-11`: preference dimension/range violations reject; already-converged solve preserves revision; exhaustion is unavailable.
- `NDU-DETAIL-12`: solver receipt objective/subject/generation rebinding rejects.
- `NDU-DETAIL-13`: equal payload digests in different objective/subject scopes have independent revocation state.
- `NDU-DETAIL-14`: durable store recovery requires a current external anchor; unwitnessed complete tails reject; anchored incomplete crash tails repair deterministically; backup/restore is digest-bound.
- `NDU-DETAIL-15`: Q24 coefficient half ties round to even, profile rebinding and conversion overflow reject.

Tests and symbols are recorded in the implementation map. They establish source behavior only, not a production caller, longitudinal utility gain or independent activation certificate.

## 7. Integration, rollback and capability ceiling

Control runtime consumes an opaque NDU evaluation digest plus the complete evaluated/rejected/Pareto/advisory projection through a typed, deny-all owner port. It does not link to or reimplement NDU selection. Learning ledger and learning evaluation consume iteration/evaluation evidence under their own writer and independence rules.

Fallback uses a compatible, selected, non-revoked deterministic predecessor, then a frozen objective baseline or abstain. A revoked projection cannot be restored from an old journal or backup. Rollback is a fresh governed transition, not replay of old authority.

This candidate grants no model, tool, network, ambient-filesystem, secret, Matrix, fleet, effect, acceptance, merge, promotion or release authority. A durable local file adapter and an independent `learning.eval` decision kernel now exist in source, but product store binding, authenticated independent evidence, exact-head qualification, activation and release remain outside the algorithm kernel.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_candidates_with_policy` in [codex-rs/hepta-ndu/src/evaluator.rs](../../../codex-rs/hepta-ndu/src/evaluator.rs); preference/context binding in [codex-rs/hepta-ndu/src/preference.rs](../../../codex-rs/hepta-ndu/src/preference.rs) and [codex-rs/hepta-ndu/src/protocol.rs](../../../codex-rs/hepta-ndu/src/protocol.rs); `estimate_conditional_moments` and `solve_backward_regression`; Q24 materialization in [codex-rs/hepta-ndu/src/coefficient_candidate.rs](../../../codex-rs/hepta-ndu/src/coefficient_candidate.rs); journal/durable store in [codex-rs/hepta-ndu/src/projection_journal.rs](../../../codex-rs/hepta-ndu/src/projection_journal.rs) and [codex-rs/hepta-ndu/src/durable_projection_store.rs](../../../codex-rs/hepta-ndu/src/durable_projection_store.rs).
- **State and recovery:** The deterministic Q32 evaluator and native f64 shadow regression are distinct profiles. Regression solves centered Z Sigma = B (rate convention Z Q = B/dt) using scaled Cholesky and bounded diagnostics. The durable adapter adds locked/synced file recovery, external-anchor checks, retention and backup/restore without claiming product composition.
- **Source tests:** [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs), [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs), [codex-rs/hepta-ndu/src/projection_journal_tests.rs](../../../codex-rs/hepta-ndu/src/projection_journal_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md](../../../codex-rs/hepta-ndu/COVARIANCE_REGRESSION.md), [docs/readiness/NDU_SYSTEM_EXECUTION.md](../../../docs/readiness/NDU_SYSTEM_EXECUTION.md).
- **Remaining work:** Coordinate/Q24 conversion evidence and the repository-owned independent convergence decision kernel are now source-implemented. Remaining work is typed production coefficient-manifest provenance/admission and consumer composition, learned conditional identification, real future-window/stability evidence, product binding of the durable store, target-host qualification and independent acceptance/activation.
