# NDU system integration and solver specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Bound modules:** `utility.ndu`, `objective.compiler`, `control.runtime`, `intuition.policy`, `learning.eval`, `learning.ledger`  
**Source target:** `codex-rs/hepta-ndu`  
**Implementation map:** `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`  
**Authority delta:** none

## 1. Scope and authority boundary

NDU is the typed preference and utility owner for supported feasible consequences. It compares only candidates bound to one immutable objective, legal-action set and generation. Authority, truth, privacy, deletion, writer ownership, emergency-stop state and hard risk/resource floors are constraints; they never become compensable utility dimensions.

The source implementation contains a deterministic fixed-point baseline, policy-bound aggregation and Pareto logic, recursive utility, preference updates, conditional-moment/covariance kernels, a protocol-context adapter and an owner-local projection-journal reference. Stochastic learned coefficients remain shadow candidates. None of these operations executes an effect, selects an artifact for production, diagnoses a person, changes the current objective or issues a capability.

## 2. Cross-organ utility contract

Every organ or module contributing to one candidate supplies a bounded contribution containing:

```text
candidate and organ identity
objective digest and body generation
hard-feasibility posture
utility vector
risk vector
resource-cost vector
uncertainty vector
support digest
```

The canonical external contract remains `UtilityContributionV1`; the Rust owner-local type preserves the same core semantics. Each axis has a registered unit and direction. A contribution with an empty support digest, mixed objective, mixed generation, duplicate organ identity, unknown axis or missing required organ is unavailable rather than zero. Every evaluated candidate must also contain a value for every registered uncertainty axis. The candidate support digest is derived from the organ identity, objective, generation, feasibility posture, complete normalized vectors and the upstream support digest, so provenance cannot be detached from contribution semantics.

An organ contributes only facts it owns. `utility.ndu` aggregates supported contributions. `control.runtime` consumes a digest-bound projection of the resulting evaluation; it does not reimplement NDU. `learning.ledger` records the complete candidate/contribution set under its own writer rules.

## 3. Multi-objective feasibility and Pareto policy

Cross-organ aggregation is never implicit for a new integration. `EvaluationPolicyV1` names exactly one rule for every utility, risk, resource and uncertainty axis:

| Operator | Meaning |
|---|---|
| `Sum` | checked Q32 addition |
| `Maximum` | conservative maximum |
| `Minimum` | registered bottleneck/minimum semantics |
| `RequireEqual` | all contributing owners must report the same value |

Missing rules, duplicate rules, unknown axes and `RequireEqual` disagreement reject. Overflow rejects rather than saturating outside a named mathematical projection.

The compatibility API `evaluate_candidates` remains available, but its prior behavior is now explicitly materialized as `legacy-sum-max-zero-tolerance-v1`:

- utility: sum;
- risk: sum;
- resource: sum;
- uncertainty: maximum;
- Pareto absolute tolerance: zero.

New integrations call `evaluate_candidates_with_policy`. `NduEvaluationReceiptV2` binds the normalized policy digest in addition to the legacy evaluation digest, preventing a future aggregation change from silently reinterpreting an old result.

### 3.1 Feasibility, Pareto and scalarization

Selection is staged:

```text
complete-contribution validation
-> hard/risk/resource feasibility
-> Pareto frontier using registered direction and tolerance
-> optional registered scalarization
-> advisory recommendation or slow path
```

A hard violation, risk-ceiling breach or resource-ceiling breach removes a candidate before utility ranking. Abstain must remain present and feasible. If all effectful candidates fail, the outcome is explicit abstain rather than a negative-utility fiction.

Each utility axis has a non-negative absolute Pareto tolerance. Candidate `a` dominates candidate `b` only when `a` is not worse beyond tolerance on every axis and is better beyond tolerance on at least one axis. The normalized tolerance vector is part of the evaluation-policy digest.

Scalarization is permitted only when every registered utility axis has one weight, each weight lies in `[0,1]`, and the exact Q32 sum is one. A tie produces a slow-path disposition, not an arbitrary ID-based winner. Without scalarization, multiple non-dominated candidates return the Pareto set and no advisory recommendation.

## 4. Deterministic hierarchical solver

Valid subject classes are system, domain, agent and episode. Updates are staged:

```text
1. freeze system and domain revisions for one run generation;
2. update episode state at registered decision boundaries;
3. consolidate terminal episode evidence into an agent candidate;
4. evaluate agent candidates against frozen domain boundaries;
5. update domain candidates in a later generation;
6. update the system candidate only after domain snapshots and independent evaluation.
```

The deterministic baseline uses signed Q32, round-to-nearest ties-to-even:

```text
P_candidate = project(P_k + dt * bounded_drift(...))
P_next = (1 - eta) * P_k + eta * P_candidate
U_k = project(instant_utility + discount * continuation_utility)
```

