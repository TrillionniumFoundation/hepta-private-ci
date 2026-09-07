# utility.ndu: implementation design

Parent: `docs/modules/utility.ndu/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-ndu`.
Packages: `NDU-0-PREFERENCE-UTILITY-CONTRACTS`, `NDU-1-DETERMINISTIC-UTILITY-BASELINE`, `NDU-2-AGENT-DOMAIN-HIERARCHY`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`evaluate_candidates(objective, complete_contributions, profile) -> NduEvaluationReceipt`; `advance_preference(subject, predecessor, event, coefficient_manifest) -> NduUpdateCandidate`; `evaluate_recursive_utility(path, terminal_outcome) -> RecursiveUtilityReceipt`; `solve_backward_regression(conditional_moments, covariance_profile) -> ZEstimate | Unsupported`. Only system/domain/agent/episode are subjects; an organ or software module is not made a subject by emitting a score.

## 3. State records and transaction design

Own append-only preference and recursive-utility projections keyed by scope+subject+objective+predecessor revision+event+coefficient digest. State and coefficient artifact are distinct: bounded episode state may advance, but selected parameters/objective remain immutable within the run. A selected projection pointer changes transactionally only after the immutable row and applicable evidence exist. No effect/credential/acceptance authority resides in utility values.

## 4. Deterministic algorithm and scheduling

Filter hard infeasibility first; reject missing units/support rather than assign zero; compute Pareto candidates; apply only a registered scalarization or return frontier/slow path. Run the deterministic Q32 preference/utility baseline first. Stochastic candidates use Z*C=B with explicit covariance-rate/dt/whitening semantics and reject singular/ill-conditioned pilot covariance. Freeze parent revisions, stage child/parent artifacts across generations and report conservation/residual/gain diagnostics; a local diagnostic is not a global convergence proof.

## 5. Capacity and performance profile

Canonical preference <=64, utility <=8, resource/risk axes <=32, candidates <=128, hierarchy depth 4, iterations <=64; eta in [1/16,1/4]. Existing p95/p99 and storage ceilings remain targets requiring named-host measurement. Stochastic covariance condition ceiling is an additional qualified profile, not a widening of any existing bound.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- NDU-DETAIL-01: analytic scaled covariance C=2dt with true Z=3 recovers 3, not 6.
- NDU-DETAIL-02: correlated covariance [[2,1],[1,2]] and B=[5,1] recovers Z=[3,-1]; singular covariance rejects.
- NDU-DETAIL-03: better soft score with a hard privacy breach is filtered before Pareto ranking.
- NDU-DETAIL-04: simultaneous parent/child artifact selection rejects; fixed objective outcome holdout detects preference-driven reward redefinition.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Map existing evaluate_candidates, preference and recursive primitives rather than replacing them with an unreviewed trainer. Prove real consumers and durable projections separately. Fallback uses a compatible non-revoked deterministic predecessor, then objective baseline/abstain; it cannot relax constraints.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
