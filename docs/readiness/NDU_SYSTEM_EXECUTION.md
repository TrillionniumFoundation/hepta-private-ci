# NDU system integration and solver specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Bound modules:** `utility.ndu`, `objective.compiler`, `control.runtime`, `intuition.policy`, `learning.eval`, `learning.ledger`  
**Source target:** `codex-rs/hepta-ndu`  
**Implementation map:** `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`  
**Authority delta:** none

## 1. Scope and authority boundary

NDU is the typed preference and utility owner for supported feasible consequences. It compares only candidates bound to one immutable objective, legal-action set and generation. Authority, truth, privacy, deletion, writer ownership, emergency-stop state and hard risk/resource floors are constraints; they never become compensable utility dimensions.

The source implementation contains a deterministic fixed-point baseline, policy-bound aggregation and Pareto logic, recursive utility, preference updates, conditional-moment/covariance kernels, a protocol-context adapter, an append-only projection journal and a crash-bounded local durable-writer candidate. Stochastic learned coefficients remain shadow candidates. None of these operations executes an effect, selects an artifact for production, diagnoses a person, changes the current objective or issues a capability. Presence of the durable writer source is not production activation.

### Theory-to-runtime separation for decision cells

NDU guides System 1 forward state/preference/action formation and System 2
recursive valuation/credit/action-parameter control. A cell is a scoped optimization
unit beneath an existing subject, not a fifth subject class or independent goal
owner. Local inference may consume frozen organ utility/credit boundaries; a full
FBSDE or central RPC at each node is not required. The formal augmented state,
parameter-gradient contract and limits are in `../learning/NDU_FBSDE_SPEC.md`.
Current native evaluator/solver claims are unchanged by this design amendment.

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

Each utility axis has a non-negative absolute Pareto tolerance. Candidate `a` dominates candidate `b` only when `a` is no worse on every axis and improves at least one axis by strictly more than that axis's tolerance. Tolerance never permits deterioration on another axis. This is an irreflexive, transitive relation: both comparisons preserve each weak inequality, and the first comparison's strict improvement survives their composition. A finite nonempty feasible set therefore has a nonempty frontier; equivalent or near-equal candidates may remain incomparable.

The normalized tolerance vector is part of the evaluation-policy digest, whose domain is now `hepta.ndu.evaluation-policy.v2`. Historical V1 policy digests identify the old relation and must not be relabeled as V2; replay requiring the corrected semantics must produce a new policy/evaluation binding. The zero-tolerance compatibility API retains its exact-Pareto behavior and base receipt format.

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

`eta` is in `[1/16,1/4]`. The preference target solver emits immutable revisions and at most 64 local iteration receipts. If the registered residual tolerance is not reached inside that bound, the solver returns `PreferenceSolverUnavailable`; the last bounded numerical state is not exposed as a successful terminal state. When iterations exist, the termination maximum is computed only from the emitted iteration receipts; the pre-iteration residual is not folded into that field. A zero-iteration no-op uses its validated initial residual for both terminal and maximum residual.

Parent/child staging is scoped by an explicit stable hierarchy identity. Different subject levels within the same hierarchy cannot select new artifacts in one generation. Unrelated hierarchy roots may advance in the same generation; a global subject-class ban is not the intended invariant.

## 5. Convergence, infeasibility and multiple solutions

`NduSolverIterationReceipt` records one owner-local numerical step. A successful `NduSolverTerminationReceipt` records:

- disposition;
- iteration count;
- terminal residual;
- maximum residual across the emitted iteration receipts, or the validated initial residual for a zero-iteration no-op;
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

`solve_preference_target_with_context_v1` freezes the objective, generation, event, coefficient and subject before entering the existing numerical kernel. Its private solver source binds the validated initial state, canonical target and actual eta. The adapter rejects context-free legacy steps and any post-execution context replacement; native exported receipts include `solve_input_digest` under digest domain `hepta.ndu.iteration-receipt.v2`, without changing their deny-all authority or claiming independent convergence.

