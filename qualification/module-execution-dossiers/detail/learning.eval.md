# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`freeze_plan(estimand, baseline, candidate, splits, thresholds) -> EvaluationPlanV1`; `audit_support(dataset, plan) -> SupportAudit`; `evaluate_single_decision(dataset, plan) -> Estimate`; `evaluate_trajectory(dataset, plan) -> SequentialEstimate`; `evaluate_retention_and_unlearning(candidate, slices) -> QualificationResults`. The estimand class is mandatory; a single-decision estimate cannot certify a long-horizon policy.

## 3. State records and transaction design

Analysis outputs are immutable evidence with plan/data/code/model IDs, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, resource/retention/privacy results and issuer identity. Durable publication uses the designated evidence owner or an explicitly bound existing evaluation store, not an undeclared production writer. Generator hidden tests and final holdouts remain access-separated.

## 4. Deterministic algorithm and scheduling

Freeze all decisions before outcomes are inspected; audit candidate completeness and support; compute single-decision IPS/SNIPS/cross-fit DR only under its assumptions or sequential history-conditioned DR under its own assumptions; cluster dependent trajectories; apply preregistered monitoring/multiplicity; intersect all thresholds; return supported/insufficient/rejected per claim. No learned outcome model repairs zero support. An internal NDU utility increase is not an independent task-success observation.

## 5. Capacity and performance profile

Canonical batch <=1000000 rows, <=128 candidates and bounded bootstrap replicates; sequential pilot horizon <=128. System longitudinal ESS is at least max(400,ceil(0.1*n),stricter slice minimum), not a weaker local minimum of 200. Keep at least two real future windows and three independently identified snapshots for the existing longitudinal claim.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- EVAL-01: two-step sequential DR analytic fixture returns 9/10; zero propensity rejects before division.
- EVAL-02: correlated repeated decisions do not count as independent bootstrap samples.
- EVAL-03: stricter profile wins when ESS floors differ; missing metrics block acceptance.
- EVAL-04: future leakage, holdout reuse, role collision, old-task regression and restored deleted lineage invalidate the corresponding claim.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Existing single temporal holdout/conservative cluster code must not be labelled generic cross-fitting without implementation evidence. Native estimator, independent observer and authentication adapters are separately bound. The evaluator emits eligibility evidence, never selects or releases its own candidate.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
