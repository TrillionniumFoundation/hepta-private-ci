use std::fs::OpenOptions;

use codex_hepta_agentd::{
    AgentdPlasticityAnchorFenceStoreV1, AgentdPlasticityHostV1,
    PlasticityOwnerEvidenceErrorV1, PlasticityOwnerEvidenceKindV1,
    PlasticityOwnerEvidencePolicyV1, PlasticityOwnerEvidenceQueryV1,
    PlasticityOwnerEvidenceReceiptV1, PlasticityOwnerEvidenceResolverV1,
    artifact_frontier_binding_v1, plasticity_owner_evidence_query_digest_v1,
};
use codex_hepta_intelligence::{
    AnchoredPlasticityWriterV1, CandidateEvaluationAdmissionV1,
    ParameterPlasticityProductRequestV1, PlasticityAdmissionEvidenceV1,
    plasticity_admission_signing_payload_v1,
};
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::{ArtifactEvent, ArtifactKind, ArtifactManifest, ArtifactRegistry};
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};
use ed25519_dalek::{Signer, SigningKey};
use tempfile::{NamedTempFile, tempfile};

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("generation {value}: {error}"))
}
fn open_file(path: &std::path::Path) -> std::fs::File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("open host journal")
}

struct OwnerResolver {
    frontier: Digest32,
    stale: bool,
    owner_id: StableId,
    context_mismatch: bool,
}
impl PlasticityOwnerEvidenceResolverV1 for OwnerResolver {
    fn resolve(
        &self,
        query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<PlasticityOwnerEvidenceReceiptV1, PlasticityOwnerEvidenceErrorV1> {
        Ok(PlasticityOwnerEvidenceReceiptV1 {
            evidence_digest: query.evidence_digest,
            query_digest: if self.context_mismatch {
                digest("wrong-owner-query")
            } else {
                plasticity_owner_evidence_query_digest_v1(query)
            },
            owner_id: self.owner_id.clone(),
            owner_receipt_digest: Digest32::of_bytes(query.evidence_digest.as_array()),
            frontier_head_digest: self.frontier,
            observed_at: if self.stale { 1 } else { 40 },
            expires_at: if self.stale { 2 } else { 60 },
        })
    }
}

fn owner_policy(owner_id: StableId) -> PlasticityOwnerEvidencePolicyV1 {
    PlasticityOwnerEvidencePolicyV1::from_rules(vec![
        (PlasticityOwnerEvidenceKindV1::UpdateRule, owner_id.clone()),
        (PlasticityOwnerEvidenceKindV1::Modulator, owner_id.clone()),
        (
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            owner_id.clone(),
        ),
        (PlasticityOwnerEvidenceKindV1::Eligibility, owner_id.clone()),
        (PlasticityOwnerEvidenceKindV1::ParameterSignal, owner_id),
    ])
    .expect("owner policy")
}

struct Fixture {
    keys: [SigningKey; 3],
    principals: Vec<AuthenticatedPrincipalV1>,
    verifier: LearningEvidenceVerifierV1,
    artifacts: ArtifactRegistry,
    grammar: MutationGrammarManifestV1,
    profile: ParameterGeneratorProfileV3,
    generated: GeneratedParameterCandidateSetV3,
    admission: PlasticityAdmissionEvidenceV1,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    frontier: Digest32,
}

impl Fixture {
    fn new() -> Self {
        let selected_artifact_digest = digest("selected-artifact");
        let objective_digest = digest("plasticity-objective");
        let baseline_id = id("artifact:baseline");
        let mut artifacts = ArtifactRegistry::new();
        artifacts
            .append(ArtifactEvent::Register {
                event_id: id("artifact-event:baseline"),
                manifest: ArtifactManifest {
                    artifact_id: baseline_id.clone(),
                    kind: ArtifactKind::Parameters,
                    generation: generation(10),
                    predecessor_id: None,
                    content_digest: selected_artifact_digest,
                    objective_digest,
                    support_digest: digest("artifact-support"),
                    producer_id: id("artifact-producer"),
                    compatibility_digest: digest("artifact-compatibility"),
                    encoded_size_bytes: 1,
                },
            })
            .expect("register baseline artifact");
        let artifact_head = artifacts.snapshot().head_digest;
        let artifact_binding = artifact_frontier_binding_v1(
            artifacts.manifest(&baseline_id).expect("baseline manifest"),
            artifact_head,
        );

        let keys = [
            SigningKey::from_bytes(&[51; 32]),
            SigningKey::from_bytes(&[52; 32]),
            SigningKey::from_bytes(&[53; 32]),
        ];
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("host-plasticity-signer-{index}")),
                credential_chain_digest: digest(&format!("host-plasticity-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("plasticity-scope"),
                authority_epoch: 17,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("plasticity-scope"),
            objective_digest,
            authority_epoch: 17,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("host-plasticity-controller-{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![match index {
                        0 => LearningEvidenceRoleV1::Generator,
                        1 => LearningEvidenceRoleV1::Observer,
                        _ => LearningEvidenceRoleV1::Evaluator,
                    }],
                    revoked_at: None,
                })
                .collect(),
        })
        .expect("trust verifier");

        let window = ProposalWindowV2 {
            window_id: id("plasticity-window:host"),
            window_digest: digest("plasticity-window-host"),
        };
        let profile = ParameterGeneratorProfileV3 {
            selected_artifact_digest,
            window: window.clone(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            }],
            update_scales: vec![FixedQ32::ONE],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:1"),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::from_raw(1_i64 << 20),
                lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
                upper_bound: FixedQ32::from_raw(1_i64 << 24),
                evidence_digest: digest("parameter-evidence"),
            }],
        };
        let grammar = build_mutation_grammar_manifest_v1(
            id("plasticity-grammar:host"),
            selected_artifact_digest,
            1,
            vec![ParameterMutationRuleV1 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:1"),
                minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
                maximum_delta: FixedQ32::from_raw(1_i64 << 24),
            }],
            vec![ProtectedParameterV1 {
                parameter_id: id("parameter:authority"),
                class: ProtectedParameterClassV1::Authority,
            }],
        )
        .expect("mutation grammar");
        let generated = generate_parameter_candidates_v3(profile.clone()).expect("generate");
        let update_id = generated
            .candidates
            .iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("update candidate")
            .candidate_id
            .clone();
        let dataset_digest = digest("plasticity-dataset");
        let frontier = digest("qualification-evidence-frontier");
        let admission = PlasticityAdmissionEvidenceV1 {
            baseline_id: baseline_id.clone(),
            objective_digest,
            selected_artifact_digest,
            artifact_registry_binding: artifact_binding,
            artifact_registry_head_digest: artifact_head,
            qualification_evidence_head_digest: frontier,
            mutation_grammar_digest: grammar.manifest_digest,
            window,
            baseline_generation: generation(10),
            candidate_generation: generation(11),
            dataset_digest,
            update_rule_digest: digest("update-rule"),
            modulator_digest: digest("modulator"),
            modulator_broadcast_digest: digest("modulator-broadcast"),
            eligibility_digest: digest("eligibility"),
            generator_digest: generated.generator_digest,
        };

        let roles = vec![MetricRoleContractV2 {
            metric_id: id("plasticity-metric"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let plan = freeze_cross_fold_plan_v2(
            CrossFoldPlanV1 {
                plan_id: id("plasticity-host-plan"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: update_id.clone(),
                baseline_id: baseline_id.clone(),
                objective_digest,
                dataset_digest,
                estimand_digest: digest("plasticity-estimand"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("plasticity-metric"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: (0..2)
                    .map(|index| CrossFoldPartitionV1 {
                        fold_id: id(&format!("plasticity-host-fold-{index}")),
                        training_principals: vec![id("training-principal")],
                        training_episodes: vec![id("training-episode")],
                        training_windows: vec![id("training-window")],
                        holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                        holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                        holdout_windows: vec![id(&format!("holdout-window-{index}"))],
                        model_digest: digest("fold-model"),
                        predictions_digest: digest("fold-predictions"),
                    })
                    .collect(),
                final_holdout_window_id: id("holdout-window-1"),
                final_holdout_digest: digest("final-holdout"),
            },
            roles.clone(),
        )
        .expect("freeze plan");
        let holdout_use = FinalHoldoutRegistry::new()
            .consume(&plan)
            .expect("consume holdout");
        let bundle = IndependentEvaluationBundleV1 {
            evaluation_id: id("plasticity-host-evaluation"),
            candidate_id: update_id,
            baseline_id,
            claim_scope: EvaluationClaimScopeV1::Qualification,
            generator: principals[0].clone(),
            evaluator: principals[2].clone(),
            frozen_plan: plan,
            holdout_use,
            objective_digest,
            dataset_digest,
            estimand_digest: digest("plasticity-estimand"),
            estimate_receipt_digest: digest("estimate-receipt"),
            support_audit_digest: digest("support-audit"),
            confidence_receipt_digest: digest("confidence-receipt"),
            retention_receipt_digests: vec![],
            unlearning_receipt_digest: Digest32::ZERO,
            snapshot_ids: vec![id("plasticity-snapshot")],
            future_window_ids: vec![id("holdout-window-1")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("plasticity-metric"),
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

        Self {
            keys,
            principals,
            verifier,
            artifacts,
            grammar,
            profile,
            generated,
            admission,
            bundle,
            roles,
            frontier,
        }
    }

    fn sign(
        &self,
        signer: usize,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let principal = &self.principals[signer];
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("plasticity-host-attestation-{signer}")),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: self.admission.objective_digest,
            authority_epoch: 17,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[signer]
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    fn request(&self) -> ParameterPlasticityProductRequestV1 {
        let generator_attestation = self.sign(
            0,
            LearningEvidenceRoleV1::Generator,
            &parameter_generator_signing_payload_v3(&self.generated),
        );
        let admission_attestation = self.sign(
            1,
            LearningEvidenceRoleV1::Observer,
            &plasticity_admission_signing_payload_v1(&self.admission),
        );
        let generator_plan = self.sign(
            0,
            LearningEvidenceRoleV1::Generator,
            self.bundle.frozen_plan.plan_digest.as_array(),
        );
        let evaluator_bundle = self.sign(
            2,
            LearningEvidenceRoleV1::Evaluator,
            &evaluation_signing_payload_v2(&self.bundle, &self.roles)
                .expect("evaluation payload"),
        );
        ParameterPlasticityProductRequestV1 {
            proposal_id: id("plasticity-host-proposal:1"),
            mutation_grammar: self.grammar.clone(),
            generator_profile: self.profile.clone(),
            generated: self.generated.clone(),
            generator_attestation,
            admission: self.admission.clone(),
            admission_attestation,
            evaluations: vec![CandidateEvaluationAdmissionV1 {
                bundle: self.bundle.clone(),
                metric_roles: self.roles.clone(),
                evidence: SignedEvaluationEvidenceV1 {
                    generator_plan,
                    evaluator_bundle,
                },
            }],
            host_evidence_verification_digest: Digest32::ZERO,
            expected_registry_predecessor: Digest32::ZERO,
        }
    }
}

#[test]
fn agentd_host_resolves_owner_state_and_persists_governed_proposal() {
    let fixture = Fixture::new();
    let resolver = OwnerResolver {
        frontier: fixture.frontier,
        stale: false,
        owner_id: id("learning.owner"),
        context_mismatch: false,
    };
    let policy = owner_policy(id("learning.owner"));
    let host = AgentdPlasticityHostV1::new(&fixture.artifacts, &resolver, &policy);
    let registry_scope = digest("plasticity-registry-scope");
    let anchor_file = NamedTempFile::new().expect("anchor journal");
    let mut anchor_store = AgentdPlasticityAnchorFenceStoreV1::open(
        open_file(anchor_file.path()),
        registry_scope,
    )
    .expect("anchor/fence store");
    let fence = anchor_store
        .issue_new_registry_fence()
        .expect("new registry fence");
    let mut writer = AnchoredPlasticityWriterV1::bootstrap_new(
        tempfile().expect("proposal registry"),
        registry_scope,
        fence,
        32,
    )
    .expect("proposal writer");

    let receipt = host
        .propose_parameter_plasticity(
            fixture.request(),
            &fixture.verifier,
            &mut writer,
            &mut anchor_store,
            50,
        )
        .expect("governed Agentd proposal");

    assert!(!receipt.proposal.authority.grants_any());
    assert_eq!(writer.record_count(), Ok(1));
    assert_eq!(anchor_store.state().writer_fence, fence);
    assert_eq!(
        anchor_store.state().anchor,
        Some(receipt.committed_registry_anchor)
    );
}

#[test]
fn agentd_host_rejects_stale_owner_evidence_before_registry_append() {
    let fixture = Fixture::new();
    let resolver = OwnerResolver {
        frontier: fixture.frontier,
        stale: true,
        owner_id: id("learning.owner"),
        context_mismatch: false,
    };
    let policy = owner_policy(id("learning.owner"));
    let host = AgentdPlasticityHostV1::new(&fixture.artifacts, &resolver, &policy);
    let registry_scope = digest("plasticity-registry-scope:stale");
    let anchor_file = NamedTempFile::new().expect("anchor journal");
    let mut anchor_store = AgentdPlasticityAnchorFenceStoreV1::open(
        open_file(anchor_file.path()),
        registry_scope,
    )
    .expect("anchor/fence store");
    let fence = anchor_store
        .issue_new_registry_fence()
        .expect("new registry fence");
    let mut writer = AnchoredPlasticityWriterV1::bootstrap_new(
        tempfile().expect("proposal registry"),
        registry_scope,
        fence,
        32,
    )
    .expect("proposal writer");

    assert!(host
        .propose_parameter_plasticity(
            fixture.request(),
            &fixture.verifier,
            &mut writer,
            &mut anchor_store,
            50,
        )
        .is_err());
    assert_eq!(writer.record_count(), Ok(0));
    assert_eq!(anchor_store.state().anchor, None);
}

#[test]
fn agentd_host_rejects_wrong_evidence_owner_before_registry_append() {
    let fixture = Fixture::new();
    let resolver = OwnerResolver {
        frontier: fixture.frontier,
        stale: false,
        owner_id: id("unexpected.owner"),
        context_mismatch: false,
    };
    let policy = owner_policy(id("learning.owner"));
    let host = AgentdPlasticityHostV1::new(&fixture.artifacts, &resolver, &policy);
    let registry_scope = digest("plasticity-registry-scope:wrong-owner");
    let anchor_file = NamedTempFile::new().expect("anchor journal");
    let mut anchor_store =
        AgentdPlasticityAnchorFenceStoreV1::open(open_file(anchor_file.path()), registry_scope)
            .expect("anchor/fence store");
    let fence = anchor_store
        .issue_new_registry_fence()
        .expect("new registry fence");
    let mut writer = AnchoredPlasticityWriterV1::bootstrap_new(
        tempfile().expect("proposal registry"),
        registry_scope,
        fence,
        32,
    )
    .expect("proposal writer");

    let result = host.propose_parameter_plasticity(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_store,
        50,
    );
    assert!(matches!(
        result,
        Err(codex_hepta_agentd::AgentdPlasticityHostErrorV1::Evidence(
            PlasticityOwnerEvidenceErrorV1::Unauthorized
        ))
    ));
    assert_eq!(writer.record_count(), Ok(0));
    assert_eq!(anchor_store.state().anchor, None);
}

#[test]
fn agentd_host_rejects_owner_receipt_context_substitution() {
    let fixture = Fixture::new();
    let resolver = OwnerResolver {
        frontier: fixture.frontier,
        stale: false,
        owner_id: id("learning.owner"),
        context_mismatch: true,
    };
    let policy = owner_policy(id("learning.owner"));
    let host = AgentdPlasticityHostV1::new(&fixture.artifacts, &resolver, &policy);
    let registry_scope = digest("plasticity-registry-scope:context-mismatch");
    let anchor_file = NamedTempFile::new().expect("anchor journal");
    let mut anchor_store =
        AgentdPlasticityAnchorFenceStoreV1::open(open_file(anchor_file.path()), registry_scope)
            .expect("anchor/fence store");
    let fence = anchor_store
        .issue_new_registry_fence()
        .expect("new registry fence");
    let mut writer = AnchoredPlasticityWriterV1::bootstrap_new(
        tempfile().expect("proposal registry"),
        registry_scope,
        fence,
        32,
    )
    .expect("proposal writer");

    let result = host.propose_parameter_plasticity(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_store,
        50,
    );
    assert!(matches!(
        result,
        Err(codex_hepta_agentd::AgentdPlasticityHostErrorV1::Evidence(
            PlasticityOwnerEvidenceErrorV1::ContextMismatch
        ))
    ));
    assert_eq!(writer.record_count(), Ok(0));
    assert_eq!(anchor_store.state().anchor, None);
}
