# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: deterministic source candidate, policy-bound evaluator, protocol adapter, semantic projection journal, crash-bounded durable writer candidate and stochastic coordinate/Q24 numerical compatibility surface implemented; production activation, independent convergence decision and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

> Status interpretation: canonical work-package lifecycle labels in the parent guide are delivery-plan facts, not implementation-maturity facts. Current source maturity is recorded by this dossier, `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json` and `docs/readiness/LANE_D_MATURITY.json`. A `planned` package label therefore must not be read as “no source exists”, and `candidate_implemented` must not be read as activation or release.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations but has no effect, capability, selection, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

There are current repository composition callsites in `codex-rs/hepta-control-plane/src/planner_ndu.rs` and `codex-rs/hepta-intelligence/src/vertical.rs`. They establish bounded read-only/planning composition, not authenticated production activation or effect authority.

## 2. Native operations and contract details

Implemented operations include:

```text
evaluate_candidates(set, profile, scalarization)
evaluate_candidates_with_policy(set, profile, scalarization, policy)
canonical_evaluation_policy_digest(profile, policy)
solve_preference_target(initial, target, eta)
validate_staged_updates(updates)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
solve_backward_regression(conditional_moments, covariance_profile)
admit_z_conversion_profile(profile)
convert_z_to_original_q24(z, source_digest, conversion_profile)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen}
NduProjectionStoreV1::{open, append_projection, select_projection, revoke_projection, backup_bytes, restore_backup}
```

The legacy evaluator is retained as a compatibility entry with an explicit `legacy-sum-max-zero-tolerance-v1` policy. New integrations use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`, whose digest binds utility, risk, resource and uncertainty aggregation plus per-axis Pareto tolerance.

## 3. State, receipts and authority separation

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` are local deterministic solver evidence. Successful termination records both terminal residual and the true maximum residual observed across iterations. Exhausting the registered 64-iteration bound returns `NduError::PreferenceSolverUnavailable`; the bounded state at exhaustion is not exposed as a successful terminal state.