The adapter also rejects structurally impossible local receipts: iteration zero or above 64, negative residual, a non-successor next revision, or an empty state digest. The receipt has a semantic digest and `AuthorityPosture::DENY_ALL`. Missing context or malformed local state fails before publication.

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

### 6.2 Projection journal semantic recovery

Preference and utility projections are append-only revisions owned by `utility.ndu`. The full semantic identity includes subject, principal scope, objective, predecessor, event and coefficient. A selected pointer changes only after the immutable projection and required independent evidence exist, and replacement requires an exact expected-predecessor compare-and-set. Exact operation replay remains idempotent; a late selection cannot overwrite a newer selected projection.

`NduProjectionJournalV1` is the bounded state-machine and serialization layer. Each entry binds:

- monotone sequence;
- preference, utility, selection or revocation kind;
- idempotency identity digest;
- objective and subject digests;
- projection payload digest;
- predecessor-entry and entry digests.

The journal enforces equal-identity/equal-semantics replay, rejects identity drift, validates exact length and hashes on reopen, rejects truncation/unknown kind/tampering, reconstructs selected projection state and prevents revocation resurrection. Recovery does not trust hash validity alone: every serialized selection and revocation is replayed through the same semantic transition checks as a live mutation. A hash-valid selection or revocation for a projection that was never recorded for that objective/subject is rejected.

### 6.3 Crash-bounded durable writer candidate

`NduProjectionStoreV1` is a native source candidate for the module-owned projection writer. It is intentionally separate from external activation. The host supplies an already-created private local directory; the store does not discover or create a broader filesystem root.

The V1 writer provides:

- one advisory writer lock held for the open store lifetime;
- metadata-size admission before allocation plus a bounded `max + 1` read before semantic reopen;
- bounded reopen through the semantic journal parser;
- stale uncommitted temporary-image removal only after lock acquisition;
- copy-on-mutate so failed persistence does not advance the in-memory journal;
- complete temporary-image write followed by `sync_all`;
- atomic rename to the committed image;
- parent-directory synchronization on the Unix qualification profile before success acknowledgement;
- an `Indeterminate` result for any rename error, including a replacement whose acknowledgement was lost, or if directory durability cannot be acknowledged;
- exact backup export;
- validated backup restore only when the current committed history is an exact prefix of the restored history, preventing an old valid backup from deleting a later revocation.

The file image remains bounded to the 4096-record journal ceiling. Ordinary projection and selection history is admitted only while enough slots remain to revoke every currently live projection; revocation itself may consume that reserved frontier. The full-capacity fixture rejects ordinary history first, validates an in-memory revocation prefix, and commits the final two reserved revocations through the real store with a reopen between them. Recovery reaches all 4096 records and exact retries do not append duplicate entries; prefix fixture construction is not evidence of 2048 separate disk writes. The lock is advisory and assumes a host-private directory; a hostile process that ignores the lock is outside this mechanism's threat model.

`NduProjectionStoreV1` is the initial V1 on-disk store format; V1 schema-open validation rejects unknown/corrupt images, and no fictitious predecessor migration is claimed. Any future format change requires an explicit deterministic migrator plus rollback compatibility evidence. Retention is fail-closed at the bounded record limit rather than silently compacting or deleting revocation history.

This source candidate does **not** establish production activation. Target-host filesystem behavior, non-Unix atomic-replace/directory-durability equivalence, host authentication and enrollment, retention policy, encrypted/off-host backup transport, restore drills, monitoring, independent acceptance, canary and release remain separately governed evidence. `productionWriterState` therefore remains fail-closed until those boundaries are qualified and selected.

### Organ credit and learning scheduling

An organ may maintain joint value/credit estimates while cells execute locally.
Actual behavior laws, peer policy versions, delayed outcomes and critic support
flow through learning.ledger. Derived advantages are not new observed facts or
authority. Value interactions are not assumed additive; existing Sum/Max/Min rules
are used only for axes with those registered semantics. Physical resources are
charged once and attributed, not repeatedly consumed in each hierarchy layer.

