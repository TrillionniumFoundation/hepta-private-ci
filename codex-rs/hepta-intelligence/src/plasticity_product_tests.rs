use super::*;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::tempfile;

#[path = "plasticity_qualification_test_support.rs"]
mod qualification_support;

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
    profile: ParameterGeneratorProfileV3,
    generated: GeneratedParameterCandidateSetV3,
    admission: PlasticityAdmissionEvidenceV1,
    bundle: IndependentEvaluationBundleV1,
    qualification: ProductQualificationReceiptV1,
    roles: Vec<MetricRoleContractV2>,
}

impl Fixture {
    fn new(evaluator_controller_collision: bool) -> Self {
        Self::new_with_evaluator_controller(evaluator_controller_collision.then_some(0))
    }

    fn new_with_evaluator_controller(evaluator_controller_collision_with: Option<usize>) -> Self {
        Self::with_publication(
            evaluator_controller_collision_with,
            digest("plasticity-publication"),
        )
    }

    fn with_publication(
        evaluator_controller_collision_with: Option<usize>,
        publication_namespace: Digest32,
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
        let mut trust_definition = LearningEvidenceTrustV1 {
            scope_digest: digest("plasticity-scope"),
            objective_digest: digest("plasticity-objective"),
            authority_epoch: 7,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("plasticity-controller-{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![match index {
                        0 => LearningEvidenceRoleV1::Generator,
                        1 => LearningEvidenceRoleV1::Observer,
                        _ => LearningEvidenceRoleV1::Evaluator,
                    }],
                    revoked_at: None,
                })
                .collect(),
        };
        let qualification_verifier = LearningEvidenceVerifierV1::new(trust_definition.clone())
            .expect("qualification trust verifier");
        if let Some(other) = evaluator_controller_collision_with {
            trust_definition.signers[2].controller_id =
                id(&format!("plasticity-controller-{other}"));
        }
        let verifier = LearningEvidenceVerifierV1::new(trust_definition).expect("trust verifier");

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
            mutation_policy: build_parameter_mutation_policy_v1(
                id("grammar:product"),
                digest("mutation-grammar-manifest"),
                selected_artifact_digest,
                window.clone(),
                vec![ParameterMutationRuleV1 {
                    parameter_id: id("parameter:1"),
                    layer_id: id("layer:1"),
                    surface: ParameterMutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
                    maximum_delta: FixedQ32::from_raw(1_i64 << 24),
                }],
            )
            .expect("mutation grammar"),
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
            owner_evidence_set_digest: digest("owner-evidence-set"),
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
        let (runner, temporal) = qualification_support::evaluate(
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
            vec![id("plasticity-snapshot")],
            vec![id("holdout-window-1")],
        );
        let context = ProductQualificationContextV1 {
            generator: principals[0].clone(),
            evaluator: principals[2].clone(),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let bundle = runner
            .qualification_bundle(&temporal, &context)
            .expect("canonical bundle");
        // Qualify under independent fixture trust, then exercise any requested
        // current-use trust collision through the unchanged admission checks.
        let sign_qualification = |signer: usize, role: LearningEvidenceRoleV1, payload: &[u8]| {
            let principal = &principals[signer];
            let mut evidence = SignedLearningEvidenceV1 {
                evidence_id: id(&format!("plasticity-attestation-{signer}")),
                principal_id: principal.principal_id.clone(),
                role,
                trust_digest: qualification_verifier.trust_digest(),
                scope_digest: principal.scope_digest,
                objective_digest: admission.objective_digest,
                authority_epoch: 7,
                issued_at: 20,
                expires_at: 90,
                payload_digest: Digest32::of_bytes(payload),
                signature: [0; 64],
            };
            evidence.signature = keys[signer].sign(&evidence.signing_bytes()).to_bytes();
            evidence
        };
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign_qualification(
                /*signer*/ 0,
                LearningEvidenceRoleV1::Generator,
                bundle.frozen_plan.plan_digest.as_array(),
            ),
            evaluator_bundle: sign_qualification(
                /*signer*/ 2,
                LearningEvidenceRoleV1::Evaluator,
                &evaluation_signing_payload_v2(&bundle, &roles).expect("evaluation payload"),
            ),
        };
        let qualification = runner
            .qualify_and_persist(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &qualification_verifier,
                /*now*/ 50,
                &mut qualification_support::Sink(publication_namespace),
            )
            .expect("sealed qualification");
        assert_eq!(
            qualification.decision.decision.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        Self {
            keys,
            principals,
            verifier,
            profile,
            generated,
            admission,
            bundle,
            qualification,
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
        evidence.signature = self.keys[signer].sign(&evidence.signing_bytes()).to_bytes();
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
            &evaluation_signing_payload_v2(&self.bundle, &self.roles).expect("evaluation payload"),
        );
        ParameterPlasticityProductRequestV1 {
            proposal_id: id("plasticity-proposal:1"),
            generator_profile: self.profile.clone(),
            generated: self.generated.clone(),
            generator_attestation,
            admission: self.admission.clone(),
            admission_attestation,
            no_change_attestation: None,
            evaluations: vec![CandidateEvaluationAdmissionV1 {
                qualification: self.qualification.clone(),
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

    fn no_change_request(&self) -> ParameterPlasticityProductRequestV1 {
        let mut profile = self.profile.clone();
        // This exceeds the declared trust region, so deterministic generation
        // retains only the explicit no-change candidate.
        profile.signals[0].learning_rate = FixedQ32::ONE;
        let generated = generate_parameter_candidates_v3(profile.clone()).expect("no-change set");
        assert_eq!(generated.candidates.len(), 1);
        assert_eq!(
            generated.candidates[0].kind,
            ParameterCandidateKindV2::NoChange
        );

        let mut admission = self.admission.clone();
        admission.generator_digest = generated.generator_digest;
        let generator_attestation = self.sign(
            0,
            LearningEvidenceRoleV1::Generator,
            &parameter_generator_signing_payload_v3(&generated),
        );
        let admission_attestation = self.sign(
            1,
            LearningEvidenceRoleV1::Observer,
            &plasticity_admission_signing_payload_v1(&admission),
        );
        let terminal_payload = no_change_disposition_signing_payload_v1(&generated, &admission)
            .expect("terminal payload");
        let no_change_attestation =
            self.sign(2, LearningEvidenceRoleV1::Evaluator, &terminal_payload);

        ParameterPlasticityProductRequestV1 {
            proposal_id: id("plasticity-proposal:no-change"),
            generator_profile: profile,
            generated,
            generator_attestation,
            admission,
            admission_attestation,
            no_change_attestation: Some(no_change_attestation),
            evaluations: Vec::new(),
            expected_registry_predecessor: Digest32::ZERO,
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
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

    assert_eq!(
        receipt.proposal.proposer_id,
        fixture.principals[0].principal_id
    );
    assert_eq!(
        receipt.proposal.evaluator_id,
        fixture.principals[2].principal_id
    );
    assert!(!receipt.proposal.authority.grants_any());
    assert_eq!(
        receipt.disposition,
        ParameterPlasticityDispositionV1::UpdateCandidates
    );
    assert_eq!(writer.record_count().expect("count"), 1);
    assert_eq!(receipt.qualifications, vec![fixture.qualification.clone()]);
    assert_eq!(
        anchor_committer.scope,
        Some(digest("plasticity-registry-scope"))
    );
    assert_eq!(anchor_committer.fence, Some(17));
    assert_eq!(
        anchor_committer.anchor,
        Some(receipt.committed_registry_anchor)
    );
}

#[test]
fn no_admissible_update_is_independently_attested_and_durably_recorded() {
    let fixture = Fixture::new(false);
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let receipt = propose_authenticated_parameter_plasticity_v1(
        fixture.no_change_request(),
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        50,
    )
    .expect("durable no-change disposition");

    assert_eq!(
        receipt.disposition,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate
    );
    assert!(receipt.qualifications.is_empty());
    assert_eq!(receipt.proposal.candidates.len(), 1);
    assert_eq!(
        receipt.proposal.candidates[0].kind,
        ParameterCandidateKindV2::NoChange
    );
    assert_eq!(
        receipt.proposal.evaluator_id,
        fixture.principals[2].principal_id
    );
    assert_eq!(writer.record_count().expect("count"), 1);
    assert_eq!(
        anchor_committer.anchor,
        Some(receipt.committed_registry_anchor)
    );
}

#[test]
fn durable_v2_evaluation_digest_binds_governed_admission_context() {
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
    .expect("first governed proposal");

    let mut changed_request = fixture.request();
    changed_request.admission.owner_evidence_set_digest = digest("owner-evidence-set:changed");
    changed_request.admission_attestation = fixture.sign(
        1,
        LearningEvidenceRoleV1::Observer,
        &plasticity_admission_signing_payload_v1(&changed_request.admission),
    );
    let mut second_writer = writer();
    let mut second_anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let second = propose_authenticated_parameter_plasticity_v1(
        changed_request,
        &fixture.verifier,
        &mut second_writer,
        &mut second_anchor,
        50,
    )
    .expect("second governed proposal");

    assert_eq!(first.proposal.evaluation_digest, first.evaluation_digest);
    assert_eq!(second.proposal.evaluation_digest, second.evaluation_digest);
    assert_ne!(first.evaluation_digest, second.evaluation_digest);
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
    let fixture = Fixture::new_with_evaluator_controller(Some(1));
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
    assert_eq!(
        writer.record_count(),
        Err(DurableProposalRegistryError::Poisoned)
    );
}

#[test]
fn signed_generic_metrics_cannot_replace_the_product_qualification_before_append() {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut request = fixture.request();
    let evaluation = &mut request.evaluations[0];
    evaluation.bundle.metrics[0].candidate.upper =
        FixedQ32::from_raw(evaluation.bundle.metrics[0].candidate.upper.raw() + 1);
    evaluation.evidence.evaluator_bundle = fixture.sign(
        /*signer*/ 2,
        LearningEvidenceRoleV1::Evaluator,
        &evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles).unwrap(),
    );
    let mut writer = writer();
    let mut anchor_committer = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let before = anchor_committer.clone();
    let result = propose_authenticated_parameter_plasticity_v1(
        request,
        &fixture.verifier,
        &mut writer,
        &mut anchor_committer,
        /*now*/ 50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::Qualification(
            ProductEvaluationError::Binding("qualification use evidence")
        ))
    ));
    assert_eq!(writer.record_count().expect("count"), 0);
    assert_eq!(anchor_committer, before);
}

#[test]
fn durable_proposal_identity_commits_the_exact_qualification_publication() {
    let first = Fixture::new(/*evaluator_controller_collision*/ false);
    let second = Fixture::with_publication(
        /*evaluator_controller_collision_with*/ None,
        digest("second-publication"),
    );
    assert_eq!(first.qualification.decision, second.qualification.decision);
    assert_ne!(
        first.qualification.publication_digest,
        second.qualification.publication_digest
    );
    let mut first_writer = writer();
    let mut second_writer = writer();
    let mut first_anchor = AnchorCommitter {
        accept: true,
        ..AnchorCommitter::default()
    };
    let mut second_anchor = first_anchor.clone();
    let original = propose_authenticated_parameter_plasticity_v1(
        first.request(),
        &first.verifier,
        &mut first_writer,
        &mut first_anchor,
        /*now*/ 50,
    )
    .expect("first proposal");
    let other = propose_authenticated_parameter_plasticity_v1(
        second.request(),
        &second.verifier,
        &mut second_writer,
        &mut second_anchor,
        /*now*/ 50,
    )
    .expect("separately qualified publication");
    assert_ne!(original.evaluation_digest, other.evaluation_digest);
    assert_ne!(
        original.proposal.proposal_digest,
        other.proposal.proposal_digest
    );
    assert_eq!(original.qualifications, vec![first.qualification]);
    assert_eq!(other.qualifications, vec![second.qualification.clone()]);

    // A different publication cannot be replayed as the already committed
    // proposal identity, even though its raw decision and candidate are equal.
    let anchor_before = first_anchor.clone();
    assert!(
        propose_authenticated_parameter_plasticity_v1(
            second.request(),
            &second.verifier,
            &mut first_writer,
            &mut first_anchor,
            /*now*/ 50,
        )
        .is_err()
    );
    assert_eq!(first_writer.record_count().expect("count"), 1);
    assert_eq!(first_anchor, anchor_before);
}
