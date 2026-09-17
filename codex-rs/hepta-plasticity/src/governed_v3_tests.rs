use std::collections::BTreeMap;

use super::*;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::EvaluationIntervalV1;
use codex_hepta_intelligence_eval::FinalHoldoutRegistry;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricGateV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
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

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

#[derive(Clone, Default)]
struct MemoryResolver {
    values: BTreeMap<Digest32, Vec<u8>>,
}

impl MemoryResolver {
    fn insert(&mut self, bytes: impl Into<Vec<u8>>) -> Digest32 {
        let bytes = bytes.into();
        let digest = Digest32::of_bytes(&bytes);
        self.values.insert(digest, bytes);
        digest
    }
}

impl PlasticityEvidenceResolverV3 for MemoryResolver {
    fn resolve(
        &mut self,
        digest: Digest32,
    ) -> Result<Option<Vec<u8>>, PlasticityEvidenceResolveErrorV3> {
        Ok(self.values.get(&digest).cloned())
    }
}

struct Fixture {
    request: GovernedParameterProposalRequestV3,
    artifacts: ArtifactRegistry,
    resolver: MemoryResolver,
    verifier: LearningEvidenceVerifierV1,
    keys: [SigningKey; 3],
    principals: [AuthenticatedPrincipalV1; 3],
}

