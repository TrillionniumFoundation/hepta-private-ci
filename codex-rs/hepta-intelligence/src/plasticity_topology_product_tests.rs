use super::*;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};
use ed25519_dalek::{Signer, SigningKey};
use tempfile::tempfile;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("generation {value}: {error}"))
}

struct Fixture {
    keys: [SigningKey; 3],
    principals: Vec<AuthenticatedPrincipalV1>,
    verifier: LearningEvidenceVerifierV1,
    policy: TopologyMutationPolicyV1,
    admission: TopologyPlasticityAdmissionEvidenceV1,
    changes: Vec<TopologyChangeV2>,
    handoffs: Vec<TopologyWriterHandoffV1>,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
}

impl Fixture {
    fn new() -> Self {
        let keys = [
            SigningKey::from_bytes(&[41; 32]),
            SigningKey::from_bytes(&[42; 32]),
            SigningKey::from_bytes(&[43; 32]),
        ];
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("topology-signer-{index}")),
                credential_chain_digest: digest(&format!("topology-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("topology-scope"),
                authority_epoch: 11,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("topology-scope"),
            objective_digest: digest("topology-objective"),
            authority_epoch: 11,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("topology-controller-{index}")),
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

        let selected = digest("topology-selected-artifact");
        let policy = build_topology_mutation_policy_v1(
            id("topology-policy:product"),
            selected,
            1,
            vec![ProtectedTopologyModuleV1 {
                module_id: id("learning.eval"),
                class: ProtectedTopologyClassV1::Evaluator,
            }],
        )
        .expect("topology policy");
        let admission = TopologyPlasticityAdmissionEvidenceV1 {
            baseline_id: id("artifact:topology:20"),
            objective_digest: digest("topology-objective"),
            selected_artifact_digest: selected,
            artifact_registry_binding: digest("topology-artifact-binding"),
            artifact_registry_head_digest: digest("topology-artifact-head"),
            qualification_evidence_head_digest: digest("topology-evidence-head"),
            topology_policy_digest: policy.policy_digest,
            window: ProposalWindowV2 {
                window_id: id("topology-window:1"),
                window_digest: digest("topology-window"),
            },
            baseline_generation: generation(20),
            candidate_generation: generation(21),
            dataset_digest: digest("topology-dataset"),
        };
        let handoff = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
            module_id: id("module:adaptive-head"),
            source_writer_id: id("writer:old"),
            destination_writer_id: id("writer:new"),
            source_domain_digest: digest("domain:old"),
            destination_domain_digest: digest("domain:new"),
            baseline_generation: admission.baseline_generation,
            candidate_generation: admission.candidate_generation,
            migration_digest: digest("topology-migration"),
            rollback_digest: digest("topology-rollback"),
            handoff_digest: Digest32::ZERO,
        })
        .expect("handoff");
        let changes = vec![TopologyChangeV2 {
            module_id: handoff.module_id.clone(),
            operation: TopologyOperationV2::Rewire,
            predecessor_digest: Some(digest("graph:20")),
            candidate_digest: Some(digest("graph:21")),
            migration_digest: handoff.migration_digest,
            rollback_digest: handoff.rollback_digest,
            writer_handoff_digest: handoff.handoff_digest,
            evidence_digest: digest("topology-change-evidence"),
        }];
        let provisional = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id("topology-proposal:fixture"),
            proposer_id: principals[0].principal_id.clone(),
            evaluator_id: principals[2].principal_id.clone(),
            selected_artifact_digest: admission.selected_artifact_digest,
            window: admission.window.clone(),
            baseline_generation: admission.baseline_generation,
            candidate_generation: admission.candidate_generation,
            evaluation_digest: digest("provisional-evaluation"),
            rollback_predecessor_digest: admission.selected_artifact_digest,
            changes: changes.clone(),
        })
        .expect("provisional topology proposal");
        let update_id = provisional
            .candidates
            .iter()
            .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
            .expect("topology update candidate")
            .candidate_id
            .clone();

        let roles = vec![MetricRoleContractV2 {
            metric_id: id("topology-metric"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let plan = freeze_cross_fold_plan_v2(
            CrossFoldPlanV1 {
                plan_id: id("topology-plan"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: update_id.clone(),
                baseline_id: admission.baseline_id.clone(),
                objective_digest: admission.objective_digest,
                dataset_digest: admission.dataset_digest,
                estimand_digest: digest("topology-estimand"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("topology-metric"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: (0..2)
                    .map(|index| CrossFoldPartitionV1 {
                        fold_id: id(&format!("topology-fold-{index}")),
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
            evaluation_id: id("topology-evaluation"),
            candidate_id: update_id,
            baseline_id: admission.baseline_id.clone(),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            generator: principals[0].clone(),
            evaluator: principals[2].clone(),
            frozen_plan: plan,
            holdout_use,
            objective_digest: admission.objective_digest,
            dataset_digest: admission.dataset_digest,
            estimand_digest: digest("topology-estimand"),
            estimate_receipt_digest: digest("estimate-receipt"),
            support_audit_digest: digest("support-audit"),
            confidence_receipt_digest: digest("confidence-receipt"),
            retention_receipt_digests: vec![],
            unlearning_receipt_digest: Digest32::ZERO,
            snapshot_ids: vec![id("topology-snapshot")],
            future_window_ids: vec![id("holdout-window-1")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("topology-metric"),
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
            policy,
            admission,
            changes,
            handoffs: vec![handoff],
            bundle,
            roles,
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
            evidence_id: id(&format!("topology-attestation-{signer}")),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: self.admission.objective_digest,
            authority_epoch: 11,
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

    fn request(&self) -> TopologyPlasticityProductRequestV1 {
        let generator_attestation = self.sign(
            0,
            LearningEvidenceRoleV1::Generator,
            &topology_generation_signing_payload_v1(
                &self.admission,
                &self.changes,
                &self.handoffs,
            )
            .expect("generator payload"),
        );
        let admission_attestation = self.sign(
            1,
            LearningEvidenceRoleV1::Observer,
            &topology_admission_signing_payload_v1(&self.admission)
                .expect("admission payload"),
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
        TopologyPlasticityProductRequestV1 {
            proposal_id: id("topology-proposal:1"),
            topology_policy: self.policy.clone(),
            changes: self.changes.clone(),
            handoffs: self.handoffs.clone(),
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
            expected_registry_predecessor: Digest32::ZERO,
        }
    }
}

#[derive(Default)]
struct AnchorCommitter {
    accept: bool,
    anchor: Option<DurableRegistryAnchorV1>,
}
impl PlasticityAnchorCommitterV1 for AnchorCommitter {
    fn persist_anchor(
        &mut self,
        _registry_scope_digest: Digest32,
        _writer_fence: u64,
        anchor: DurableRegistryAnchorV1,
    ) -> bool {
        if !self.accept {
            return false;
        }
        self.anchor = Some(anchor);
        true
    }
}

fn writer() -> AnchoredTopologyPlasticityWriterV1 {
    AnchoredTopologyPlasticityWriterV1::bootstrap_new(
        tempfile().expect("tempfile"),
        digest("topology-registry-scope"),
        31,
        16,
    )
    .expect("topology writer")
}

#[test]
fn authenticated_topology_path_evaluates_handoff_persists_and_commits_anchor() {
    let fixture = Fixture::new();
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let receipt = propose_authenticated_topology_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    )
    .expect("authenticated topology proposal");

    assert!(!receipt.proposal.authority.grants_any());
    assert!(!receipt.handoff_set_digest.is_zero());
    assert_eq!(writer.state(), PlasticityWriterStateV1::Healthy);
    assert_eq!(writer.record_count(), Ok(1));
    assert_eq!(anchor_committer.anchor, Some(receipt.committed_registry_anchor));
}

#[test]
fn authenticated_topology_rejects_protected_evaluator_surface_before_append() {
    let fixture = Fixture::new();
    let mut request = fixture.request();
    request.changes[0].module_id = id("learning.eval");
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let result = propose_authenticated_topology_plasticity_v1(
        request,
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(TopologyPlasticityProductErrorV1::Policy(
            TopologyMutationPolicyErrorV1::ProtectedModuleTargeted(module)
        )) if module == "learning.eval"
    ));
    assert_eq!(writer.record_count(), Ok(0));
    assert_eq!(anchor_committer.anchor, None);
}

#[test]
fn authenticated_topology_anchor_failure_poison_writer() {
    let fixture = Fixture::new();
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter::default();
    let result = propose_authenticated_topology_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(TopologyPlasticityProductErrorV1::AnchorPersistenceFailed)
    ));
    assert_eq!(writer.state(), PlasticityWriterStateV1::Poisoned);
    assert_eq!(
        writer.record_count(),
        Err(DurableTopologyProposalRegistryError::Poisoned)
    );
}