The learning owner applies justified NDU-sensitive gradients, actor objectives or
policy distillation to candidate Laya heads/adapters. The utility owner does not
become a model trainer/executor. Freeze the parent/peer/bundle references for each
update stage; insufficient data means no update. Publish compatible cell, organ
and base candidates through the existing artifact-selection boundary. A change
in utility estimator must still be tested against the same external objective.

### Circuit-valued decisions

Evaluate activation, branch selection, continuation and termination in addition to
cell actions. Nested calls contribute declared duration, resources and supported
successor/uncertainty summaries, not a fixed reward per visited node. The actual
route policy after all admissibility filters belongs in the learning trace; an
upstream probability alone is not its propensity. Fit cell-only and route-only
candidates separately before joint updates; topology is a slower candidate class.
Durable historical choices remain immutable when a utility/model revision changes.

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

### Parameter-field diagnostics do not authorize control

The fixed-epoch field profile in `../learning/NDU_FBSDE_SPEC.md` binds effective
operators/probes, anchors, declared symmetry and optimizer/task conditioning.
Distinguish inference depth from learning time and retain multidriver/closure
uncertainty. A field projection cannot declare its own reward or acquire authority;
its control benefit must be tested against independent task outcomes and matched
baseline information. Topology surgery requires a new field epoch/transport.
No new native solver, wire protocol or production observer is introduced here.

## 9. Golden fixtures and tests

- `NDU-SYS-GV-001`: deterministic zero-noise preference/utility vector reproduces exact Q32 values.
- `NDU-SYS-GV-002`: a higher-utility privacy-violating candidate is filtered before Pareto analysis.
- `NDU-SYS-GV-003`: multiple non-dominated candidates without scalarization return a Pareto slow path.
- `NDU-SYS-GV-004`: simultaneous parent/child update inside one hierarchy rejects; unrelated hierarchy roots may advance in the same generation.
- `NDU-SYS-GV-005`: resource cost above ceiling is infeasible, not negative utility.
- `NDU-SYS-GV-006`: changed outcome-observer identity invalidates the evaluation chain.
- `NDU-SYS-GV-007`: policy-specific maximum aggregation differs from summation and is digest-bound.
- `NDU-SYS-GV-008`: `RequireEqual` detects contradictory organ values.
- `NDU-SYS-GV-009`: Pareto tolerance changes the frontier and policy digest deterministically.
- `NDU-SYS-GV-010`: successful termination receipt reports terminal and true maximum residual separately.
- `NDU-SYS-GV-011`: canonical iteration publication rejects missing objective/event/coefficient context and malformed local iteration receipts.
- `NDU-SYS-GV-012`: projection-journal reopen rejects tamper, truncation, hash-valid impossible transitions and revocation resurrection.
- `NDU-SYS-GV-013`: registered slow damping that cannot reach tolerance in 64 iterations returns unavailable.
- `NDU-SYS-GV-014`: durable writer reopen preserves selected and revoked state under the single-writer lock.
- `NDU-SYS-GV-015`: stale temporary images are discarded before recovery and a concurrent writer is rejected.
- `NDU-SYS-GV-016`: backup restore validates the full journal and rejects rollback that would remove a later revocation.

Exact native mappings are registered in `docs/modules/utility.ndu/IMPLEMENTATION_MAP.json`. The same implementation cannot be the sole oracle for a critical numerical claim; analytic or independent scalar fixtures remain required.

## 10. Implementation sequence

Implementation order is typed contributions, explicit aggregation policy, feasibility, tolerant Pareto, optional scalarization, fixed-point preference state, local solver receipts, canonical context adapter, recursive utility, covariance shadow kernel, semantic projection journal, crash-bounded durable writer candidate, exact source tests and semantic conformance.

Work-package ownership is narrowed by `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`:

- `NDU-2A-HIERARCHY-PROTOCOLS` owns cross-module contract specification;
- `NDU-2B-NDU-HIERARCHY-IMPLEMENTATION` owns `codex-rs/hepta-ndu/**`;
- `RCP-2-NDU-HIERARCHY-INTEGRATION` owns Control integration under `runtime-control` with explicit co-ownership.