They are deliberately not named `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and additionally requires independent evaluator identity, conservation, stability and spectral-radius evidence. A local solver cannot certify itself for activation.

`bind_solver_iteration_receipt_v1` publishes an owner-local canonical-context receipt only after binding subject, objective, body generation, event, coefficient, revision, residual, projection count and state digest. It rejects zero/out-of-range iteration numbers, non-successor revisions, negative residuals, empty state digests and subject identity/class rebinding before publication. The output carries `AuthorityPosture::DENY_ALL`.

`NduProjectionJournalV1` is the bounded semantic/serialization layer. It provides append-only hash-chain entries, semantic idempotency, selected-projection reconstruction, exact reopen, truncation/tamper detection and revocation non-resurrection. Recovery replays the same semantic transition rules as live mutation: a hash-valid selection or revocation that references a projection never recorded for the same objective/subject is rejected. Revocation is scoped by `(objective_digest, subject_digest, projection_digest)`, so identical projection bytes used under another objective/subject are not accidentally revoked across scope boundaries.

`NduProjectionStoreV1` is a crash-bounded durable writer **source candidate**, not an activated production writer. It requires a host-supplied private directory, holds one advisory writer lock, reopens only a valid semantic journal, writes and `sync_all`s a temporary complete image, atomically renames it, synchronizes the parent directory on the Unix qualification profile, discards stale uncommitted temp images under the writer lock, and only advances in-memory state after persistence succeeds. Backup restore is monotonic: the current committed journal must be an exact prefix of the restored journal so an old valid backup cannot remove a later revocation.

If rename may have committed but parent-directory durability cannot be acknowledged, the store reports `Indeterminate` and poisons that open handle. Authoritative reads, backup export, restore and later mutations all fail closed on the poisoned handle; callers must drop/reopen to reconcile the durable journal before proceeding. This prevents a possibly advanced disk image from being followed by writes based on stale in-memory state.

Activation still requires host authentication/enrollment, target-filesystem qualification, non-Unix replace/directory-durability evidence when applicable, retention and encrypted/off-host backup policy, restore drills, monitoring, operator acceptance and governed selection. Source existence alone does not change `productionWriterState`.

## 4. Aggregation, Pareto, solver and stochastic numerical semantics

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with one of:

- `Sum`;
- `Maximum`;
- `Minimum`;
- `RequireEqual`.

Every utility, risk, resource and uncertainty axis has exactly one rule. Unexpected axes and missing rules reject. `RequireEqual` detects inconsistent owner values instead of selecting one silently.

Pareto dominance uses registered direction and non-negative absolute tolerance for every utility axis. A candidate is strictly better only beyond the tolerance on at least one axis and not worse beyond tolerance on all others. The tolerance vector and aggregation rules are in the evaluation-policy digest.

The deterministic preference solver uses Q32 nearest/ties-even arithmetic, eta in `[1/16,1/4]`, at most 64 iterations, bounded projection and immutable revision advancement. Parent/child staging is scoped by an explicit `hierarchy_id`; different hierarchy roots may advance in the same generation, while different subject levels inside one hierarchy may not.

The stochastic shadow kernel solves `Z C = B` with centered conditional moments and an admitted covariance convention. Singular or ill-conditioned pilot covariance rejects. This numeric kernel is not a production stochastic policy or efficacy claim.

The stochastic numerical compatibility surface is separate from covariance estimation. `NduZConversionProfileV1` binds units, dimensions, source coordinates and an optional lower-triangular whitening transform. For `m=L xi`, a head declared in whitened coordinates is converted by solving `Z_m L = Z_xi`; an original-coordinate head passes through unchanged. `convert_z_to_original_q24` then records signed Q24 nearest/ties-to-even values and maximum absolute quantization error in a digest-bound, `DENY_ALL` receipt. This closes coordinate/scale ambiguity in source but does not authenticate a learned coefficient artifact, identify a conditional model or admit a production stochastic consumer.

## 5. Capacity and performance profile

Pilot ceilings remain preference dimension 64, utility dimension 8, risk/resource dimension 32, hierarchy depth 4, candidates 128, contributions 4096 and solver iterations 64. Projection journal/store images are bounded to 4096 records. Z conversion uses the same 32-driver/8-utility envelope as covariance regression.

Runtime cost is deterministic and bounded by the declared dimensions. Dense covariance work stays on a bounded slow path. p95/p99 and persistent-state targets remain design targets until measured on a named host with exact source, compiler, build profile and fixture.

## 6. Concrete verification cases

- `NDU-DETAIL-01`: scaled covariance `C=2dt` with true `Z=3` recovers 3, not 6.
- `NDU-DETAIL-02`: correlated covariance recovers the analytic vector; singular covariance rejects.
- `NDU-DETAIL-03`: higher utility with a hard privacy breach is filtered before Pareto analysis.
- `NDU-DETAIL-04`: simultaneous parent/child artifact update rejects only within the same explicit hierarchy; unrelated roots may advance concurrently.
- `NDU-DETAIL-05`: axis-specific maximum aggregation differs from implicit summation and is digest-bound.
- `NDU-DETAIL-06`: `RequireEqual` rejects conflicting owner values.
- `NDU-DETAIL-07`: Pareto tolerance changes the frontier and changes the policy digest.
- `NDU-DETAIL-08`: registered slow damping that cannot reach residual tolerance in 64 iterations returns unavailable.
- `NDU-DETAIL-09`: protocol publication requires complete objective/subject/event/coefficient context and a structurally valid, subject-bound local solver receipt.
- `NDU-DETAIL-10`: projection journal reopens exactly; tampering, truncation, hash-valid impossible transitions and revoked-projection resurrection reject.
- `NDU-DETAIL-11`: durable writer reopen preserves selected/revoked state, rejects a second live writer and discards a stale uncommitted temporary image.
- `NDU-DETAIL-12`: backup restore validates the complete image and rejects rollback that would remove later committed history such as a revocation.
- `NDU-DETAIL-13`: revocation of one objective/subject does not revoke identical projection bytes under another objective/subject.
- `NDU-DETAIL-14`: an indeterminate durable handle cannot read, export, restore or mutate until it is reopened.
- `NDU-DETAIL-15`: `Z_xi=[5,-3]` with `L=[[2,0],[1,3]]` converts to `Z_m=[3,-1]`, and original-coordinate half-ULP Q24 fixtures use nearest/ties-to-even.

Tests and symbols are recorded in the implementation map. They establish source behavior only, not longitudinal utility gain, target-host durability qualification or independent activation certificate.

## 7. Integration, rollback and capability ceiling

Control runtime consumes an opaque NDU evaluation digest plus the complete evaluated/rejected/Pareto/advisory projection through a typed, deny-all owner port. `planner_ndu` executes the owner implementation before sealing its authority-free planning projection. The Intelligence read-only vertical independently composes objective, cognitive evidence, context and the policy-bound NDU V2 receipt. Neither path creates effect authority or production activation.

Fallback uses a compatible, selected, non-revoked deterministic predecessor, then a frozen objective baseline or abstain. A revoked projection cannot be restored from an old journal or a regressive backup. Rollback is a fresh governed transition, not replay of old authority.

This candidate grants no model, tool, network, filesystem, secret, Matrix, fleet, effect, acceptance, merge, promotion or release authority. Durable writer source now exists, but production writer selection/host composition, exact-head qualification, independent `learning.eval` decision, stochastic coefficient provenance/consumer admission, operator acceptance and release remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_candidates_with_policy` in [codex-rs/hepta-ndu/src/evaluator.rs](../../../codex-rs/hepta-ndu/src/evaluator.rs); `solve_preference_target` and hierarchy-scoped `validate_staged_updates` in [codex-rs/hepta-ndu/src/preference.rs](../../../codex-rs/hepta-ndu/src/preference.rs); `bind_solver_iteration_receipt_v1` in [codex-rs/hepta-ndu/src/protocol.rs](../../../codex-rs/hepta-ndu/src/protocol.rs); `estimate_conditional_moments` in [codex-rs/hepta-ndu/src/conditional_moments.rs](../../../codex-rs/hepta-ndu/src/conditional_moments.rs); `solve_backward_regression` in [codex-rs/hepta-ndu/src/covariance.rs](../../../codex-rs/hepta-ndu/src/covariance.rs); `convert_z_to_original_q24` in [codex-rs/hepta-ndu/src/z_conversion.rs](../../../codex-rs/hepta-ndu/src/z_conversion.rs); `NduProjectionStoreV1` in [codex-rs/hepta-ndu/src/projection_store.rs](../../../codex-rs/hepta-ndu/src/projection_store.rs).
- **State and recovery:** The deterministic Q32 evaluator and native f64 shadow regression are distinct profiles. Regression solves centered `Z Sigma = B` (rate convention `Z Q = B/dt`) using scaled Cholesky and bounded diagnostics. Projection journal recovery validates both hash-chain and transition semantics with scoped revocation. The durable store adds single-writer ownership, synchronized copy-on-mutate persistence, crash-temp cleanup, poison-on-indeterminate behavior, reopen and monotonic backup restore.
- **Stochastic numerical compatibility:** [codex-rs/hepta-ndu/src/z_conversion.rs](../../../codex-rs/hepta-ndu/src/z_conversion.rs) admits original/whitened coordinate conventions, converts `Z_xi` back to `Z_m` through the declared `L`, and emits digest-bound signed-Q24 conversion evidence. It does not authenticate or select a learned coefficient artifact.
- **Current composition:** `codex-rs/hepta-control-plane/src/planner_ndu.rs` and `codex-rs/hepta-intelligence/src/vertical.rs` are concrete repository callsites for policy-bound V2 evaluation. Their current posture is bounded planning/read-only composition rather than authenticated production activation.
- **Source tests:** [codex-rs/hepta-ndu/src/preference_tests.rs](../../../codex-rs/hepta-ndu/src/preference_tests.rs), [codex-rs/hepta-ndu/src/protocol_tests.rs](../../../codex-rs/hepta-ndu/src/protocol_tests.rs), [codex-rs/hepta-ndu/src/covariance_tests.rs](../../../codex-rs/hepta-ndu/src/covariance_tests.rs), [codex-rs/hepta-ndu/src/z_conversion_tests.rs](../../../codex-rs/hepta-ndu/src/z_conversion_tests.rs), [codex-rs/hepta-ndu/src/evaluator_tests.rs](../../../codex-rs/hepta-ndu/src/evaluator_tests.rs), [codex-rs/hepta-ndu/src/projection_journal_tests.rs](../../../codex-rs/hepta-ndu/src/projection_journal_tests.rs), [codex-rs/hepta-ndu/src/projection_store_tests.rs](../../../codex-rs/hepta-ndu/src/projection_store_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Qualification workflow:** `.github/workflows/hepta-ndu-recursion.yml` qualifies PR source heads and deterministic synthetic merges, and now also runs on relevant `main` pushes so the default-branch exact head receives fresh package qualification rather than inheriting a PR result.
- **Remaining repository-controlled work:** compose the durable writer candidate into an authenticated host/owner boundary; bind production consumers to that selected writer and final authentication profile; register and compose a production stochastic coefficient profile/consumer using the now-explicit coordinate/Q24 conversion boundary.
- **Remaining external evidence:** target-host durability/performance, non-Unix filesystem equivalence if selected, conditional identification and longitudinal efficacy, independent FBSDE/convergence qualification, operator acceptance, activation, canary, promotion and release. These cannot be self-issued by `utility.ndu` source or documentation.
