# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: point, cluster, sequential-confidence, temporal cross-fit, recorded product evaluation, typed single- and multi-outcome archives, persistent recovery and independent-decision source candidate implemented. Current exact-head and synthetic-merge CI determine source qualification; authenticated target-host invocation, real future-window and independent acceptance evidence remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged. Current public and recovery semantics are normative in `../../../codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md`, `../../../codex-rs/hepta-intelligence-eval/RECOVERY_CONTRACT.md` and `../../../codex-rs/hepta-intelligence-eval/RECOVERY_TRUST_CAPACITY_CONTRACT.md`.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Concrete current source mappings are recorded in `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md` and `../../../docs/modules/learning.eval/IMPLEMENTATION_MAP.json`; the Lane E matrix retains cross-module design lineage. Preserve existing estimators and registered compatibility; do not create another authority or execution spine.

## 2. Public operations and contract details

Statistical source operations include `estimate_ope`, `estimate_cluster_intervals`, `estimate_sequential`, `SequentialPlan::estimate_cluster_intervals_v1`, `fit_temporal_fold`, `evaluate_temporal_holdout` and `CrossFoldPlanV1::execute_temporal_cross_fit_v1`. Plan freezing uses `freeze_cross_fold_plan_v2`, `freeze_product_evaluation_plan_v1` or `freeze_product_outcome_plan_v1`.

Default product ingress uses `RecordedProductEvaluationRunnerV1::{evaluate_temporal_comparison,evaluate_outcome_comparison}` over the independently anchored durable journal capability. Public qualification uses `qualify_and_persist_with_artifacts` or the selected-host single- and multi-outcome methods, which persist the canonical typed archive before decision. Public selected-host final use requires root-issued `ActivatedLearningTrustV1` and a host-sampled clock. Public recovery uses the selected-host archive/reconciliation methods and persistent pending-page controller.

`FencedFinalHoldoutOwnerV1::consume` and `LockedFileFinalHoldoutCasStoreV1::{create,recover,compact_into}` supply contended holdout ownership and verified copy-compaction. Signed V2/V3 decision functions and unarchived recorded qualification helpers are crate-internal. The raw `ProductEvaluationRunnerV1` and direct unsigned evaluators are trusted-only compatibility surfaces behind `trusted-inprocess-eval`; they are not alternative default product ingress.

The estimand class is mandatory. A single-decision estimate cannot certify a long-horizon policy. Estimator receipts and the independent eligibility decision are separate outputs; neither selects or releases an artifact.

## 3. State records and transaction design

Analysis outputs are immutable evidence with plan/data/code/model IDs, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, resource/retention/privacy results and issuer identity. Durable publication uses the designated evidence owner or an explicitly bound existing evaluation store, not an undeclared production writer. Generator hidden tests and final holdouts remain access-separated.

`CrossFoldPlanV1` binds two to thirty-two canonical folds, each with disjoint training and holdout principal, episode and window lineages. It also binds claim scope, candidate and baseline identities, objective, dataset, estimand, metric directions and safety floors, multiplicity, final-holdout window and final-holdout digest. The final holdout cannot appear in training and must occur in exactly one holdout fold. Production qualification uses `freeze_cross_fold_plan_v2` so preregistered metric roles and margins enter the frozen digest before holdout use. The deterministic seal detects post-freeze mutation but is not issuer authentication.

The in-memory `FinalHoldoutRegistry` consumes that typed receipt. `DurableFinalHoldoutJournalV1` remains the single-host/cooperative compatibility adapter. Contended production composition uses one canonical owner, `FencedFinalHoldoutOwnerV1`; `LockedFileFinalHoldoutCasStoreV1` is the repository concrete cross-process CAS/replay backend and accepts an independently retained `FinalHoldoutCasAnchorV1` to reject stale backup restore. `HoldoutFenceIssuerV1` resumes fence generation from that retained minimum. Alternate target hosts may substitute an equivalent linearizable CAS backend without creating another holdout authority.