The legacy `NDU-2-AGENT-DOMAIN-HIERARCHY` identifier remains in historical DAGs but is superseded for new source mutation by this overlay. No package gains positive authority.

Repository-controlled source completion requires the implementation map, source tests, strict lint, semantic checker, exact-head workflows and synthetic merge checks. A concrete request-local read-only path is established as `runtime.agentd cognitive_context -> control plan_observed_context -> evaluate_prepared_plan_with_ndu -> NDU V2 evaluator`, and the dedicated NDU workflow runs focused Control caller regressions. This establishes bounded product execution only for that read-only/planning profile. Authenticated production NDU owner/caller composition, selected production writer activation, independent convergence decision, target-host qualification and release remain separately governed.

## 11. Coding-entry checklist

- contribution sets bind one objective and generation and contain every required organ;
- every utility axis has an explicit uncertainty value, never an omitted implicit zero;
- candidate support digests bind organ identity and complete normalized contribution semantics;
- aggregation, Pareto tolerance and optional scalarization profiles are digest-bound;
- solver exhaustion returns unavailable and is never relabeled convergence;
- hierarchy staging compares levels only inside one explicit hierarchy identity;
- local termination receipts remain distinct from independent convergence certificates;
- protocol publication rejects structurally invalid local solver receipts;
- projection reopen replays semantic transitions, not only hashes;
- durable writer tests cover lock lifetime, crash-temp recovery, reopen, backup validation and non-resurrection;
- exact-head and synthetic-merge checks pass before source completion is claimed.

## Appendix A. Closed gap and protocol mapping

Canonical readiness protocols:

- `UtilityContributionV1` — owned by `utility.ndu`;
- `NduIterationReceiptV1` — owned by `utility.ndu`;
- `NduConvergenceCertificateV1` — owned by `learning.eval`.

Owner-local source types such as `EvaluationPolicyV1`, `NduEvaluationReceiptV2`, `NduSolverTerminationReceipt`, `NduProjectionJournalV1` and `NduProjectionStoreV1` do not become admitted external wire protocols by appearing in Rust. External protocol admission requires explicit registry and consumer changes.

Closed documentation gap identifiers remain:

- `RDY-GAP-NDU-001`
- `RDY-GAP-NDU-002`
- `RDY-GAP-NDU-003`
- `RDY-GAP-NDU-004`
- `RDY-GAP-NDU-005`
- `RDY-GAP-NDU-006`


## Current deterministic-owner and coefficient integrity boundary (2026-09-25)

The canonical NDU follow-up is PR #997, not a parallel writer implementation. The normal Agentd `local-deterministic` bootstrap consumes a digest-pinned bounded descriptor and a fresh independently signed revocation source. Its existing private control socket exposes preparation, signed mutation, selection and historical outcome queries. Product selection binds the complete journal head as well as selected-content predecessor; content-only CAS cannot by itself reject an A-to-B-to-A history. Previously committed operation identities are reconciled through their stored outcome, not rebound to a new journal head. Owner/principal scope and frozen production policy are persisted under the single writer lock; unbound historical stores require explicit migration.

The producer and stochastic consumer share `validate_ndu_coefficient_projection_v1`. Actual signed-Q24 matrix values, shape, admitted profile, source evidence and conversion receipt are recomputed against the canonical output digest before the solver identity is accepted. Retaining old digests/certificates while modifying even one numeric coordinate must fail. A freshly recomputed digest is still not independent acceptance: the current actual artifact, independently signed convergence/well-posedness evidence and consumer context must also match.

These integrity and local process capabilities do not establish protected time, an off-host rollback witness, learned Cell/Circuit activation or external utility improvement. Independent held-out/longitudinal outcomes, actual selected artifacts and governed production trust remain separate gates. See the current module technical guide and retained exact-candidate suite receipts; test source and a workflow definition are not execution results.
