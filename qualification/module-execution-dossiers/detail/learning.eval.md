# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: point, cluster, sequential, temporal, cross-fold and independent-decision source candidate implemented; current exact-head and synthetic-merge CI determine source qualification, while real future-window and independent acceptance evidence remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. The normative production ingress contract is `../../../codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md`. Preserve existing estimators and compatibility semantics, but do not expose a weaker production admission path or create another authority/execution spine.

## 2. Public operations and contract details

`estimate_ope(plan, rows) -> OpeEstimate`; `estimate_cluster_intervals(plan, rows, assignments) -> ClusterOpeEstimate`; `estimate_sequential(plan, trajectories) -> SequentialEstimate`; `fit_temporal_fold(plan, training, targets) -> TemporalFoldReceipt`; `evaluate_temporal_holdout(plan, training, targets, observations, assignments) -> TemporalEvaluationReceipt`. Production qualification freezes with `freeze_cross_fold_plan_v2`, consumes the final holdout with `DurableFinalHoldoutJournalV1::consume_proven`, and admits only through `decide_with_signed_durable_evidence_v3` (`Qualification`) or `decide_with_signed_durable_longitudinal_evidence_v4` (`SystemLongitudinal`). Raw `decide_independently*` is trusted-in-process compatibility behind an explicit feature; the lightweight evaluator is crate-private.

The estimand class is mandatory. A single-decision estimate cannot certify a long-horizon policy. Estimator receipts and the independent eligibility decision are separate outputs; neither selects or releases an artifact.

## 3. State records and transaction design

Analysis outputs are immutable evidence with plan/data/code/model IDs, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, resource/retention/privacy results and issuer identity. Durable publication uses the designated evidence owner or an explicitly bound existing evaluation store, not an undeclared production writer. Generator hidden tests and final holdouts remain access-separated.

`CrossFoldPlanV1` binds two to thirty-two canonical folds, each with disjoint training and holdout principal, episode and window lineages. It also binds claim scope, candidate and baseline identities, objective, dataset, estimand, metric directions and safety floors, multiplicity, final-holdout window and final-holdout digest. The final holdout cannot appear in training and must occur in exactly one holdout fold. Production freezes through `freeze_cross_fold_plan_v2`, which additionally preregisters metric roles and margins; deterministic seals detect post-freeze mutation but are not issuer authentication.

The in-memory `FinalHoldoutRegistry` is semantic compatibility only. Production consumes the typed receipt through `DurableFinalHoldoutJournalV1::consume_proven`, which preserves idempotent retry and reuse/mutation rejection while returning the adapter-origin `DurableHoldoutUseV1` required by signed admission. The host/storage layer still owns authoritative-file selection, independent anchors/currentness, rollback protection and multi-host linearizable CAS/fencing when applicable.

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

The former single temporal holdout and conservative cluster code is no longer labelled generic cross-fitting by implication. `freeze_cross_fold_plan_v2` supplies the production analysis contract including preregistered metric roles, and `DurableFinalHoldoutJournalV1::consume_proven` binds final-holdout use to an immutable durable journal record before signed admission. Actual nuisance-model scheduling, authoritative storage ownership/currentness, multi-host fencing when applicable and live outcome provenance remain product bindings. Native estimator, independent observer and authentication adapters are separately identified. The evaluator emits eligibility evidence, never selection or release authority.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `evaluate_temporal_holdout` in [codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation.rs). Point/sequential/temporal estimators and independent decision source implemented.
- **State and recovery:** Temporal evaluation binds a frozen plan and exact joined held-out cohort, isolates training labels and checks cluster lineage. `FinalHoldoutRegistry` remains semantic/in-memory compatibility only. `DurableFinalHoldoutJournalV1::consume_proven` now mints the private-field `DurableHoldoutUseV1` required by production signed admission; host authentication/currentness, multi-host CAS/fencing, rollback protection and production scheduling remain external. Production `SystemLongitudinal` admission requires durable V4 observed-time evidence, not window IDs alone.
- **Source tests:** [codex-rs/hepta-intelligence-eval/src/temporal_evaluation_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/temporal_evaluation_tests.rs), [codex-rs/hepta-intelligence-eval/src/closure_tests.rs](../../../codex-rs/hepta-intelligence-eval/src/closure_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md), [codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- **Remaining work:** Bind the durable holdout adapter to the product nuisance-model scheduler and independently retained current anchor; provide live authenticated outcomes and real future-window evidence; estimator fixtures cannot establish longitudinal efficacy.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, strict Clippy and rustfmt.

The repository cannot self-issue live outcome authentication, a product scheduler and durable holdout-use writer, real future-calendar windows, independent snapshots, statistical power/precision, subgroup/privacy review, retention/change-point observations, backup non-resurrection, independent operator acceptance, selection, canary, promotion or release. These remain external exact-candidate evidence gates.
