# learning.eval: implementation design

Parent: `docs/modules/learning.eval/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: point, cluster, sequential, temporal, cross-fold, durable-holdout and signed independent-decision source candidate implemented; current exact-head and pull-request synthetic-merge CI determine source qualification, while product execution, real future-window and independent acceptance evidence remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-intelligence-eval`.
Packages: `LRN-2-CAUSAL-EVALUATION`, `LONG-1-TEMPORAL-HOLDOUT`, `LONG-2-RETENTION-FORGETTING`, `LONG-3-UNLEARNING-NON-RESURRECTION`.

Concrete source mappings are recorded in `../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md` and `../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve existing estimators and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`estimate_ope(plan, rows) -> OpeEstimate`; `estimate_cluster_intervals(plan, rows, assignments) -> ClusterOpeEstimate`; `estimate_sequential(plan, trajectories) -> SequentialEstimate`; `fit_temporal_fold(plan, training, targets) -> TemporalFoldReceipt`; `evaluate_temporal_holdout(plan, training, targets, observations, assignments) -> TemporalEvaluationReceipt`; `freeze_cross_fold_plan_v2(plan, metric_roles) -> CrossFoldPlanReceiptV1`; `FinalHoldoutRegistry::consume(&frozen_plan_receipt) -> HoldoutUseReceiptV1`; `DurableFinalHoldoutJournalV1::{create,recover,consume}`; `authenticate_holdout_anchor_v1(...) -> AuthenticatedHoldoutAnchorV1`; `recover_with_authenticated_holdout_anchor_v1(...)`; `decide_with_signed_evidence_v2(...) -> SignedEvaluationDecisionV1`; `decide_with_signed_longitudinal_evidence_v3(...) -> SignedEvaluationDecisionV1`.

The estimand class is mandatory. A single-decision estimate cannot certify a long-horizon policy. Estimator receipts and the independent eligibility decision are separate outputs; neither selects or releases an artifact. All accepted independent decisions remain `DENY_ALL` authority.

## 3. State records and transaction design

Analysis outputs are immutable evidence with plan/data/code/model IDs, eligibility/censoring counts, estimator, support, cluster definition, intervals, multiplicity, resource/retention/privacy results and issuer identity. Durable publication uses the designated evidence owner or an explicitly bound existing evaluation store, not an undeclared production writer. Generator hidden tests and final holdouts remain access-separated.

`CrossFoldPlanV1` binds two to thirty-two canonical folds, each with disjoint training and holdout principal, episode and window lineages. It also binds claim scope, candidate and baseline identities, objective, dataset, estimand, metric directions and safety floors, multiplicity, final-holdout window and final-holdout digest. The final holdout cannot appear in training and must occur in exactly one holdout fold. `freeze_cross_fold_plan_v2` additionally binds preregistered metric roles and margins. Its deterministic sealed receipt detects post-freeze mutation but is not issuer authentication.

The in-memory `FinalHoldoutRegistry` and append-only `FinalHoldoutJournalV1` enforce semantic one-use rules: exact retry is idempotent, semantic mutation under the same plan identity conflicts, and a second plan cannot reuse either the final-holdout digest or final-holdout window. `DurableFinalHoldoutJournalV1` adds an authorized regular-file owner adapter with exclusive cooperating-writer locking, bounded checksummed frames, `sync_all`, recovery against an independently retained minimum anchor and a poisoned state after uncertain writes. It does not own directory durability or current trust state.

`SignedHoldoutAnchorV1` closes the authenticated-origin edge for the independently retained recovery anchor. `authenticate_holdout_anchor_v1` verifies the exact namespace binding, sequence and head under a trusted independent `Observer` plus a host-owned monotonic minimum-issued-at watermark. That watermark is not chosen by the submitted witness. `recover_with_authenticated_holdout_anchor_v1` authenticates first and refuses a zero bootstrap anchor; initialization stays explicit. The product host still has to persist the latest signed witness and freshness watermark outside the holdout journal before releasing confirmatory labels or acknowledging use externally.

`IndependentEvaluationBundleV1` consumes authenticated generator/evaluator roles, the exact sealed frozen-plan and holdout-use receipts, objective, dataset, estimand, estimate, support, confidence, retention, unlearning, snapshot and future-window facts. It validates receipt integrity and semantic equality before statistical admission. Signed evaluation admission verifies actual Ed25519 attestations against host-owned trust and rejects principal, credential-chain, signing-key and controller collisions where applicable.

For `SystemLongitudinal`, V1/V2 signed decision entrypoints deliberately reject the stronger claim. V3 additionally requires `LongitudinalTimeEvidenceV1`: an independent trusted observer signs the exact future-window IDs, snapshot IDs, Unix-microsecond intervals, nonzero observation counts, distinct observed source cuts, frozen plan, dataset, objective and host-preregistered minimum duration. Windows must occur after freeze, not overlap, and end before both observer issuance and trusted current time. This validates evidence admission; it does not manufacture elapsed calendar time.

## 4. Deterministic algorithm and scheduling

Freeze all decisions before outcomes are inspected; audit candidate completeness and support; compute single-decision IPS/SNIPS/DR only under its assumptions or sequential history-conditioned DR under its own assumptions; cluster dependent trajectories; freeze the complete cross-fold analysis semantics; consume the exact sealed plan receipt once; durably commit holdout use; persist and authenticate the external current anchor; apply preregistered monitoring and multiplicity; validate plan/use receipt integrity and equality; intersect all thresholds; and return eligible, insufficient or rejected per claim.

Candidate eligibility requires candidate lower confidence bound beyond baseline upper confidence bound in the declared direction, every safety floor, supported metrics and the claim-specific longitudinal evidence. A system-longitudinal claim additionally requires at least three snapshots, two observed future windows, retention evidence and an unlearning receipt. No learned outcome model repairs zero support. An internal NDU utility increase is not an independent task-success observation.

## 5. Capacity and performance profile

Resource ceilings are stage-specific, not one global batch claim:

- point OPE: at most 1000000 rows;
- temporal fold fitting: at most 100000 training or target rows;
- composed temporal holdout: at most 16384 held-out rows;
- sequential evaluator: at most 4096 trajectories, 65536 steps and horizon 128;
- durable holdout journal: at most 8192 records and 16 MiB, with frames at most 2048 bytes;
- candidate actions: at most 128 where the applicable estimator declares that bound.

System-longitudinal ESS is at least `max(400, ceil(0.1*n), stricter slice minimum)`, not a weaker local minimum. Keep at least two real future windows and three independently identified snapshots for a longitudinal claim. These source bounds and virtual-clock fixtures are not target-host measurements or future-calendar efficacy evidence.

## 6. Concrete verification cases

- EVAL-01: two-step sequential DR analytic fixture returns 9/10; zero propensity rejects before division.
- EVAL-02: correlated repeated decisions do not count as independent bootstrap samples.
- EVAL-03: stricter profile wins when ESS floors differ; missing metrics block acceptance.
- EVAL-04: future leakage, semantic or durable holdout reuse/rollback, stale or mutated signed anchors, unobserved/substituted future windows, role collision, retention failure and restored deleted lineage invalidate the corresponding claim.

Every case is mapped to concrete Rust test functions in `../../lane-e/TEST_TRACEABILITY.json`. EVAL-04 now includes durable recovery, signed-anchor freshness/tamper and signed observed-time tests in addition to semantic registry tests. The OP-03 cross-module test also confirms that excellent in-sample fit without retention or unlearning remains insufficient.

## 7. Integration, rollback and capability ceiling

The former single temporal holdout and conservative cluster code is no longer labelled generic cross-fitting by implication. `freeze_cross_fold_plan_v2` supplies an explicit complete analysis contract and sealed receipt; final-holdout registry/journal use derives from that receipt rather than loose caller arguments. Durable journal and signed-anchor admission now exist in source, but the actual authorized file namespace, independently persisted latest anchor/currentness watermark, nuisance-model scheduling, immutable plan store and live authenticated data remain product bindings. Native estimator, independent observer and authentication adapters are separately identified. The evaluator emits eligibility evidence, never selection or release authority.

Use all eighteen dossier receipt fields. Immediate revocation and stop remain effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** point/cluster/sequential/temporal estimators; `evaluate_temporal_holdout`; cross-fold plan freezing; semantic and durable final-holdout use; signed holdout-anchor admission/recovery; signed independent decision V2; signed observed-time longitudinal decision V3.
- **State and recovery:** Temporal evaluation binds a frozen plan and exact joined held-out cohort, isolates training labels and checks cluster lineage. The durable holdout journal locks and synchronizes a bounded checksummed file, replays against an independent anchor and poisons uncertain handles. The new signed-anchor layer authenticates that external anchor plus a host-owned freshness watermark; the host still owns persistence/currentness and product scheduling.
- **Source tests:** `src/temporal_evaluation_tests.rs`, `src/closure_tests.rs`, `src/durable_holdout_tests.rs`, inline `src/authenticated_holdout.rs` tests and `src/longitudinal_time_tests.rs`. These are test identities, not execution receipts or real future-calendar observations.
- **Implementation and operating references:** [codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md](../../../codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md), [codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md](../../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md).
- **Remaining work:** Bind the source adapters to the product scheduler, immutable plan/data stores, authorized final-holdout namespace and independently retained signed current-anchor store; provide live authenticated outcomes and actual future-window observations; estimator and virtual-clock fixtures cannot establish longitudinal efficacy.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by `../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent pull-request synthetic-merge execution are defined in `.github/workflows/hepta-lane-e-gap-closure.yml`. The workflow compiles all targets, runs owner and cross-crate tests, cross-language wire/fault coverage, strict Clippy and rustfmt, and only then retains machine-readable source-qualification receipts. Those artifacts explicitly deny product-execution, future-calendar, independent-acceptance, selection, promotion and release claims.

The repository cannot self-issue live outcome authentication, a product scheduler/immutable plan store, an authorized production file namespace plus independently persisted current anchor watermark, real future-calendar windows, independent snapshots, statistical power/precision, subgroup/privacy review, retention/change-point observations, backup non-resurrection, independent operator acceptance, selection, canary, promotion or release. These remain external exact-candidate evidence gates.