`RecordedProductEvaluationRunnerV1` freezes metric-source selection into the bound estimand, reserves the complete remaining lifecycle and acknowledges `IntentPersisted` before provider lookup or holdout access. It consumes the fenced holdout and acknowledges `HoldoutConsumed` before the provider releases observations. Candidate and baseline use the same bound outcome cohort and `MetricGateV1` intervals derive only from sealed estimator receipts. Multi-outcome evaluation preserves each independently named measurement channel; authenticating the real measurement custodian remains a host obligation.

Successful public qualification appends `ComparisonSealed`, persists the module-owned canonical single- or multi-outcome archive and acknowledges `QualificationArtifactsPersisted`, reconstructs and verifies the exact V2/V3 bundle, then appends `QualificationDecided` and `PublicationPending` before publication. `Published` requires observing the exact committed record. The seven-phase history, unresolved index and reducer checkpoint/tail replay are independently anchored. Recovery resolves active trust for each attempt, reloads the typed archive and re-verifies evidence inside the module; it cannot accept a caller-created decision or blindly repeat a Pending write. For V3, generator, evaluator and observer are pairwise independent by principal, credential chain, signing key and controller.

## 4. Deterministic algorithm and scheduling

Freeze all decisions before outcomes are inspected; audit candidate completeness and support; compute single-decision IPS/SNIPS/DR only under its assumptions or sequential history-conditioned DR under its own assumptions; cluster dependent trajectories; freeze the complete cross-fold analysis semantics; consume the exact sealed plan receipt once; apply preregistered monitoring and multiplicity; validate plan/use receipt integrity and equality; intersect all thresholds; and return eligible, insufficient or rejected per claim.

Candidate eligibility applies the preregistered V2 metric roles: primary superiority requires conservative improvement strictly beyond its margin; non-inferiority permits regression only within its bound; an absolute constraint applies its registered directional bound. Every applicable safety floor, support requirement and claim-specific longitudinal gate must also pass. A system-longitudinal claim additionally requires at least three snapshots, two observed future windows, retention evidence and an unlearning receipt. No learned outcome model repairs zero support. An internal NDU utility increase is not an independent task-success observation. Fixed-analysis sequential confidence does not provide adaptive-stopping or anytime-valid guarantees.

## 5. Capacity and performance profile

Resource ceilings are stage-specific, not one global batch claim:

- point OPE: at most 1000000 rows;
- temporal fold fitting: at most 100000 training or target rows;
- composed temporal holdout: at most 16384 held-out rows;
- sequential evaluator: at most 4096 trajectories, 65536 steps and horizon 128;
- candidate actions: at most 128 where the applicable estimator declares that bound.
- measured outcomes: at most 32 channels and 100000 aggregate batch rows, subject to each estimator's smaller bound;
- attempt journal: at most 64 MiB and 1000000 events, with complete lifecycle reservation before new intent;
- pending discovery: 1 to 1024 unresolved identities per page.

The sustained source profile contains 4096 attempts and 28672 lifecycle events. Checkpoints 64 attempts before each 128-attempt restart exercise nonempty tail replay. These fixture parameters do not establish measured target-host performance.

System-longitudinal ESS is at least `max(400, ceil(0.1*n), stricter slice minimum)`, not a weaker local minimum. Keep at least two real future windows and three independently identified snapshots for a longitudinal claim. These source bounds are not target-host measurements.

## 6. Concrete verification cases

- EVAL-01: two-step sequential DR analytic fixture returns 9/10; zero propensity rejects before division.
- EVAL-02: correlated repeated decisions do not count as independent bootstrap samples.
- EVAL-03: stricter profile wins when ESS floors differ; missing metrics block acceptance.
- EVAL-04: future leakage, holdout reuse, role collision, old-task regression and restored deleted lineage invalidate the corresponding claim.

