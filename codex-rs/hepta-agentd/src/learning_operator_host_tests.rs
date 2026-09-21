use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::VerifiedOperatorDatasetV2;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_bound_v2;
use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence::evaluated_candidate_signing_payload_v1;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::EvaluationIntervalV1;
use codex_hepta_intelligence_eval::FinalHoldoutRegistry;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricGateV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan_v2;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactLifecycleEventV1;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::LifecycleActorEvidenceV2;
use codex_hepta_learning_artifacts::LifecycleActorRoleV2;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::read_registry_snapshot;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::CognitiveContextItem;
use crate::cognitive_action_id;
use crate::cognitive_sensor_id;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000219").unwrap()
}

fn item(name: &str) -> CognitiveContextItem {
    CognitiveContextItem {
        memory_id: name.to_owned(),
        revision: 1,
        content: format!("lemon {name}"),
        content_sha256: digest(name).to_string(),
    }
}

struct CurrentView(Mutex<(PathBuf, RegistrySnapshotReceipt)>);

impl CurrentCognitiveRegistry for CurrentView {
    fn current(&self) -> Result<(File, RegistrySnapshotReceipt), String> {
        let guard = self.0.lock().map_err(|_| "view lock poisoned")?;
        Ok((
            File::open(&guard.0).map_err(|error| error.to_string())?,
            guard.1,
        ))
    }
}

struct EvaluationFixture {
    verifier: LearningEvidenceVerifierV1,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: SignedEvaluationEvidenceV1,
    candidate_evidence: SignedLearningEvidenceV1,
}

fn signed(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn principals_and_verifier() -> (
    [SigningKey; 2],
    Vec<AuthenticatedPrincipalV1>,
    LearningEvidenceVerifierV1,
) {
    let keys = [
        SigningKey::from_bytes(&[31; 32]),
        SigningKey::from_bytes(&[32; 32]),
    ];
    let principals = keys
        .iter()
        .enumerate()
        .map(|(index, key)| AuthenticatedPrincipalV1 {
            principal_id: id(&format!("operator-signer-{index}")),
            credential_chain_digest: digest(&format!("operator-credential-{index}")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 1,
            authenticated_at: 10,
            expires_at: 100,
        })
        .collect::<Vec<_>>();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: principals
            .iter()
            .zip(&keys)
            .enumerate()
            .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                principal: principal.clone(),
                controller_id: principal.principal_id.clone(),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![if index == 0 {
                    LearningEvidenceRoleV1::Generator
                } else {
                    LearningEvidenceRoleV1::Evaluator
                }],
                revoked_at: None,
            })
            .collect(),
    })
    .unwrap();
    (keys, principals, verifier)
}

fn frozen_dataset(
    principal: AuthenticatedPrincipalV1,
    objective_digest: Digest32,
    evidence: &[Digest32],
) -> DatasetSnapshotReceiptV3 {
    freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("operator-dataset"),
            producer: principal,
            ledger_head_digest: digest("ledger-head"),
            objective_digest,
            eligible_frontier: 1,
            outcome_watermark: 20,
            correction_cut_digest: digest("corrections"),
            revocation_cut_digest: digest("revocations"),
            inclusion_policy_digest: digest("inclusion"),
            source_record_digests: evidence.to_vec(),
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .unwrap()
}