`eta` is in `[1/16,1/4]`. The preference target solver emits immutable revisions and at most 64 local iteration receipts. Parent and child artifact updates cannot share one generation.

## 5. Convergence, infeasibility and multiple solutions

`NduSolverIterationReceipt` records one owner-local numerical step. `NduSolverTerminationReceipt` records:

- disposition;
- iteration count;
- terminal residual;
- true maximum residual across all iterations;
- cumulative projection count;
- predecessor and terminal state digests.

These local records are not an activation certificate. They deliberately do not use the name `NduConvergenceCertificateV1`.

The canonical `NduConvergenceCertificateV1` remains owned by `learning.eval`. It additionally binds independent evaluator identity, operating region, residuals, resource/risk conservation, perturbation evidence and the spectral-radius upper confidence bound. A certificate with a spectral-radius upper 95% bound `>=0.95`, stale objective, unsupported dimension or missing independent decision cannot activate an adaptive artifact.

`bind_solver_iteration_receipt_v1` converts one local step into an owner-local protocol representation only after binding:

- subject ID and class;
- immutable objective digest;
- generation;
- event digest;
- coefficient digest;
- predecessor/next revisions;
- residual, projection count and state digest.

The receipt has a semantic digest and `AuthorityPosture::DENY_ALL`. Missing context fails before publication.

## 6. State, persistence and scheduling

### 6.1 Conditional covariance and stochastic shadow boundary

For a shadow stochastic candidate, let centered increment and utility be:

```text
m_c = m - E[m | F_k]
u_c = U_next - E[U_next | F_k]
C_k = E[m_c m_c^T | F_k]
B_k = E[u_c m_c^T | F_k]
Z_k C_k = B_k
```

Use a stable linear solve, not explicit matrix inversion. Only when `C_k = dt I` does the result reduce to `B_k/dt`. A covariance-rate manifest, whitening convention, coordinate system, `dt` floor, eigenvalue floor and condition-number ceiling are immutable profile fields.

The full-rank pilot rejects singular or ill-conditioned covariance. A pseudoinverse requires a separately qualified supported-subspace profile with residual and null-space identifiability tests. Conditional-moment samples use pre-boundary features; future outcomes may label training rows but never enter runtime features.

A numeric covariance fixture proves algebra only. It does not prove conditional identification, a complete FBSDE solution, adaptive efficacy or activation safety.

### 6.2 Projection state and owner-local durability reference

Preference and utility projections are append-only revisions owned by `utility.ndu`. The full semantic identity includes subject, principal scope, objective, predecessor, event and coefficient. A selected pointer changes only after the immutable projection and required independent evidence exist.

`NduProjectionJournalV1` is an owner-local bounded reference implementation. Each entry binds:

- monotone sequence;
- preference, utility, selection or revocation kind;
- idempotency identity digest;
- objective and subject digests;
- projection payload digest;
- predecessor-entry and entry digests.

The journal enforces equal-identity/equal-semantics replay, rejects identity drift, validates exact length and hashes on reopen, rejects truncation/unknown kind/tampering, reconstructs selected projection state and prevents revocation resurrection after restart.

This reference does not claim an activated production writer, operating-system durability, fsync, schema migration, retention or backup qualification. Product composition must bind a selected store and prove those properties independently.

## 7. Goodhart and wireheading controls

Outcome definitions and observers are owned outside the evaluated policy. NDU cannot write terminal success, alter evidence requirements, change evaluation slices or count its own activation as user utility.

Required controls include complete candidate logging, independent terminal outcomes, future-window evaluation, adversarial proxy tests, reward-channel integrity, causal ablations, subgroup floors, explicit resource accounting and no self-issued selection. A utility gain cannot waive privacy, deletion, authority, support, retention, calibration or safety failure.

Preferences are uncertain internal estimates, not psychological diagnoses or authority statements about a person. Subject identifiers are purpose-scoped. Raw credentials, unrestricted prompts and consumable capability tokens never enter projection or evaluation receipts.

### 7.1 Scheduling, fallback and rollback

The local hot path consumes frozen or cached system/domain summaries and current episode/agent state. It performs no fleet-wide synchronous optimization. Revocation checks remain current even when an artifact or projection is cached.

Fallback order is:

1. compatible selected adaptive predecessor with current evidence;
2. compatible selected deterministic predecessor;
3. valid objective-class deterministic snapshot;
4. immutable objective baseline;
5. abstain or governed slow path.

Every predecessor is checked against current revocation and deletion frontiers. A revoked or incompatible projection is quarantined, not loaded because it once worked. Rollback is a fresh fenced transition and cannot reset epochs, resurrect deleted lineage or reuse an old grant.