The historical Lane E cases are mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`; current recorded-product, archive, active-trust, capacity, checkpoint and consumer tests are mapped in `../../../docs/modules/learning.eval/IMPLEMENTATION_MAP.json` and `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md`. The OP-03 cross-module test confirms that excellent in-sample fit without retention or unlearning remains insufficient. Compiler-negative fixtures must specifically reject raw/unarchived ingress, a bare selected-host verifier and a caller-supplied scalar clock; unrelated compilation failure is not evidence of that boundary.

## 7. Integration, rollback and capability ceiling

The former single temporal holdout and conservative cluster code is no longer labelled generic cross-fitting by implication. `freeze_cross_fold_plan_v2` supplies an explicit complete analysis contract and sealed receipt, and `CrossFoldPlanV1::execute_temporal_cross_fit_v1` executes every preregistered fold with exact lineage and recomputed output-digest equality. Final-holdout use derives from the frozen receipt rather than loose caller arguments. Canonical archive persistence, concrete fenced storage and bounded persistent recovery exist in source; the selected host must bind their namespaces, scheduler, trust, provider, anchor and publication owner. The evaluator emits eligibility evidence, never selection or release authority.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** Point, cluster, sequential-confidence, temporal cross-fit and recorded single-/multi-outcome evaluation and qualification are mapped in [NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md). Raw estimator source and default product ingress have distinct contracts.
- **State and recovery:** Temporal evaluation binds a frozen plan and exact joined held-out cohort, isolates training labels and checks cluster lineage. `FinalHoldoutRegistry` remains the in-memory semantic registry. `DurableFinalHoldoutJournalV1` is the single-host/cooperative-owner adapter; `FencedFinalHoldoutOwnerV1` plus the concrete locked-file CAS backend supplies contended ownership. The independently anchored attempt journal, canonical typed archives, checkpoint/tail replay, selected-host publication store, per-attempt active-trust checks and durable recovery cursor exist in source. Authenticating the deployed trust/anchor/provider/publication topology, storage semantics and scheduler invocation remains external. Signed `SystemLongitudinal` admission requires V3 observed-time evidence, not window IDs alone.
- **Source tests:** Estimator/unit tests, seven process-kill cuts, two-process cold archive recovery, selected-host single-/multi-outcome recovery, active-trust expiry/revocation, near-capacity and sustained checkpoint tests are mapped in [IMPLEMENTATION_MAP.json](../../../docs/modules/learning.eval/IMPLEMENTATION_MAP.json). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md](../../../codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md), [codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md), [codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- **Remaining work:** bind the evidence sink and holdout namespace to a named target host; then provide live authenticated outcomes and real future-window/retention/privacy/unlearning evidence. `run_evaluated_shadow_v1` now consumes only `ProductQualificationReceiptV1`, so the repository-controlled product qualification spine is single-path. The repository has a concrete cross-process locked-file CAS backend; cross-host use still requires qualification of the shared filesystem's lock/fsync semantics.

## 9. Native closure and remaining evidence

Repository-controlled source coverage includes `../../../scripts/hepta-lane-e-closure.py`. Current learning.eval convergence, exact-tree and sustained-profile workflows separately verify compiler/API boundaries, owner/consumer and process-fault tests, typed cold recovery, active trust, capacity/checkpoint behavior, all-target compilation, strict Clippy, rustfmt and default-production coverage. Exact-head and ordered-parent synthetic-merge evidence must pass on one immutable final candidate; configured workflows and discovered test names are not passing receipts.

The repository supplies source contracts and concrete scheduler-facing recovery, durable holdout and publication adapters. It cannot self-issue authenticated deployed invocation, independent anchor administration, live outcome authentication, qualified storage topology, real future-calendar windows, independent snapshots, statistical power/precision, subgroup/privacy review, retention/change-point observations, backup non-resurrection, independent operator acceptance, selection, canary, promotion or release. These remain external exact-candidate evidence gates.

- EVAL-05: The recorded product runner must acknowledge intent and fenced final-holdout consumption before release, derive MetricGate intervals only from sealed candidate/baseline estimator receipts, persist the canonical typed archive before internal current verification and require exact durable evidence publication.

- EVAL-06: The concrete locked-file CAS owner must replay committed history, fence failover, expose cross-process exclusion and reject restoring a backup older than the independently retained minimum anchor.

- EVAL-07: SystemLongitudinal admission requires generator, evaluator and observer to be pairwise independent by principal, credential chain, signing key and controller.