fn evaluation_fixture(
    keys: &[SigningKey; 2],
    principals: &[AuthenticatedPrincipalV1],
    verifier: LearningEvidenceVerifierV1,
    dataset: &DatasetSnapshotReceiptV3,
    plan: &TabularOperatorPlanV1,
    candidate_bytes: &[u8],
) -> EvaluationFixture {
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("operator-metric"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let frozen_plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("operator-eval-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: plan.artifact_id.clone(),
            baseline_id: id("baseline"),
            objective_digest: plan.objective_digest,
            dataset_digest: dataset.snapshot.dataset_digest,
            estimand_digest: digest("estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("operator-metric"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: None,
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: (0..2)
                .map(|index| CrossFoldPartitionV1 {
                    fold_id: id(&format!("operator-fold-{index}")),
                    training_principals: vec![id("training-principal")],
                    training_episodes: vec![id("training-episode")],
                    training_windows: vec![id("training-window")],
                    holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                    holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                    holdout_windows: vec![id(&format!("holdout-window-{index}"))],
                    model_digest: Digest32::of_bytes(candidate_bytes),
                    predictions_digest: digest(&format!("predictions-{index}")),
                })
                .collect(),
            final_holdout_window_id: id("holdout-window-1"),
            final_holdout_digest: digest("final-holdout"),
        },
        roles.clone(),
    )
    .unwrap();
    let holdout_use = FinalHoldoutRegistry::new().consume(&frozen_plan).unwrap();
    let bundle = IndependentEvaluationBundleV1 {
        evaluation_id: id("operator-evaluation"),
        candidate_id: plan.artifact_id.clone(),
        baseline_id: id("baseline"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        generator: principals[0].clone(),
        evaluator: principals[1].clone(),
        frozen_plan,
        holdout_use,
        objective_digest: plan.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        estimand_digest: digest("estimand"),
        estimate_receipt_digest: digest("estimate"),
        support_audit_digest: digest("support"),
        confidence_receipt_digest: digest("confidence"),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
        snapshot_ids: vec![dataset.snapshot.snapshot_id.clone()],
        future_window_ids: vec![id("holdout-window-1")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricGateV1 {
            metric_id: id("operator-metric"),
            direction: EvaluationDirectionV1::Maximize,
            candidate: EvaluationIntervalV1 {
                lower: FixedQ32::ONE,
                upper: FixedQ32::ONE,
            },
            baseline: EvaluationIntervalV1 {
                lower: FixedQ32::ZERO,
                upper: FixedQ32::ZERO,
            },
            safety_floor: None,
            support_digest: digest("metric-support"),
        }],
    };
    let generator_plan = signed(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        bundle.frozen_plan.plan_digest.as_array(),
    );
    let evaluator_bundle = signed(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        &evaluation_signing_payload_v2(&bundle, &roles).unwrap(),
    );
    let candidate_evidence = signed(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        &evaluated_candidate_signing_payload_v1(
            &bundle,
            &roles,
            candidate_bytes,
            plan.generation.get(),
        )
        .unwrap(),
    );
    EvaluationFixture {
        verifier,
        bundle,
        roles,
        evidence: SignedEvaluationEvidenceV1 {
            generator_plan,
            evaluator_bundle,
        },
        candidate_evidence,
    }
}

fn complete_external_selection(
    journal: &mut ArtifactLifecycleJournalV2,
    producer_id: &StableId,
    artifact_id: &StableId,
    evaluation_digest: Digest32,
) {
    let transitions = [
        (
            "shadow-operator",
            LifecycleActorRoleV2::ShadowOperator,
            ArtifactLifecycleStateV1::Evaluated,
            ArtifactLifecycleStateV1::Shadow,
            digest("shadow"),
        ),
        (
            "canary-operator",
            LifecycleActorRoleV2::CanaryOperator,
            ArtifactLifecycleStateV1::Shadow,
            ArtifactLifecycleStateV1::Canary,
            digest("canary"),
        ),
        (
            "human-operator",
            LifecycleActorRoleV2::HumanOperator,
            ArtifactLifecycleStateV1::Canary,
            ArtifactLifecycleStateV1::OperatorAccepted,
            digest("operator-accepted"),
        ),
        (
            "selector",
            LifecycleActorRoleV2::Selector,
            ArtifactLifecycleStateV1::OperatorAccepted,
            ArtifactLifecycleStateV1::Selected,
            evaluation_digest,
        ),
    ];
    for (index, (actor_name, role, prior, next, evidence_digest)) in
        transitions.into_iter().enumerate()
    {
        let actor = LifecycleActorEvidenceV2 {
            actor_id: id(actor_name),
            credential_digest: digest(&format!("credential-{actor_name}")),
            role,
            authority_epoch: 1,
            verified_at: 10,
            expires_at: 100,
        };
        let occurred_at = 60 + u64::try_from(index).unwrap();
        journal
            .append(
                journal.head_digest(),
                producer_id,
                actor.clone(),
                ArtifactLifecycleEventV1 {
                    event_id: id(&format!("external-lifecycle-{index}")),
                    artifact_id: artifact_id.clone(),
                    prior_state: prior,
                    next_state: next,
                    actor_id: actor.actor_id.clone(),
                    actor_credential_digest: actor.credential_digest,
                    evidence_digest,
                    authority_epoch: actor.authority_epoch,
                    occurred_at,
                },
                occurred_at,
            )
            .unwrap();
    }
}

#[test]
fn coordination_journal_reopens_and_rejects_semantic_reuse() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("operator-coordination");
    File::create(&path).unwrap();
    let operation = id("operator-run");
    let request = digest("request");
    let first_head;
    {
        let mut journal = OfflineOperatorJournalV1::open(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&path)
                .unwrap(),
        )
        .unwrap();
        journal.prepare(operation.clone(), request).unwrap();
        journal
            .advance(
                &operation,
                request,
                OfflineOperatorPhaseV1::Trained,
                digest("trained"),
            )
            .unwrap();
        first_head = journal.head_digest();
    }
    let mut reopened = OfflineOperatorJournalV1::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(reopened.head_digest(), first_head);
    assert_eq!(
        reopened.prepare(operation, digest("different")),
        Err(OfflineOperatorJournalError::OperationConflict)
    );
}

