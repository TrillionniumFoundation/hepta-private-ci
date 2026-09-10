# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: point, cluster, sequential, temporal, cross-fold and independent-decision source candidate implemented; exact-head and ordered-base synthetic-merge CI determine source qualification. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `../../../docs/engineering/MODULE_ENGINEERING_STANDARD.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Concrete mappings are recorded in `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Estimation, eligibility, selection and release remain separate authorities.

## 2. Public operations and contract details

The authoritative operation set includes:

- `estimate_ope` and `estimate_cluster_intervals`;
- `estimate_sequential`;
- `fit_temporal_fold` and `evaluate_temporal_holdout`;
- `freeze_cross_fold_plan`;
- `FinalHoldoutRegistry::consume`;
- `FinalHoldoutJournalV1::consume` and `FinalHoldoutJournalV1::from_snapshot`;
- `decide_independently`.

The estimand class is mandatory. A single-decision estimate cannot certify a long-horizon policy. Point estimates, confidence evidence, independent eligibility, artifact selection and release are distinct outputs.

## 3. State records and transaction design

Evaluation records bind plan, data, code, model, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, retention/privacy/unlearning evidence and issuer identity. Generator hidden tests and final holdouts remain access-separated.

`CrossFoldPlanV1` binds two to thirty-two canonical folds with disjoint training and holdout principal, episode and window lineages. It also binds claim scope, candidate/baseline, objective, dataset, estimand, metric direction and safety floors, multiplicity, final-holdout window and digest.

`FinalHoldoutRegistry` remains the pure semantic core. `FinalHoldoutJournalV1` adds expected-head compare-and-swap, a canonical record chain, exact idempotent retry and deterministic snapshot replay. Changed semantics under an existing plan identity conflict; a second plan cannot reuse either final-holdout digest or window. A product adapter must persist the typed journal snapshot under an exclusive writer and authenticate its issuer.

Receipt seals are integrity checks, not signatures. Authenticated origin, trust root and physical durability remain explicit host obligations.

## 4. Deterministic algorithm and scheduling

Freeze every decision before inspecting outcomes; audit candidate completeness and support; run only an estimator whose assumptions match the estimand; cluster dependent trajectories; freeze the complete cross-fold semantics; consume the final holdout against the exact journal head; apply preregistered monitoring and multiplicity; validate plan/use bindings; intersect superiority, safety, support, retention, unlearning and future-window requirements; then emit eligible, ineligible or insufficient evidence.

Multiplicity-adjusted intervals are produced by the responsible statistical engine and bound into typed plan/evidence receipts. The independent decision validates those bindings; it does not silently invent an adjustment from bare unregistered values. No outcome model repairs zero support.

System-longitudinal claims require at least three independently identified snapshots, two real future windows, retention evidence and an unlearning receipt. Internal utility or synthetic model predictions are not independent task-success observations.

## 5. Capacity and performance profile

Stage bounds are distinct:

| Stage | Bound |
|---|---:|
| Point OPE | 1,000,000 rows |
| Temporal fold | 100,000 training or target rows |
| Composed temporal holdout | 16,384 held-out rows |
| Sequential evaluator | 4,096 trajectories / 65,536 steps |
| Sequential horizon | 128 |
| Complete cross-fold lineage | 1,000,000 IDs across the plan profile |

The implementation must enforce both per-vector and total-plan encoded-size, memory and CPU budgets. A broad point-estimator ceiling is never reused as the composed temporal-pipeline capacity claim.

## 6. Concrete verification cases

- EVAL-01: sequential DR goldens are exact and zero support rejects before division.
- EVAL-02: correlated repeated decisions do not manufacture precision.
- EVAL-03: the strictest support profile, superiority, safety, retention and unlearning gates are intersected.
- EVAL-04: future leakage, holdout reuse, receipt drift, role collision and restored deleted lineage invalidate the claim.
- EVAL-05: final-holdout consumption is expected-head-bound, idempotent and exactly replayable after reopen.

Every case maps to concrete Rust tests in `../../lane-e/TEST_TRACEABILITY.json`. Synthetic timestamps do not qualify as future-calendar evidence.

## 7. Integration, rollback and capability ceiling

The final-holdout product adapter must persist the journal and its predecessor head atomically, fence concurrent writers, fsync containing metadata where applicable, reopen and replay before readiness, and quarantine any mismatch. The evaluator emits eligibility evidence only; a separate selector consumes it.

Immediate revocation and stop remain effective across frozen plans. Preserve all external gates; no evaluator self-selection, activation, promotion or release is authorized.

## 8. Native closure and remaining evidence

Repository-controlled coverage now includes the previously omitted cluster and temporal operations, cross-fold plan integrity, final-holdout anti-reuse, predecessor-bound replay and independent decision. `../../../scripts/hepta-lane-e-closure.py` validates public symbols, exports, attributed tests and cross-crate linkage. CI repeats compilation, tests, strict lint and formatting on exact head and ordered merge.

The repository cannot self-issue live outcome authentication, a named product scheduler and physical single-writer store, real future-calendar windows, statistical power/precision, subgroup/privacy review, change-point observations, backup non-resurrection, independent operator acceptance, selection, canary, promotion or release. Those exact-candidate gates remain external.