impl Fixture {
    fn new() -> Self {
        let objective = digest(b"objective:plasticity:v3");
        let scope = digest(b"scope:plasticity:v3");
        let keys = [
            SigningKey::from_bytes(&[41; 32]),
            SigningKey::from_bytes(&[42; 32]),
            SigningKey::from_bytes(&[43; 32]),
        ];
        let principals = [
            principal("generator", &keys[0], scope),
            principal("evaluator", &keys[1], scope),
            principal("observer", &keys[2], scope),
        ];
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 7,
            signers: vec![
                TrustedLearningSignerV1 {
                    principal: principals[0].clone(),
                    controller_id: id("controller:generator"),
                    verifying_key: keys[0].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: principals[1].clone(),
                    controller_id: id("controller:evaluator"),
                    verifying_key: keys[1].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Evaluator],
                    revoked_at: None,
                },
                TrustedLearningSignerV1 {
                    principal: principals[2].clone(),
                    controller_id: id("controller:observer"),
                    verifying_key: keys[2].verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Observer],
                    revoked_at: None,
                },
            ],
        })
        .expect("valid trust snapshot");

        let dataset = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("dataset:plasticity:v3"),
                producer: principals[0].clone(),
                ledger_head_digest: digest(b"ledger-head"),
                objective_digest: objective,
                eligible_frontier: 8,
                outcome_watermark: 20,
                correction_cut_digest: digest(b"correction-cut"),
                revocation_cut_digest: digest(b"revocation-cut"),
                inclusion_policy_digest: digest(b"inclusion-policy"),
                source_record_digests: vec![digest(b"source-record")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            50,
        )
        .expect("dataset receipt");

        let artifact_id = id("parameters:baseline:v3");
        let artifact_digest = digest(b"parameter-artifact:baseline:v3");
        let mut artifacts = ArtifactRegistry::new();
        artifacts
            .append(ArtifactEvent::Register {
                event_id: id("artifact-event:register:v3"),
                manifest: ArtifactManifest {
                    artifact_id: artifact_id.clone(),
                    kind: ArtifactKind::Parameters,
                    generation: generation(7),
                    predecessor_id: None,
                    content_digest: artifact_digest,
                    objective_digest: objective,
                    support_digest: digest(b"artifact-support"),
                    producer_id: principals[0].principal_id.clone(),
                    compatibility_digest: digest(b"artifact-compatibility"),
                    encoded_size_bytes: 4096,
                },
            })
            .expect("register parameter artifact");

        let mut resolver = MemoryResolver::default();
        let window_digest = resolver.insert(b"window-material".to_vec());
        let update_rule_digest = resolver.insert(b"update-rule-material".to_vec());
        let modulator_digest = resolver.insert(b"modulator-material".to_vec());
        let modulator_broadcast_digest = resolver.insert(b"broadcast-material".to_vec());
        let eligibility_digest = resolver.insert(b"eligibility-material".to_vec());
        let parameter_evidence_digest = resolver.insert(b"parameter-evidence-material".to_vec());

        let norm_layers = vec![LayerNormDenominatorV2 {
            layer_id: id("layer:plasticity:v3"),
            baseline_squared_l2_raw_q64: 1_000_000,
        }];
        let norm_payload = artifact_norm_profile_payload_v3(
            &artifact_id,
            artifact_digest,
            &norm_layers,
        )
        .expect("canonical norm payload");
        let norm_profile_evidence_digest = resolver.insert(norm_payload);

        let generator = ParameterGeneratorRequestV3 {
            proposal_id: id("proposal:governed:v3"),
            learning_rate: FixedQ32::from_raw(2),
            signals: vec![ParameterGeneratorSignalV3 {
                layer_id: id("layer:plasticity:v3"),
                parameter_id: id("parameter:plasticity:v3"),
                eligibility: FixedQ32::ONE,
                modulator_broadcast: FixedQ32::ONE,
                lower_bound: FixedQ32::from_raw(-10),
                upper_bound: FixedQ32::from_raw(10),
                evidence_digest: parameter_evidence_digest,
            }],
        };
        let generated = generate_parameter_candidates_v3(generator.clone()).expect("generated");
        let candidate_id = generated
            .candidates
            .iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("update candidate")
            .candidate_id
            .clone();

        let roles = vec![MetricRoleContractV2 {
            metric_id: id("metric:utility:v3"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let plan = freeze_cross_fold_plan_v2(
            CrossFoldPlanV1 {
                plan_id: id("eval-plan:plasticity:v3"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: candidate_id.clone(),
                baseline_id: artifact_id.clone(),
                objective_digest: objective,
                dataset_digest: dataset.snapshot.dataset_digest,
                estimand_digest: digest(b"estimand:plasticity:v3"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("metric:utility:v3"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: vec![
                    fold(0),
                    fold(1),
                ],
                final_holdout_window_id: id("holdout-window:1"),
                final_holdout_digest: digest(b"final-holdout"),
            },
            roles.clone(),
        )
        .expect("freeze evaluation plan");
        let holdout_use = FinalHoldoutRegistry::new()
            .consume(&plan)
            .expect("consume holdout");
        let evaluation = IndependentEvaluationBundleV1 {
            evaluation_id: id("evaluation:plasticity:v3"),
            candidate_id,
            baseline_id: artifact_id.clone(),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            generator: principals[0].clone(),
            evaluator: principals[1].clone(),
            frozen_plan: plan,
            holdout_use,
            objective_digest: objective,
            dataset_digest: dataset.snapshot.dataset_digest,
            estimand_digest: digest(b"estimand:plasticity:v3"),
            estimate_receipt_digest: digest(b"estimate-receipt"),
            support_audit_digest: digest(b"support-audit"),
            confidence_receipt_digest: digest(b"confidence-receipt"),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
            snapshot_ids: vec![dataset.snapshot.snapshot_id.clone()],
            future_window_ids: vec![id("holdout-window:1")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("metric:utility:v3"),
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
                support_digest: digest(b"metric-support"),
            }],
        };

        let request = GovernedParameterProposalRequestV3 {
            selected_artifact_id: artifact_id,
            window: ProposalWindowV2 {
                window_id: id("window:plasticity:v3"),
                window_digest,
            },
            update_rule_digest,
            modulator_digest,
            modulator_broadcast_digest,
            eligibility_digest,
            norm_profile_evidence_digest,
            norm_layers,
            generator,
            dataset,
            evaluation,
            metric_roles: roles,
        };

        Self {
            request,
            artifacts,
            resolver,
            verifier,
            keys,
            principals,
        }
    }

    fn attest(
        &self,
        prepared: &PreparedGovernedParameterProposalV3,
    ) -> GovernedParameterProposalAttestationsV3 {
        let evaluation_payload = evaluation_signing_payload_v2(
            &self.request.evaluation,
            &self.request.metric_roles,
        )
        .expect("evaluation signing payload");
        GovernedParameterProposalAttestationsV3 {
            generator: sign(
                &self.verifier,
                &self.principals[0],
                &self.keys[0],
                LearningEvidenceRoleV1::Generator,
                prepared.generator_payload(),
                self.request.evaluation.objective_digest,
            ),
            observer: sign(
                &self.verifier,
                &self.principals[2],
                &self.keys[2],
                LearningEvidenceRoleV1::Observer,
                prepared.observer_payload(),
                self.request.evaluation.objective_digest,
            ),
            evaluation: SignedEvaluationEvidenceV1 {
                generator_plan: sign(
                    &self.verifier,
                    &self.principals[0],
                    &self.keys[0],
                    LearningEvidenceRoleV1::Generator,
                    self.request.evaluation.frozen_plan.plan_digest.as_array(),
                    self.request.evaluation.objective_digest,
                ),
                evaluator_bundle: sign(
                    &self.verifier,
                    &self.principals[1],
                    &self.keys[1],
                    LearningEvidenceRoleV1::Evaluator,
                    &evaluation_payload,
                    self.request.evaluation.objective_digest,
                ),
            },
        }
    }
}

fn principal(name: &str, key: &SigningKey, scope: Digest32) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(&format!("principal:{name}")),
        credential_chain_digest: digest(format!("credential:{name}").as_bytes()),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 100,
    }
}

fn fold(index: usize) -> CrossFoldPartitionV1 {
    CrossFoldPartitionV1 {
        fold_id: id(&format!("fold:{index}")),
        training_principals: vec![id("training:principal")],
        training_episodes: vec![id("training:episode")],
        training_windows: vec![id("training:window")],
        holdout_principals: vec![id(&format!("holdout:principal:{index}"))],
        holdout_episodes: vec![id(&format!("holdout:episode:{index}"))],
        holdout_windows: vec![id(&format!("holdout:window:{index}"))],
        model_digest: digest(format!("model:{index}").as_bytes()),
        predictions_digest: digest(format!("predictions:{index}").as_bytes()),
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    objective_digest: Digest32,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence:{}:{role:?}", principal.principal_id)),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn governed_v3_requires_current_materialized_evidence_and_three_authenticated_roles() {
    let fixture = Fixture::new();
    let mut prepare_resolver = fixture.resolver.clone();
    let prepared = prepare_governed_parameter_proposal_v3(
        fixture.request.clone(),
        &fixture.artifacts,
        &mut prepare_resolver,
        50,
    )
    .expect("prepare governed proposal");
    let attestations = fixture.attest(&prepared);
    let mut admit_resolver = fixture.resolver.clone();
    let governed = admit_governed_parameter_proposal_v3(
        prepared,
        &attestations,
        &fixture.artifacts,
        &mut admit_resolver,
        &fixture.verifier,
        50,
    )
    .expect("admit governed proposal");

    assert_eq!(
        governed.proposal.proposer_id,
        fixture.principals[0].principal_id
    );
    assert_eq!(
        governed.proposal.evaluator_id,
        fixture.principals[1].principal_id
    );
    assert_eq!(governed.proposal.baseline_generation, generation(7));
    assert_eq!(governed.proposal.candidate_generation, generation(8));
    assert_eq!(governed.proposal.candidates.len(), 2);
    assert!(!governed.governance_digest.is_zero());
    assert!(!governed.authority.grants_any());
    assert!(!governed.proposal.authority.grants_any());
    assert_eq!(
        governed.proposal.status,
        ProposalStatus::RequiresIndependentAcceptance
    );
}

#[test]
fn governed_v3_fails_closed_when_named_evidence_is_missing() {
    let fixture = Fixture::new();
    let mut resolver = fixture.resolver.clone();
    resolver.values.remove(&fixture.request.eligibility_digest);
    assert!(matches!(
        prepare_governed_parameter_proposal_v3(
            fixture.request.clone(),
            &fixture.artifacts,
            &mut resolver,
            50,
        ),
        Err(GovernedParameterProposalErrorV3::EvidenceMissing(_))
    ));
}

#[test]
fn governed_v3_rechecks_artifact_lineage_between_prepare_and_admit() {
    let fixture = Fixture::new();
    let mut prepare_resolver = fixture.resolver.clone();
    let prepared = prepare_governed_parameter_proposal_v3(
        fixture.request.clone(),
        &fixture.artifacts,
        &mut prepare_resolver,
        50,
    )
    .expect("prepare governed proposal");
    let attestations = fixture.attest(&prepared);
    let mut quarantined = fixture.artifacts.clone();
    quarantined
        .append(ArtifactEvent::Quarantine(StateChange {
            event_id: id("artifact-event:quarantine:v3"),
            artifact_id: fixture.request.selected_artifact_id.clone(),
            evaluator_id: fixture.principals[1].principal_id.clone(),
            reason_digest: digest(b"qualification-quarantine"),
        }))
        .expect("quarantine selected artifact");
    let mut admit_resolver = fixture.resolver.clone();
    assert!(matches!(
        admit_governed_parameter_proposal_v3(
            prepared,
            &attestations,
            &quarantined,
            &mut admit_resolver,
            &fixture.verifier,
            50,
        ),
        Err(GovernedParameterProposalErrorV3::ArtifactIneligible)
    ));
}