#[test]
fn product_loop_requires_external_selection_then_reloads_into_agentd_consumer() {
    let directory = tempfile::tempdir().unwrap();
    let items = vec![item("one"), item("two")];
    let sensor = cognitive_sensor_id("lemon").unwrap();
    let actions = items
        .iter()
        .map(cognitive_action_id)
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let evidence = [
        digest("row-0-0"),
        digest("row-0-1"),
        digest("row-1-0"),
        digest("row-1-1"),
    ];
    let (keys, principals, verifier) = principals_and_verifier();
    let dataset = frozen_dataset(principals[0].clone(), digest("objective"), &evidence);
    let plan = TabularOperatorPlanV1 {
        artifact_id: id("policy"),
        producer_id: id("offline-operator-host"),
        generation: Generation::new(1).unwrap(),
        objective_digest: digest("objective"),
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: digest("sensor-core"),
        training_profile_digest: digest("agentd-ranker-profile"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![sensor.clone()],
        action_ids: actions.clone(),
        samples: actions
            .iter()
            .enumerate()
            .flat_map(|(action_index, action)| {
                let sensor = sensor.clone();
                [0_usize, 1].map(move |replicate| TabularOperatorSampleV1 {
                    sample_id: id(&format!("sample-{action_index}-{replicate}")),
                    sensor_id: sensor.clone(),
                    action_id: action.clone(),
                    target: FixedQ32::from_raw(if action_index == 0 { 0 } else { 10 }),
                    evidence_digest: evidence[action_index * 2 + replicate],
                })
            })
            .collect(),
    };
    let verified = VerifiedOperatorDatasetV2::from_receipt(&dataset, 50).unwrap();
    let expected_model = fit_tabular_operator_bound_v2(&verified, plan.clone()).unwrap();
    let expected_bytes = encode_tabular_payload_v1(&expected_model).unwrap();
    let eval = evaluation_fixture(
        &keys,
        &principals,
        verifier,
        &dataset,
        &plan,
        &expected_bytes,
    );

    let manifest = ArtifactManifest {
        artifact_id: plan.artifact_id.clone(),
        kind: ArtifactKind::Policy,
        generation: plan.generation,
        predecessor_id: None,
        content_digest: Digest32::of_bytes(&expected_bytes),
        objective_digest: plan.objective_digest,
        support_digest: plan.dataset_digest,
        producer_id: plan.producer_id.clone(),
        compatibility_digest: digest("ranker-consumer-v1"),
        encoded_size_bytes: expected_bytes.len() as u64,
    };
    let payload_path = directory.path().join("payload");
    let snapshot_path = directory.path().join("snapshot");
    let journal_path = directory.path().join("coordination");
    File::create(&journal_path).unwrap();
    let journal = OfflineOperatorJournalV1::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&journal_path)
            .unwrap(),
    )
    .unwrap();
    let mut host = AgentdOfflineOperatorHostV1::new(owner(), 1, journal).unwrap();
    let mut registry = ArtifactRegistry::new();
    let mut lifecycle = ArtifactLifecycleJournalV2::new();
    let producer_actor = LifecycleActorEvidenceV2 {
        actor_id: manifest.producer_id.clone(),
        credential_digest: digest("offline-operator-host-credential"),
        role: LifecycleActorRoleV2::Producer,
        authority_epoch: 1,
        verified_at: 10,
        expires_at: 100,
    };
    let evaluator_actor = LifecycleActorEvidenceV2 {
        actor_id: principals[1].principal_id.clone(),
        credential_digest: principals[1].credential_chain_digest,
        role: LifecycleActorRoleV2::Evaluator,
        authority_epoch: principals[1].authority_epoch,
        verified_at: principals[1].authenticated_at,
        expires_at: principals[1].expires_at,
    };
    let candidate = host
        .train_evaluate_publish(
            &mut registry,
            &mut lifecycle,
            &eval.verifier,
            OfflineOperatorCandidateRequestV1 {
                operation_id: id("product-operator-run"),
                dataset: &dataset,
                plan: plan.clone(),
                register_event_id: id("register-policy"),
                trained_lifecycle_event_id: id("trained-policy"),
                evaluated_lifecycle_event_id: id("evaluated-policy"),
                producer_actor: producer_actor.clone(),
                evaluator_actor: evaluator_actor.clone(),
                manifest: manifest.clone(),
                payload_target: OfflineOperatorPayloadTargetV1::Create(
                    CreateOnlyArtifactFile::create(&payload_path).unwrap(),
                ),
                registry_snapshot_target: CreateOnlyArtifactFile::create(&snapshot_path).unwrap(),
                registry_binding: digest("artifact-owner-binding"),
                evaluation: eval.bundle.clone(),
                metric_roles: eval.roles.clone(),
                evaluation_evidence: &eval.evidence,
                candidate_evidence: &eval.candidate_evidence,
                now: 50,
            },
        )
        .unwrap();
    assert_eq!(
        candidate.evaluation.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert_eq!(
        host.coordination_records().last().unwrap().phase,
        OfflineOperatorPhaseV1::EvaluatedEligible
    );

    assert_eq!(
        lifecycle.records().last().unwrap().event.next_state,
        ArtifactLifecycleStateV1::Evaluated
    );
    let view = Arc::new(CurrentView(Mutex::new((
        snapshot_path.clone(),
        candidate.selected_spec.registry_receipt,
    ))));
    assert!(
        host.load_selected_ranker(
            &candidate,
            &lifecycle,
            File::open(&snapshot_path).unwrap(),
            File::open(&payload_path).unwrap(),
            view.clone(),
        )
        .is_err()
    );
    drop(host);

    let lifecycle_snapshot = lifecycle.snapshot();
    let mut lifecycle = ArtifactLifecycleJournalV2::from_snapshot(lifecycle_snapshot, 50).unwrap();
    let mut registry = read_registry_snapshot(
        File::open(&snapshot_path).unwrap(),
        &candidate.selected_spec.registry_receipt,
    )
    .unwrap();
    let reopened_journal = OfflineOperatorJournalV1::open(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&journal_path)
            .unwrap(),
    )
    .unwrap();
    let mut fresh_host = AgentdOfflineOperatorHostV1::new(owner(), 1, reopened_journal).unwrap();
    let retry_snapshot_path = directory.path().join("snapshot-retry");
    let retry_candidate = fresh_host
        .train_evaluate_publish(
            &mut registry,
            &mut lifecycle,
            &eval.verifier,
            OfflineOperatorCandidateRequestV1 {
                operation_id: id("product-operator-run"),
                dataset: &dataset,
                plan,
                register_event_id: id("register-policy"),
                trained_lifecycle_event_id: id("trained-policy"),
                evaluated_lifecycle_event_id: id("evaluated-policy"),
                producer_actor,
                evaluator_actor,
                manifest: manifest.clone(),
                payload_target: OfflineOperatorPayloadTargetV1::Existing(
                    File::open(&payload_path).unwrap(),
                ),
                registry_snapshot_target: CreateOnlyArtifactFile::create(&retry_snapshot_path)
                    .unwrap(),
                registry_binding: digest("artifact-owner-binding"),
                evaluation: eval.bundle,
                metric_roles: eval.roles,
                evaluation_evidence: &eval.evidence,
                candidate_evidence: &eval.candidate_evidence,
                now: 50,
            },
        )
        .unwrap();
    assert_eq!(retry_candidate.request_digest, candidate.request_digest);
    assert_eq!(retry_candidate.model, candidate.model);
    assert_eq!(
        retry_candidate.coordination_head_digest,
        candidate.coordination_head_digest
    );
    assert_eq!(fresh_host.coordination_records().len(), 4);

    complete_external_selection(
        &mut lifecycle,
        &manifest.producer_id,
        &manifest.artifact_id,
        retry_candidate.evaluation.decision.evidence_digest,
    );
    let retry_view = Arc::new(CurrentView(Mutex::new((
        retry_snapshot_path.clone(),
        retry_candidate.selected_spec.registry_receipt,
    ))));
    let ranker = fresh_host
        .load_selected_ranker(
            &retry_candidate,
            &lifecycle,
            File::open(&retry_snapshot_path).unwrap(),
            File::open(&payload_path).unwrap(),
            retry_view,
        )
        .unwrap();
    let mut ranked = items.clone();
    ranker.rank(&owner(), 1, "lemon", &mut ranked).unwrap();
    assert_eq!(ranked, vec![items[1].clone(), items[0].clone()]);
    assert_eq!(
        fresh_host.coordination_records().last().unwrap().phase,
        OfflineOperatorPhaseV1::Reloaded
    );
}
