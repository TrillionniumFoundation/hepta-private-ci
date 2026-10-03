//! Product-level self-evolution acceptance: the learning chain starts from the
//! ordinary Agentd product admission and its independently observed outcome.
//! Signers, future windows and metric intervals below are controlled fixtures,
//! not independent deployment acceptance or empirical learning benefit.

use std::collections::BTreeSet;
use std::fs::OpenOptions;

use super::*;
use codex_hepta_agent_components::control_plane::RuntimeModuleAbiV1;
use codex_hepta_agent_components::control_plane::RuntimeModuleStateClassV1;
use codex_hepta_agent_components::intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_agent_components::intelligence_eval::CrossFoldPlanV1;
use codex_hepta_agent_components::intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_agent_components::intelligence_eval::EvaluationDirectionV1;
use codex_hepta_agent_components::intelligence_eval::EvaluationIntervalV1;
use codex_hepta_agent_components::intelligence_eval::FinalHoldoutRegistry;
use codex_hepta_agent_components::intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_agent_components::intelligence_eval::LongitudinalTimeEvidenceV1;
use codex_hepta_agent_components::intelligence_eval::MetricContractV1;
use codex_hepta_agent_components::intelligence_eval::MetricGateV1;
use codex_hepta_agent_components::intelligence_eval::MetricRoleContractV2;
use codex_hepta_agent_components::intelligence_eval::MetricRoleV2;
use codex_hepta_agent_components::intelligence_eval::ObservedFutureWindowV1;
use codex_hepta_agent_components::intelligence_eval::SelfEvolutionSelectionPolicyV1;
use codex_hepta_agent_components::intelligence_eval::SelfEvolutionSelectionRequestV1;
use codex_hepta_agent_components::intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_agent_components::intelligence_eval::VerifiedSelfEvolutionSelectionV1;
use codex_hepta_agent_components::intelligence_eval::admit_self_evolution_rollback_v1;
use codex_hepta_agent_components::intelligence_eval::admit_self_evolution_selection_v1;
use codex_hepta_agent_components::intelligence_eval::freeze_cross_fold_plan_v2;
use codex_hepta_agent_components::intelligence_eval::future_window_signing_payload_v1;
use codex_hepta_agent_components::intelligence_eval::longitudinal_evaluation_signing_payload_v3;
use codex_hepta_agent_components::intelligence_eval::prepare_self_evolution_selection_v1;
use codex_hepta_agent_components::intelligence_eval::rollback_signing_payload_v1;
use codex_hepta_agent_components::intelligence_eval::selection_signing_payload_v1;
use codex_hepta_agent_components::learning_artifacts::ArtifactEvent;
use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
use codex_hepta_agent_components::learning_artifacts::ArtifactManifest;
use codex_hepta_agent_components::learning_artifacts::ArtifactRegistry;
use codex_hepta_agent_components::learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_agent_components::learning_artifacts::write_candidate_payload;
use codex_hepta_agent_components::learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_agent_components::learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::TrustedLearningSignerV1;
use codex_hepta_agent_components::learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_supervisor::DurableRuntimeModuleSupervisorV1;

const EVAL_NOW: u64 = 5_000;
const FREEZE_TIME: u64 = 1_000;
const OBSERVER_TIME: u64 = 4_500;
const MINIMUM_WINDOW: u64 = 1_000;

struct EvolutionSigningFixture {
    verifier: LearningEvidenceVerifierV1,
    keys: [SigningKey; 4],
    principals: [AuthenticatedPrincipalV1; 4],
}

impl EvolutionSigningFixture {
    fn new(objective_digest: Digest32) -> Self {
        let scope = digest("self-evolution:scope");
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
            SigningKey::from_bytes(&[33; 32]),
            SigningKey::from_bytes(&[44; 32]),
        ];
        let identities = [
            (
                "generator.product",
                "controller.generator",
                LearningEvidenceRoleV1::Generator,
            ),
            (
                "evaluator.independent",
                "controller.evaluator",
                LearningEvidenceRoleV1::Evaluator,
            ),
            (
                "observer.independent",
                "controller.observer",
                LearningEvidenceRoleV1::Observer,
            ),
            (
                "selector.independent",
                "controller.selector",
                LearningEvidenceRoleV1::Selector,
            ),
        ];
        let principals = std::array::from_fn(|index| AuthenticatedPrincipalV1 {
            principal_id: id(identities[index].0),
            credential_chain_digest: digest(&format!("credential:{}", identities[index].0)),
            signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
            scope_digest: scope,
            authority_epoch: 23,
            authenticated_at: 100,
            expires_at: 10_000,
        });
        let signers = identities
            .iter()
            .enumerate()
            .map(|(index, (_, controller, role))| TrustedLearningSignerV1 {
                principal: principals[index].clone(),
                controller_id: id(controller),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![*role],
                revoked_at: None,
            })
            .collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest,
            authority_epoch: 23,
            signers,
        })
        .expect("independent learning trust");
        Self {
            verifier,
            keys,
            principals,
        }
    }

    fn sign(
        &self,
        index: usize,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
        issued_at: u64,
        objective_digest: Digest32,
        label: &str,
    ) -> SignedLearningEvidenceV1 {
        let principal = &self.principals[index];
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("evidence:{label}")),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest,
            authority_epoch: principal.authority_epoch,
            issued_at,
            expires_at: 9_000,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
}

