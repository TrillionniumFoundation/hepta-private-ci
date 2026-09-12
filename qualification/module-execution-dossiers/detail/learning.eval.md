# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: point, cluster, sequential, temporal, cross-fold and independent-decision source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while real future-window and independent acceptance evidence remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve existing estimators and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`estimate_ope(plan, rows) -> OpeEstimate`; `estimate_cluster_intervals(plan, rows, assignments) -> ClusterOpeEstimate`; `estimate_sequential(plan, trajectories) -> SequentialEstimate`; `fit_temporal_fold(plan, training, targets) -> TemporalFoldReceipt`; `evaluate_temporal_holdout(plan, training, targets, observations, assignments) -> TemporalEvaluationReceipt`; `freeze_cross_fold_plan(plan) -> CrossFoldPlanReceiptV1`; `FinalHoldoutRegistry::consume(&frozen_plan_receipt) -> HoldoutUseReceiptV1`; `decide_independently(bundle) -> IndependentEvaluationDecisionV1`.

The estimand class is mandatory. A single-decision estimate cannot certify a long-horizon policy. Estimator receipts and the independent eligibility decision are separate outputs; neither selects or releases an artifact.

## 3. State records and transaction design

Analysis outputs are immutable evidence with plan/data/code/model IDs, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, resource/retention/privacy results and issuer identity. Durable publication uses the designated evidence owner or an explicitly bound existing evaluation store, not an undeclared production writer. Generator hidden tests and final holdouts remain access-separated.

`CrossFoldPlanV1` binds two to thirty-two canonical folds, each with disjoint training and holdout principal, episode and window lineages. It also binds claim scope, candidate and baseline identities, objective, dataset, estimand, metric directions and safety floors, multiplicity, final-holdout window and final-holdout digest. The final holdout cannot appear in training and must occur in exactly one holdout fold. `freeze_cross_fold_plan` emits a deterministic sealed receipt; the seal detects post-freeze mutation but is not issuer authentication.

The in-memory `FinalHoldoutRegistry` consumes that typed receipt. It permits an exact idempotent retry, rejects semantic mutation under the same plan identity, and prevents a second plan from reusing either the final-holdout digest or final-holdout window. Its sealed use receipt binds the complete frozen-plan semantics and registry state. A product adapter must persist both registry and receipts under an exclusive writer and authenticated storage boundary.

`IndependentEvaluationBundleV1` consumes authenticated generator/evaluator roles, the exact sealed frozen-plan and holdout-use receipts, objective, dataset, estimand, estimate, support, confidence, retention, unlearning, snapshot and future-window facts. It validates receipt integrity and semantic equality before statistical admission. The evaluator cannot share a principal, credential chain or signing key with the generator.

## 4. Deterministic algorithm and scheduling

Freeze all decisions before outcomes are inspected; audit candidate completeness and support; compute single-decision IPS/SNIPS/DR only under its assumptions or sequential history-conditioned DR under its own assumptions; cluster dependent trajectories; freeze the complete cross-fold analysis semantics; consume the exact sealed plan receipt once; apply preregistered monitoring and multiplicity; validate plan/use receipt integrity and equality; intersect all thresholds; and return eligible, insufficient or rejected per claim.

Candidate eligibility requires candidate lower confidence bound beyond baseline upper confidence bound in the declared direction, every safety floor, supported metrics and the claim-specific longitudinal evidence. A system-longitudinal claim additionally requires at least three snapshots, two future windows, retention evidence and an unlearning receipt. No learned outcome model repairs zero support. An internal NDU utility increase is not an independent task-success observation.

## 5. Capacity and performance profile

Resource ceilings are stage-specific, not one global batch claim:

- point OPE: at most 1000000 rows;
- temporal fold fitting: at most 100000 training or target rows;
- composed temporal holdout: at most 16384 held-out rows;
- sequential evaluator: at most 4096 trajectories, 65536 steps and horizon 128;
- candidate actions: at most 128 where the applicable estimator declares that bound.

System-longitudinal ESS is at least `max(400, ceil(0.1*n), stricter slice minimum)`, not a weaker local minimum. Keep at least two real future windows and three independently identified snapshots for a longitudinal claim. These source bounds are not target-host measurements.

## 6. Concrete verification cases

- EVAL-01: two-step sequential DR analytic fixture returns 9/10; zero propensity rejects before division.
- EVAL-02: correlated repeated decisions do not count as independent bootstrap samples.
- EVAL-03: stricter profile wins when ESS floors differ; missing metrics block acceptance.
- EVAL-04: future leakage, holdout reuse, role collision, old-task regression and restored deleted lineage invalidate the corresponding claim.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. The OP-03 cross-module test also confirms that excellent in-sample fit without retention or unlearning remains insufficient.

## 7. Integration, rollback and capability ceiling

The former single temporal holdout and conservative cluster code is no longer labelled generic cross-fitting by implication. `freeze_cross_fold_plan` now supplies an explicit complete analysis contract and sealed receipt, and `FinalHoldoutRegistry::consume` derives its use binding from that receipt rather than loose caller arguments. Actual nuisance-model scheduling, canonical receipt persistence and durable single-writer holdout storage remain product bindings. Native estimator, independent observer and authentication adapters are separately identified. The evaluator emits eligibility evidence, never selection or release authority.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_temporal_holdout` in [codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs). Point/sequential/temporal estimators and independent decision source implemented.
- **State and recovery:** Temporal evaluation binds a frozen plan and exact joined held-out cohort, isolates training labels and checks cluster lineage. FinalHoldoutRegistry remains the in-memory semantic registry. DurableFinalHoldoutJournalV1 now wraps its journal with locked, synced, independently anchored file recovery; host authentication/currentness and production scheduling remain external. Signed SystemLongitudinal admission requires V3 observed-time evidence, not window IDs alone.
- **Source tests:** [codex-rs/hepta-intelligence-eval/src/temporal_evaluation_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation_tests.rs), [codex-rs/hepta-intelligence-eval/src/closure_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/closure_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md), [codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- **Remaining work:** Bind the durable holdout adapter to the product nuisance-model scheduler and independently retained current anchor; provide live authenticated outcomes and real future-window evidence; estimator fixtures cannot establish longitudinal efficacy.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, strict Clippy and rustfmt.

The repository cannot self-issue live outcome authentication, a product scheduler and durable holdout-use writer, real future-calendar windows, independent snapshots, statistical power/precision, subgroup/privacy review, retention/change-point observations, backup non-resurrection, independent operator acceptance, selection, canary, promotion or release. These remain external exact-candidate evidence gates.
