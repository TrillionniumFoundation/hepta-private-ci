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
    grammar: MutationGrammarManifestV1,
    profile: ParameterGeneratorProfileV3,
    generated: GeneratedParameterCandidateSetV3,
    admission: PlasticityAdmissionEvidenceV1,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
}

impl Fixture {
    fn new(evaluator_controller_collision: bool) -> Self {
        Self::new_with_collisions(evaluator_controller_collision, false)
    }

    fn new_with_observer_evaluator_collision() -> Self {
        Self::new_with_collisions(false, true)
    }

    fn new_with_collisions(
        evaluator_controller_collision: bool,
        observer_evaluator_controller_collision: bool,
    ) -> Self {
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
            SigningKey::from_bytes(&[33; 32]),
        ];
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("plasticity-signer-{index}")),
                credential_chain_digest: digest(&format!("plasticity-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("plasticity-scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("plasticity-scope"),
            objective_digest: digest("plasticity-objective"),
            authority_epoch: 7,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: if evaluator_controller_collision && index == 2 {
                        principals[0].principal_id.clone()
                    } else if observer_evaluator_controller_collision && index == 2 {
                        principals[1].principal_id.clone()
                    } else {
                        id(&format!("plasticity-controller-{index}"))
                    },
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

        let selected_artifact_digest = digest("selected-artifact");
        let window = ProposalWindowV2 {
            window_id: id("plasticity-window:1"),
            window_digest: digest("plasticity-window"),
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
            id("plasticity-grammar:1"),
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
        .expect("grammar");
        let generated = generate_parameter_candidates_v3(profile.clone()).expect("generate");
        let update_id = generated
            .candidates
            .iter()
            .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .expect("one update")
            .candidate_id
            .clone();
        let dataset_digest = digest("plasticity-dataset");
        let admission = PlasticityAdmissionEvidenceV1 {
            baseline_id: id("artifact:baseline"),
            objective_digest: digest("plasticity-objective"),
            selected_artifact_digest,
            artifact_registry_binding: digest("artifact-registry-binding"),
            artifact_registry_head_digest: digest("artifact-registry-head"),
            qualification_evidence_head_digest: digest("qualification-evidence-head"),
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
                plan_id: id("plasticity-plan"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: update_id.clone(),
                baseline_id: admission.baseline_id.clone(),
                objective_digest: admission.objective_digest,
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
                        fold_id: id(&format!("plasticity-fold-{index}")),
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
            evaluation_id: id("plasticity-evaluation"),
            candidate_id: update_id,
            baseline_id: admission.baseline_id.clone(),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            generator: principals[0].clone(),
            evaluator: principals[2].clone(),
            frozen_plan: plan,
            holdout_use,
            objective_digest: admission.objective_digest,
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
            grammar,
            profile,
            generated,
            admission,
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
            evidence_id: id(&format!("plasticity-attestation-{signer}")),
            principal_id: principal.principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: principal.scope_digest,
            objective_digest: self.admission.objective_digest,
            authority_epoch: 7,
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
            proposal_id: id("plasticity-proposal:1"),
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
            host_evidence_verification_digest: digest("host-evidence-verification"),
            expected_registry_predecessor: Digest32::ZERO,
        }
    }
}

#[derive(Default)]
struct AnchorCommitter {
    accept: bool,
    scope: Option<Digest32>,
    fence: Option<u64>,
    anchor: Option<DurableRegistryAnchorV1>,
}
impl PlasticityAnchorCommitterV1 for AnchorCommitter {
    fn persist_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        anchor: DurableRegistryAnchorV1,
    ) -> bool {
        if !self.accept {
            return false;
        }
        self.scope = Some(registry_scope_digest);
        self.fence = Some(writer_fence);
        self.anchor = Some(anchor);
        true
    }
}

fn writer() -> AnchoredPlasticityWriterV1 {
    AnchoredPlasticityWriterV1::bootstrap_new(
        tempfile().expect("tempfile"),
        digest("plasticity-registry-scope"),
        17,
        32,
    )
    .expect("writer")
}

#[test]
fn authenticated_product_path_generates_evaluates_appends_and_commits_anchor() {
    let fixture = Fixture::new(false);
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let receipt = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    )
    .expect("authenticated proposal");

    assert_eq!(receipt.proposal.proposer_id, fixture.principals[0].principal_id);
    assert_eq!(receipt.proposal.evaluator_id, fixture.principals[2].principal_id);
    assert!(!receipt.proposal.authority.grants_any());
    assert_eq!(writer.state(), PlasticityWriterStateV1::Healthy);
    assert_eq!(writer.record_count().expect("count"), 1);
    assert_eq!(anchor_committer.scope, Some(digest("plasticity-registry-scope")));
    assert_eq!(anchor_committer.fence, Some(17));
    assert_eq!(anchor_committer.anchor, Some(receipt.committed_registry_anchor));
}