fn fold(index: u8, final_window: &StableId) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(&format!("fold.product.{index}")),
        training_principals: vec![id(&format!("train.principal.{index}"))],
        training_episodes: vec![id(&format!("train.episode.{index}"))],
        training_windows: vec![id(&format!("train.window.{index}"))],
        holdout_principals: vec![id(&format!("holdout.principal.{index}"))],
        holdout_episodes: vec![id(&format!("holdout.episode.{index}"))],
        holdout_windows: if index == 2 {
            vec![final_window.clone()]
        } else {
            vec![id("future.window.1")]
        },
        model_digest: digest(&format!("fold:model:{index}")),
        predictions_digest: digest(&format!("fold:predictions:{index}")),
    }
}

fn verified_selection(
    ledger: &codex_hepta_agent_components::learning_ledger::LedgerSnapshot,
    dataset: &codex_hepta_agent_components::learning_ledger::DatasetSnapshotReceiptV3,
    baseline_digest: Digest32,
    candidate_digest: Digest32,
    candidate_id: StableId,
) -> (VerifiedSelfEvolutionSelectionV1, EvolutionSigningFixture) {
    let objective_digest = dataset.snapshot.objective_digest;
    let signing = EvolutionSigningFixture::new(objective_digest);
    let final_window = id("future.window.2");
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("metric.product.utility"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::from_raw(5),
        },
    }];
    let frozen_plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("plan.product.self-evolution"),
            claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
            candidate_id: candidate_id.clone(),
            baseline_id: id("artifact.baseline"),
            objective_digest,
            dataset_digest: dataset.snapshot.dataset_digest,
            estimand_digest: digest("estimand.product"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("metric.product.utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(70)),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![fold(1, &final_window), fold(2, &final_window)],
            final_holdout_window_id: final_window.clone(),
            final_holdout_digest: digest("holdout.product.final"),
        },
        roles.clone(),
    )
    .expect("freeze product evaluation plan");
    let holdout_use = FinalHoldoutRegistry::new()
        .consume(&frozen_plan)
        .expect("consume final holdout exactly once");
    let bundle = IndependentEvaluationBundleV1 {
        evaluation_id: id("evaluation.product.self-evolution"),
        candidate_id: candidate_id.clone(),
        baseline_id: id("artifact.baseline"),
        claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
        generator: signing.principals[0].clone(),
        evaluator: signing.principals[1].clone(),
        frozen_plan,
        holdout_use,
        objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        estimand_digest: digest("estimand.product"),
        estimate_receipt_digest: digest("estimate.product"),
        support_audit_digest: digest("support.product"),
        confidence_receipt_digest: digest("confidence.product"),
        retention_receipt_digests: vec![digest("retention.product")],
        unlearning_receipt_digest: digest("unlearning.product"),
        snapshot_ids: vec![
            id("snapshot.product.1"),
            id("snapshot.product.2"),
            id("snapshot.product.3"),
        ],
        future_window_ids: vec![id("future.window.1"), final_window],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricGateV1 {
            metric_id: id("metric.product.utility"),
            direction: EvaluationDirectionV1::Maximize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(100),
                upper: FixedQ32::from_raw(110),
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(80),
                upper: FixedQ32::from_raw(90),
            },
            safety_floor: Some(FixedQ32::from_raw(70)),
            support_digest: digest("metric.product.support"),
        }],
    };
    let placeholder = signing.sign(
        2,
        LearningEvidenceRoleV1::Observer,
        b"placeholder",
        OBSERVER_TIME,
        objective_digest,
        "observer-placeholder",
    );
    let mut timing = LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: FREEZE_TIME,
        windows: vec![
            ObservedFutureWindowV1 {
                window_id: id("future.window.1"),
                snapshot_id: id("snapshot.product.1"),
                starts_unix_micros: 1_100,
                ends_unix_micros: 2_100,
                observation_count: 16,
                observed_source_cut: digest("source.cut.1"),
            },
            ObservedFutureWindowV1 {
                window_id: id("future.window.2"),
                snapshot_id: id("snapshot.product.3"),
                starts_unix_micros: 2_200,
                ends_unix_micros: 3_200,
                observation_count: 16,
                observed_source_cut: digest("source.cut.2"),
            },
        ],
        observer: placeholder,
    };
    let observer_payload = future_window_signing_payload_v1(&bundle, &timing, MINIMUM_WINDOW)
        .expect("observer payload");
    timing.observer = signing.sign(
        2,
        LearningEvidenceRoleV1::Observer,
        &observer_payload,
        OBSERVER_TIME,
        objective_digest,
        "observer",
    );
    let generator = signing.sign(
        0,
        LearningEvidenceRoleV1::Generator,
        bundle.frozen_plan.plan_digest.as_array(),
        FREEZE_TIME,
        objective_digest,
        "generator",
    );
    let evaluator_payload =
        longitudinal_evaluation_signing_payload_v3(&bundle, &roles, &timing, MINIMUM_WINDOW)
            .expect("longitudinal evaluator payload");
    let evaluator = signing.sign(
        1,
        LearningEvidenceRoleV1::Evaluator,
        &evaluator_payload,
        OBSERVER_TIME,
        objective_digest,
        "evaluator",
    );
    let evaluation_evidence = SignedEvaluationEvidenceV1 {
        generator_plan: generator,
        evaluator_bundle: evaluator,
    };
    let prepared = prepare_self_evolution_selection_v1(
        &SelfEvolutionSelectionPolicyV1 {
            no_change_baseline_id: id("artifact.baseline"),
            no_change_baseline_digest: baseline_digest,
            minimum_dataset_records: 2,
            minimum_future_window_micros: MINIMUM_WINDOW,
        },
        SelfEvolutionSelectionRequestV1 {
            selection_id: id("selection.product.self-evolution"),
            predecessor_id: id("artifact.baseline"),
            predecessor_generation: generation(1),
            predecessor_artifact_digest: baseline_digest,
            candidate_id,
            candidate_generation: generation(2),
            candidate_artifact_digest: candidate_digest,
        },
        bundle,
        roles,
        &evaluation_evidence,
        &timing,
        dataset,
        ledger,
        &signing.verifier,
        EVAL_NOW,
    )
    .expect("prepare independently evaluated selection");
    let selector_payload =
        selection_signing_payload_v1(prepared.receipt()).expect("selector payload");
    let selector = signing.sign(
        3,
        LearningEvidenceRoleV1::Selector,
        &selector_payload,
        4_700,
        objective_digest,
        "selector",
    );
    let selected =
        admit_self_evolution_selection_v1(prepared, &selector, &signing.verifier, EVAL_NOW)
            .expect("admit independent selector");
    (selected, signing)
}

