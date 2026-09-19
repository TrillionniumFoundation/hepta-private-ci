# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: policy-bound source composition, bounded preference/utility kernels, context-bound solver evidence, anchored durable projection-writer candidate and externally verified FBSDE-regression admission are implemented. Independent convergence acceptance, named product composition of the durable writer, target-host qualification, activation and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/NDU_SYSTEM_EXECUTION.md` and `docs/learning/NDU_FBSDE_SPEC.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-ndu`. Owner-local source package: `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION`. Protocol and Control integration boundaries are split by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact source/test mappings are in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`.

The module owns utility and preference calculations and its projection state. It has no effect, capability, final selection, acceptance, promotion or release authority. Only system, domain, agent and episode are valid NDU subjects.

Source-level callers now exist in the Control planning path and read-only intelligence vertical. That is composition evidence, not activation evidence: the product caller still cannot turn a deny-all NDU receipt into effect authority.

## 2. Native operations and contract details

Public source operations include:

```text
evaluate_candidates_with_policy(set, profile, scalarization, policy)
canonical_evaluation_policy_digest(profile, policy)
canonical_utility_profile_digest(profile)
solve_preference_target(initial, target, eta, iteration_context)
ndu_iteration_context_digest_v1(context)
bind_solver_iteration_receipt_v1(context, local_step)
evaluate_recursive_utility(path)
estimate_conditional_moments(samples, source, covariance_profile)
solve_backward_regression(conditional_moments, covariance_profile)
admit_fbsde_evidence_v1(evidence, covariance_profile, external_verifier)
solve_qualified_backward_regression_v1(moments, covariance_profile, admitted_evidence)
NduProjectionJournalV1::{append_projection, select_projection, revoke_projection, reopen}
NduProjectionDurableJournalV1::{create, recover, restore_checkpoint,
  migrate_authenticated_reference_snapshot, append_projection,
  select_projection, revoke_projection, checkpoint}
```

The old `evaluate_candidates` and `legacy_evaluation_policy` compatibility helpers are crate-local only. Repository product/qualification callers use `EvaluationPolicyV1` and `NduEvaluationReceiptV2`. CI rejects new external callers that reintroduce either legacy symbol.

`UtilityProfile` explicitly binds an immutable `normalization_manifest_digest`; canonical profile/evaluation digests therefore change if units, scales, normalization or clipping semantics change even when a human-readable profile ID is reused.

## 3. Preference state, receipts and authority separation

Preference vectors are admitted at the public API boundary: dimension is at most 64 and every value must be in the closed interval `[-1,1]`. A target outside that interval is invalid input, not a request that may be silently clamped toward a boundary.

`solve_preference_target` receives the full `NduIterationContextV1`. It verifies subject identity/class before solving and computes a canonical context digest covering subject, objective, generation, event and coefficient identities. Local iteration-receipt fields are crate-private and carry that context digest from creation time. `bind_solver_iteration_receipt_v1` recomputes the digest and rejects cross-context rebinding.

An already-converged state is a zero-iteration no-op: revision and state digest remain unchanged. A bounded solve that still exceeds the residual tolerance after 64 iterations returns `PreferenceSolveOutcome::Unavailable`; it does not expose an unconverged `PreferenceState` as a persistable success value.

`NduSolverIterationReceipt` and `NduSolverTerminationReceipt` remain local numerical evidence. They are deliberately not `NduConvergenceCertificateV1`. That canonical certificate remains owned by `learning.eval` and requires an independent evaluator plus its registered stability/conservation evidence.

## 4. Hierarchy, aggregation and Pareto semantics

Hierarchy staging uses explicit artifact lineage. `UpdateGeneration` carries `artifact_id` and optional `parent_artifact_id`; same-generation rejection applies only when a staged child actually names another staged node as its parent. Unrelated Domain/Agent updates are not rejected merely because their enum classes differ, and malformed direct-parent relations fail closed.

Hard feasibility is applied before utility arithmetic. Every candidate includes abstain. Missing required organ support, objective/generation mismatch, missing axis or empty support digest rejects rather than contributing zero.

Aggregation is versioned per axis with `Sum`, `Maximum`, `Minimum` or `RequireEqual`. Every utility, risk, resource and uncertainty axis has exactly one rule. Pareto dominance uses registered direction and non-negative absolute tolerance; tolerance and aggregation rules are in the policy digest. Scalarization remains optional and fully digest-bound.

## 5. Projection durability and recovery