#[test]
fn host_evidence_verification_digest_is_bound_into_final_proposal() {
    let fixture = Fixture::new(false);

    let mut first_writer = writer();
    let mut first_anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let first = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut first_writer,
        &mut first_anchor,
        50,
    )
    .expect("first proposal");

    let mut second_request = fixture.request();
    second_request.host_evidence_verification_digest = digest("different-host-evidence");
    let mut second_writer = writer();
    let mut second_anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let second = propose_authenticated_parameter_plasticity_v1(
        second_request,
        &fixture.verifier,
        &mut second_writer,
        &mut second_anchor,
        50,
    )
    .expect("second proposal");

    assert_ne!(first.proposal.evaluation_digest, second.proposal.evaluation_digest);
    assert_ne!(first.proposal.proposal_digest, second.proposal.proposal_digest);
}

#[test]
fn product_path_rejects_tampered_frontier_witness() {
    let fixture = Fixture::new(false);
    let mut request = fixture.request();
    request.admission.artifact_registry_head_digest = digest("tampered-head");
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let result = propose_authenticated_parameter_plasticity_v1(
        request,
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::AdmissionEvidence(
            SignedEvidenceError::PayloadMismatch
        ))
    ));
    assert_eq!(writer.record_count().expect("count"), 0);
}

#[test]
fn product_path_rejects_protected_parameter_even_with_valid_generator_bytes() {
    let fixture = Fixture::new(false);
    let mut request = fixture.request();
    request.generator_profile.signals[0].parameter_id = id("parameter:authority");
    request.generated = generate_parameter_candidates_v3(request.generator_profile.clone())
        .expect("raw generator can construct compatibility set");
    request.admission.generator_digest = request.generated.generator_digest;
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    assert!(matches!(
        propose_authenticated_parameter_plasticity_v1(
            request,
            &fixture.verifier,
            &mut writer,
            &mut anchor_committer,
            50,
        ),
        Err(ParameterPlasticityProductErrorV1::Grammar(
            MutationGrammarErrorV1::ProtectedParameterAllowed(_)
        ))
    ));
    assert_eq!(writer.record_count().expect("count"), 0);
}

#[test]
fn product_path_rejects_generator_evaluator_controller_collision() {
    let fixture = Fixture::new(true);
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let result = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::ControllerCollision)
        ))
    ));
    assert_eq!(writer.record_count().expect("count"), 0);
}

#[test]
fn product_path_rejects_observer_evaluator_controller_collision() {
    let fixture = Fixture::new_with_observer_evaluator_collision();
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let result = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::Evaluation(
            SignedEvaluationError::Evidence(SignedEvidenceError::ControllerCollision)
        ))
    ));
    assert_eq!(writer.record_count().expect("count"), 0);
}

#[test]
fn anchor_commit_failure_poison_writer_after_durable_append() {
    let fixture = Fixture::new(false);
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter::default();
    let result = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::AnchorPersistenceFailed)
    ));
    assert_eq!(writer.state(), PlasticityWriterStateV1::Poisoned);
    assert_eq!(writer.record_count(), Err(DurableProposalRegistryError::Poisoned));
}