fn module_abi(
    generation_value: u64,
    implementation: Digest32,
    predecessor: Option<(u64, Digest32)>,
) -> RuntimeModuleAbiV1 {
    RuntimeModuleAbiV1 {
        module_id: id("module.product.self-evolution"),
        owner_id: id("owner.product.self-evolution"),
        generation: generation(generation_value),
        implementation_digest: implementation,
        candidate_artifact_digest: implementation,
        predecessor_generation: predecessor.map(|(value, _)| generation(value)),
        rollback_predecessor_digest: predecessor.map_or(Digest32::ZERO, |(_, digest)| digest),
        state_class: RuntimeModuleStateClassV1::Stateless,
        dependencies: Vec::new(),
        input_ports: Vec::new(),
        output_ports: Vec::new(),
        authoritative_domains: BTreeSet::new(),
        effect_scope: BTreeSet::new(),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_product_request_drives_signed_future_window_candidate_promotion_and_rollback() {
    let (fixture, evaluation_trust) = super::signed::signed_fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("product runner")
        .with_evaluation_trust(evaluation_trust)
        .expect("host-root evaluation trust");
    let mut coordinator = product_test_coordinator();
    let admitted = runner
        .prepare_and_admit(&mut coordinator, fixture.request, fixture.inputs)
        .await
        .expect("ordinary product admission");
    let AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    } = admitted
    else {
        panic!("ordinary selected product request must be admitted");
    };
    let dispatched = coordinator
        .mark_dispatched(
            wall_clock_ms().expect("wall clock"),
            &run_receipt.run_id,
            run_receipt.revision,
        )
        .expect("durable dispatch transition");

    let ledger_path = temp.path().join("product-learning-ledger");
    let ledger_binding = digest("product:self-evolution:ledger-binding");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("create product ledger");
    let mut ledger = DurableLedger::create(file, ledger_binding, 32).expect("product ledger");
    let decision = runner
        .append_decision(
            &mut ledger,
            Digest32::ZERO,
            &prepared,
            id("episode.product.self-evolution"),
            id("intuition.policy"),
        )
        .expect("append product decision");
    let observed = runner
        .append_outcome(
            &mut ledger,
            decision.chain_digest,
            &prepared,
            id("outcome-record.product.self-evolution"),
            id("outcome.product.self-evolution"),
            id("episode.product.self-evolution"),
            id("observer.product.outcome"),
            FixedQ32::ONE,
            OutcomeFinality::Terminal,
            digest("product:terminal-observation"),
        )
        .expect("append independently observed product outcome");
    coordinator
        .observe_terminal(
            &dispatched.run_id,
            dispatched.revision,
            RunPhase::Succeeded,
            true,
        )
        .expect("terminal product observation");

    let ledger_snapshot = ledger.snapshot().expect("ledger snapshot");
    assert_eq!(ledger_snapshot.head_digest, observed.chain_digest);
    let mut source_record_digests = ledger_snapshot
        .records()
        .iter()
        .map(|record| record.event_digest)
        .collect::<Vec<_>>();
    source_record_digests.sort_unstable();
    let objective_digest = prepared.envelope.objective_digest;
    let dataset = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset.product.self-evolution"),
            producer: AuthenticatedPrincipalV1 {
                principal_id: id("owner.product.dataset"),
                credential_chain_digest: digest("dataset:credential"),
                signing_key_digest: digest("dataset:key"),
                scope_digest: digest("dataset:scope"),
                authority_epoch: 23,
                authenticated_at: 100,
                expires_at: 10_000,
            },
            ledger_head_digest: ledger_snapshot.head_digest,
            objective_digest,
            eligible_frontier: 2,
            outcome_watermark: 2,
            correction_cut_digest: digest("dataset:correction-cut"),
            revocation_cut_digest: digest("dataset:revocation-cut"),
            inclusion_policy_digest: digest("dataset:inclusion-policy"),
            source_record_digests,
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        EVAL_NOW,
    )
    .expect("freeze dataset from product ledger");

    let baseline_bytes = b"stable product baseline";
    let candidate_bytes = b"candidate learned from product outcome";
    let baseline_digest = Digest32::of_bytes(baseline_bytes);
    let candidate_digest = Digest32::of_bytes(candidate_bytes);
    let candidate_id = id("artifact.candidate.product");
    let mut artifacts = ArtifactRegistry::new();
    for (event, manifest) in [
        (
            "artifact.event.baseline",
            ArtifactManifest {
                artifact_id: id("artifact.baseline"),
                kind: ArtifactKind::Policy,
                generation: generation(1),
                predecessor_id: None,
                content_digest: baseline_digest,
                objective_digest,
                support_digest: dataset.snapshot.dataset_digest,
                producer_id: id("learning.operator"),
                compatibility_digest: digest("artifact:compatibility"),
                encoded_size_bytes: baseline_bytes.len() as u64,
            },
        ),
        (
            "artifact.event.candidate",
            ArtifactManifest {
                artifact_id: candidate_id.clone(),
                kind: ArtifactKind::Policy,
                generation: generation(2),
                predecessor_id: Some(id("artifact.baseline")),
                content_digest: candidate_digest,
                objective_digest,
                support_digest: dataset.snapshot.dataset_digest,
                producer_id: id("learning.operator"),
                compatibility_digest: digest("artifact:compatibility"),
                encoded_size_bytes: candidate_bytes.len() as u64,
            },
        ),
    ] {
        artifacts
            .append(ArtifactEvent::Register {
                event_id: id(event),
                manifest,
            })
            .expect("register immutable learning artifact");
    }
    write_candidate_payload(
        CreateOnlyArtifactFile::create(temp.path().join("candidate.payload"))
            .expect("create candidate payload"),
        &artifacts,
        &candidate_id,
        candidate_bytes,
    )
    .expect("persist candidate artifact");

    let (selection, signing) = verified_selection(
        &ledger_snapshot,
        &dataset,
        baseline_digest,
        candidate_digest,
        candidate_id,
    );
    assert_eq!(selection.selector_id(), &id("selector.independent"));

    let state_file = temp.path().join("runtime-modules.json");
    let mut supervisor = DurableRuntimeModuleSupervisorV1::open(&state_file)
        .expect("open durable module supervisor");
    supervisor
        .register_bootstrap(module_abi(1, baseline_digest, None))
        .expect("activate no-change baseline");
    supervisor
        .register_selected_shadow(
            module_abi(2, candidate_digest, Some((1, baseline_digest))),
            &selection,
        )
        .expect("register independently selected shadow");
    supervisor
        .enter_canary(&id("module.product.self-evolution"), generation(2))
        .expect("enter canary");
    supervisor
        .promote_stateless(
            &id("module.product.self-evolution"),
            generation(2),
            digest("canary.product.passed"),
        )
        .expect("promote exact candidate");
    drop(supervisor);

    let mut restarted =
        DurableRuntimeModuleSupervisorV1::open(&state_file).expect("recover promoted topology");
    let active = restarted.topology().expect("healthy durable owner");
    assert_eq!(active.active.len(), 1);
    assert_eq!(active.active[0].generation, generation(2));
    assert_eq!(active.active[0].implementation_digest, candidate_digest);

    let regression = digest("future-window.product.regression");
    let rollback_payload =
        rollback_signing_payload_v1(&selection, regression).expect("rollback payload");
    let rollback_evidence = signing.sign(
        1,
        LearningEvidenceRoleV1::Evaluator,
        &rollback_payload,
        5_100,
        objective_digest,
        "rollback-evaluator",
    );
    let rollback = admit_self_evolution_rollback_v1(
        &selection,
        regression,
        &rollback_evidence,
        &signing.verifier,
        5_200,
    )
    .expect("independent rollback admission");
    restarted
        .rollback_verified(
            &id("module.product.self-evolution"),
            generation(2),
            &rollback,
        )
        .expect("rollback as a new generation");
    drop(restarted);

    let recovered =
        DurableRuntimeModuleSupervisorV1::open(&state_file).expect("recover rollback generation");
    let active = recovered.topology().expect("healthy durable owner");
    assert_eq!(active.active[0].generation, generation(3));
    assert_eq!(active.active[0].implementation_digest, baseline_digest);
    assert_eq!(
        recovered
            .checkpoint()
            .expect("healthy durable owner")
            .registry
            .generation_fences[0]
            .greatest_generation,
        generation(3)
    );

    // Exercise the full multi-module durable path with the SAME product-derived
    // dataset. Selection credentials remain fixtures, not deployment authority.
    let topology_path = temp.path().join("selected-topology.json");
    let mut topology_owner =
        DurableRuntimeModuleSupervisorV1::open(&topology_path).expect("topology owner");
    topology_owner
        .register_bootstrap(module_abi(1, baseline_digest, None))
        .expect("baseline module");
    let mut retiring = module_abi(1, digest("retiring-content"), None);
    retiring.module_id = id("module.retiring");
    topology_owner
        .register_bootstrap(retiring.clone())
        .expect("retiring sibling");
    let serving = topology_owner.topology().expect("serving topology");
    let mut candidate = codex_hepta_agent_components::types::RuntimeTopologyCandidateV1 {
        proposal_digest: digest("topology-proposal"),
        candidate_id: id("topology.product.candidate"),
        candidate_digest: Digest32::ZERO,
        baseline_generation: generation(1),
        candidate_generation: generation(2),
        selected_topology_digest: serving.digest,
        evaluation_digest: digest("topology-evaluation"),
        rollback_predecessor_digest: serving.digest,
        changed: true,
        deltas: vec![
            codex_hepta_agent_components::types::RuntimeTopologyDeltaV1 {
                module_id: id("module.product.self-evolution"),
                operation: codex_hepta_agent_components::types::RuntimeTopologyOperationV1::Replace,
                related_module_ids: Vec::new(),
                predecessor_digest: baseline_digest,
                candidate_digest,
                evidence_digest: digest("replace-evidence"),
            },
            codex_hepta_agent_components::types::RuntimeTopologyDeltaV1 {
                module_id: retiring.module_id.clone(),
                operation: codex_hepta_agent_components::types::RuntimeTopologyOperationV1::Retire,
                related_module_ids: Vec::new(),
                predecessor_digest: retiring.implementation_digest,
                candidate_digest: Digest32::ZERO,
                evidence_digest: digest("retire-evidence"),
            },
        ],
    };
    candidate.candidate_digest = candidate.content_digest().expect("bound topology content");
    let topology_digest = candidate.candidate_digest;
    let (topology_selection, _) = verified_selection(
        &ledger_snapshot,
        &dataset,
        serving.digest,
        topology_digest,
        candidate.candidate_id.clone(),
    );
    let mut successor = module_abi(2, candidate_digest, Some((1, baseline_digest)));
    successor.candidate_artifact_digest = topology_digest;
    topology_owner
        .register_selected_topology_candidate(candidate, vec![successor], &topology_selection)
        .expect("persist independently selected topology");
    let selected = topology_owner.checkpoint().expect("selected checkpoint");
    assert_eq!(selected.pending_topologies.len(), 1);
    drop(topology_owner);

    // Reopen at admission and again after per-member readiness. Neither cut may
    // expose a half-published topology or lose its retirement obligation.
    let mut topology_owner =
        DurableRuntimeModuleSupervisorV1::open(&topology_path).expect("recover selected topology");
    assert_eq!(topology_owner.checkpoint().expect("checkpoint"), selected);
    topology_owner
        .enter_topology_canary(topology_digest)
        .expect("persist canary");
    topology_owner
        .promote_stateless(
            &id("module.product.self-evolution"),
            generation(2),
            digest("topology-canary"),
        )
        .expect("stage member promotion");
    assert_eq!(
        topology_owner.topology().expect("not yet published"),
        serving
    );
    let staged = topology_owner.checkpoint().expect("staged checkpoint");
    assert!(
        topology_owner
            .finalize_topology_candidate(topology_digest)
            .is_err()
    );
    assert_eq!(
        topology_owner
            .checkpoint()
            .expect("semantic rejection remains healthy"),
        staged
    );
    drop(topology_owner);

    // Independent fixture copy exercises withdrawal. No serving product owner
    // or external effect is duplicated; both modules in this fixture are stateless.
    let withdrawal_path = temp.path().join("withdrawal-topology.json");
    std::fs::copy(&topology_path, &withdrawal_path).expect("copy isolated fixture");
    let mut withdrawal =
        DurableRuntimeModuleSupervisorV1::open(&withdrawal_path).expect("withdrawal owner");
    withdrawal
        .discard_topology_candidate(topology_digest)
        .expect("withdraw candidate");
    assert_eq!(withdrawal.topology().expect("baseline preserved"), serving);
    let withdrawn = withdrawal.checkpoint().expect("withdrawn checkpoint");
    assert!(withdrawn.pending_topologies.is_empty());
    assert_eq!(
        withdrawn.registry.generation_fences,
        staged.registry.generation_fences
    );
    drop(withdrawal);
    let withdrawal =
        DurableRuntimeModuleSupervisorV1::open(&withdrawal_path).expect("recover withdrawal");
    assert_eq!(
        withdrawal.checkpoint().expect("withdrawal remains durable"),
        withdrawn
    );

    let mut topology_owner =
        DurableRuntimeModuleSupervisorV1::open(&topology_path).expect("recover staged topology");
    assert_eq!(
        topology_owner.checkpoint().expect("staged checkpoint"),
        staged
    );
    topology_owner
        .record_retirement_ready(
            &retiring.module_id,
            generation(1),
            codex_hepta_supervisor::RuntimeModuleRetirementWitnessV1 {
                drain_digest: digest("stateless-drain"),
                reconciliation_digest: Digest32::ZERO,
                unknown_effect_count: 0,
            },
        )
        .expect("persist existing retirement witness");
    let published = topology_owner
        .finalize_topology_candidate(topology_digest)
        .expect("atomic durable publication");
    assert_eq!(published.active.len(), 1);
    assert_eq!(published.active[0].implementation_digest, candidate_digest);
    drop(topology_owner);
    let mut topology_owner =
        DurableRuntimeModuleSupervisorV1::open(&topology_path).expect("recover publication");
    assert_eq!(
        topology_owner.topology().expect("published topology"),
        published
    );
    assert!(topology_owner.register_bootstrap(retiring).is_err());
    assert_eq!(
        topology_owner
            .topology()
            .expect("retired generation stays fenced"),
        published
    );
}