`NduProjectionJournalV1` remains the pure semantic reducer. Revocation lookup is scoped by the full `(objective_digest, subject_digest, payload_digest)` tuple, so revoking identical payload bytes in one subject/objective cannot revoke another scope.

`NduProjectionDurableJournalV1` is the durable owner candidate around that reducer:

- acquires a crash-released exclusive OS file lock;
- binds the file to a nonzero owner/binding digest and a versioned durable header;
- bounds retained records by the configured limit and the module ceiling of 4096;
- writes exactly one canonical record, `sync_all`s it, then requires an external anti-rollback compare-and-set before publishing the mutation in memory;
- poisons the live writer on ambiguous anchor failure so callers must reopen/reconcile rather than retry physical append;
- recovery trusts the external anchor, validates the acknowledged hash-chain prefix and truncates any complete or partial unwitnessed tail;
- checkpoints contain byte-exact durable state plus binding and acknowledged anchor;
- restore refuses a stale checkpoint unless the independently retained anchor still matches it;
- migration from `NduProjectionJournalV1` bytes is allowed only when an external anchor already authenticates that exact chain head.

The anchor store is intentionally not implemented inside NDU. Its trust, persistence, revocation and rollback domain must be owned outside the projection file. File-path creation and containing-directory durability are also host responsibilities. Therefore this is a production-writer **source candidate**, not an activated writer.

## 6. Conditional covariance and qualified FBSDE regression boundary

The native numerical kernel estimates centered conditional moments and solves `Z Sigma = B` (or `Z Q = B/dt`) with scaled Cholesky. Driver dimension is 1–32, utility dimension 1–8 and sample count 2–512; singular, ill-conditioned, non-finite, out-of-bound and high-residual inputs fail closed.

`admit_fbsde_evidence_v1` adds the missing evidence-consumption boundary. An embedding-supplied verifier must approve a bundle that binds coefficient artifact/profile, source dataset, conditioning stratum, conditional-identification evidence, coordinate manifest, Q24 conversion profile, consumer admission and independent qualification. The admitted object is opaque and bound to the exact covariance profile digest.

`solve_qualified_backward_regression_v1` refuses source/conditioning/profile mismatch, reuses the bounded regression kernel, converts the resulting Z matrix to signed Q24 with nearest/ties-to-even rounding, records the maximum conversion error and binds the shadow-regression digest, admitted-evidence digest and Q24 conversion receipt. The result is still `AuthorityPosture::DENY_ALL`.

This closes the repository-side admission and conversion seam. It does **not** prove that a learned FBSDE model is well posed, causally identified, beneficial or safe to activate. Those claims require the externally verified evidence to be real and current, plus independent `learning.eval` acceptance.

## 7. Concrete verification cases

Focused source cases now include:

- preference dimension >64 and genesis/target values outside `[-1,1]` reject;
- already-converged preference state returns zero iterations with no revision churn;
- 64-iteration exhaustion returns `Unavailable`, not a state;
- subject/context mismatch and event/coefficient context rebinding reject;
- unrelated hierarchy subjects may share a generation; an actual parent/child pair may not;
- malformed direct-parent lineage rejects;
- identical projection payloads in different objective/subject scopes have independent revocation state;
- normalization-manifest drift changes the canonical utility-profile digest; zero manifest digest rejects;
- durable append survives reopen only after external acknowledgement; ambiguous anchor failure is reconciled by truncating the unwitnessed tail;
- checkpoint restore requires the same external anchor; legacy snapshot migration cannot mint its own trust;
- qualified FBSDE regression consumes external evidence and emits deterministic Q24 nearest/ties-even evidence;
- external FBSDE verifier rejection or admitted conditioning reuse rejects.

These are source-test identities. Exact-head/synthetic-merge workflow success is separate evidence and must be current for the PR candidate.

## 8. Current composition and remaining gates

Control planning calls the V2 evaluator before sealing planning receipts; the request-local context planner constructs an explicit policy instead of the compatibility policy. The read-only intelligence vertical also consumes the V2 evaluator. These are current source-level composition paths.

Still not claimed:

- activated product ownership of `NduProjectionDurableJournalV1` and a selected external anchor implementation;
- named-host durability/fault-injection/backup restore qualification;
- a complete learned forward/backward model, training/selection runtime or well-posedness proof;
- independent convergence acceptance, which remains owned by `learning.eval`;
- activation, canary, promotion or release.

The exact source/test/claim state is canonicalized in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`. A source-complete claim must not be upgraded to product-complete while any of the gates above remain open.