Corrections and deletion append revocation edges. Rebuild excludes revoked events, features, datasets, coefficients and descendants. If selective parameter unlearning is unsupported, revoke and retrain; a logical tombstone alone does not prove removal from learned parameters.

## 8. Numerical and resource envelope

Pilot ceilings are:

| Dimension | Ceiling |
|---|---:|
| preference axes | 64 |
| utility axes | 8 |
| risk/resource axes | 32 |
| required organs | 32 |
| candidates | 128 |
| contribution rows | 4096 |
| hierarchy depth | 4 |
| deterministic iterations | 64 |
| projection-journal records per file | 4096 |

All normalization, units, scales, clipping locations and tolerances are manifest-bound. NaN/infinity equivalents, unknown units, dimension drift, excessive projection, covariance failure or conservation failure reject or quarantine the candidate.

Reference-host p95/p99, transient memory and persistent projection targets remain design targets until bound to a named host, compiler, build profile, exact source and fixture. A solver residual is not a statistical-error or efficacy proof.

## 9. Golden fixtures and tests

- `NDU-SYS-GV-001`: deterministic zero-noise preference/utility vector reproduces exact Q32 values.
- `NDU-SYS-GV-002`: a higher-utility privacy-violating candidate is filtered before Pareto analysis.
- `NDU-SYS-GV-003`: multiple non-dominated candidates without scalarization return a Pareto slow path.
- `NDU-SYS-GV-004`: simultaneous parent/child update rejects; staged damping converges in the fixture.
- `NDU-SYS-GV-005`: resource cost above ceiling is infeasible, not negative utility.
- `NDU-SYS-GV-006`: changed outcome-observer identity invalidates the evaluation chain.
- `NDU-SYS-GV-007`: policy-specific maximum aggregation differs from summation and is digest-bound.
- `NDU-SYS-GV-008`: `RequireEqual` detects contradictory organ values.
- `NDU-SYS-GV-009`: Pareto tolerance changes the frontier and policy digest deterministically.
- `NDU-SYS-GV-010`: termination receipt reports terminal and true maximum residual separately.
- `NDU-SYS-GV-011`: canonical iteration publication rejects missing objective/event/coefficient context.
- `NDU-SYS-GV-012`: projection-journal reopen, tamper, truncation and revocation non-resurrection fixtures pass.

Exact native mappings are registered in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`. The same implementation cannot be the sole oracle for a critical numerical claim; analytic or independent scalar fixtures remain required.

## 10. Implementation sequence

Implementation order is typed contributions, explicit aggregation policy, feasibility, tolerant Pareto, optional scalarization, fixed-point preference state, local solver receipts, canonical context adapter, recursive utility, covariance shadow kernel, owner-local durability reference, exact source tests and semantic conformance.

Work-package ownership is narrowed by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`:

- `NDU-2A-HIERARCHY-PROTOCOLS` owns cross-module contract specification;
- `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION` owns `codex-rs/hepta-ndu/**`;
- `RCP-2-NDU-HIERARCHY-INTEGRATION` owns Control integration under `runtime-control` with explicit co-ownership.

The legacy `NDU-2-AGENT-DOMAIN-HIERARCHY` identifier remains in historical DAGs but is superseded for new source mutation by this overlay. No package gains positive authority.

Repository-controlled completion requires the implementation map, source tests, strict lint, semantic checker, exact-head workflows and synthetic merge checks. Product caller, production writer, independent convergence decision, activation and release remain separately governed.

## 11. Coding-entry checklist

- contribution sets bind one objective and generation and contain every required organ;
- every utility axis has an explicit uncertainty value, never an omitted implicit zero;
- candidate support digests bind organ identity and complete normalized contribution semantics;
- aggregation, Pareto tolerance and optional scalarization profiles are digest-bound;
- local termination receipts remain distinct from independent convergence certificates;
- projection reopen, tamper and revocation non-resurrection fixtures pass;
- exact-head and synthetic-merge checks pass before source completion is claimed.

## Appendix A. Closed gap and protocol mapping

Canonical readiness protocols:

- `UtilityContributionV1` — owned by `utility.ndu`;
- `NduIterationReceiptV1` — owned by `utility.ndu`;
- `NduConvergenceCertificateV1` — owned by `learning.eval`.

Owner-local source types such as `EvaluationPolicyV1`, `NduEvaluationReceiptV2`, `NduSolverTerminationReceipt` and `NduProjectionJournalV1` do not become admitted external wire protocols by appearing in Rust. External protocol admission requires explicit registry and consumer changes.

Closed documentation gap identifiers remain:

- `RDY-GAP-NDU-001`
- `RDY-GAP-NDU-002`
- `RDY-GAP-NDU-003`
- `RDY-GAP-NDU-004`
- `RDY-GAP-NDU-005`
- `RDY-GAP-NDU-006`
