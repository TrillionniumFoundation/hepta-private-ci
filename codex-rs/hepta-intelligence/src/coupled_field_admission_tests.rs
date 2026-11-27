use super::*;
use codex_hepta_intelligence_eval::CrossFoldPartitionV1;
use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::EvaluationClaimScopeV1;
use codex_hepta_intelligence_eval::EvaluationDirectionV1;
use codex_hepta_intelligence_eval::EvaluationIntervalV1;
use codex_hepta_intelligence_eval::FinalHoldoutRegistry;
use codex_hepta_intelligence_eval::MetricContractV1;
use codex_hepta_intelligence_eval::MetricGateV1;
use codex_hepta_intelligence_eval::MetricRoleV2;
use codex_hepta_intelligence_eval::freeze_cross_fold_plan_v2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterMutationRuleV1;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::build_parameter_mutation_policy_v1;
use codex_hepta_plasticity::coupled_field_v1::*;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn sid(s: impl Into<String>) -> StableId {
    StableId::new(s).unwrap()
}
fn hash(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
struct Owner {
    snap: CoupledFieldCurrentSnapshotV1,
    reads: usize,
    change: bool,
}
impl CoupledFieldCurrentOwnerPortV1 for Owner {
    fn current(&mut self, scope: &StableId, _now: u64) -> Result<CoupledFieldCurrentSnapshotV1, E> {
        if scope != &self.snap.scope_id {
            return Err(E::OwnerUnavailable);
        }
        self.reads += 1;
        let mut s = self.snap.clone();
        if self.change && self.reads > 1 {
            s.learning_ledger_head = hash("changed-live-ledger");
        }
        Ok(s)
    }
}
struct Fixture {
    keys: [SigningKey; 3],
    principals: Vec<AuthenticatedPrincipalV1>,
    verifier: LearningEvidenceVerifierV1,
    p: CoupledFieldProfileV1,
    g: GeneratedCoupledFieldV1,
    s: CoupledFieldCurrentSnapshotV1,
    bundles: Vec<IndependentEvaluationBundleV1>,
    roles: Vec<MetricRoleContractV2>,
}
impl Fixture {
    fn new(empty: bool, collision: Option<usize>) -> Self {
        // Test-only fixed keys and policy. No production credentials.
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
            SigningKey::from_bytes(&[33; 32]),
        ];
        let objective = hash("field-test-objective");
        let principals = keys
            .iter()
            .enumerate()
            .map(|(i, k)| AuthenticatedPrincipalV1 {
                principal_id: sid(format!("field-test-signer:{i}")),
                credential_chain_digest: hash(&format!("field-test-credential:{i}")),
                signing_key_digest: Digest32::of_bytes(&k.verifying_key().to_bytes()),
                scope_digest: hash("field-test-scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: hash("field-test-scope"),
            objective_digest: objective,
            authority_epoch: 7,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(i, (p, k))| TrustedLearningSignerV1 {
                    principal: p.clone(),
                    controller_id: sid(format!(
                        "field-test-controller:{}",
                        if i == 2 { collision.unwrap_or(i) } else { i }
                    )),
                    verifying_key: k.verifying_key().to_bytes(),
                    roles: vec![
                        [
                            LearningEvidenceRoleV1::Generator,
                            LearningEvidenceRoleV1::Observer,
                            LearningEvidenceRoleV1::Evaluator,
                        ][i],
                    ],
                    revoked_at: None,
                })
                .collect(),
        })
        .unwrap();
        let artifact = hash("field-test-parent");
        let layer = sid("layer:field-test");
        let parameter = sid("parameter:field-test");
        let window = ProposalWindowV2 {
            window_id: sid("window:field-test"),
            window_digest: hash("window-test"),
        };
        let lo = FixedQ32::from_raw(-25_000_000);
        let hi = FixedQ32::from_raw(25_000_000);
        let policy = build_parameter_mutation_policy_v1(
            sid("policy:field-test"),
            hash("test grammar"),
            artifact,
            window.clone(),
            vec![ParameterMutationRuleV1 {
                parameter_id: parameter.clone(),
                layer_id: layer.clone(),
                surface: ParameterMutationSurfaceV1::LearnableParameter,
                minimum_delta: lo,
                maximum_delta: hi,
            }],
        )
        .unwrap();
        let actions = if empty {
            vec![]
        } else {
            (0..2)
                .map(|i| FieldActionV1 {
                    action_id: sid(format!("action:test:{i}")),
                    solver_record_digest: hash(&format!("test solver record {i}")),
                    coefficient_pico: vec![vec![100_000_000 * (i + 1)]],
                })
                .collect()
        };
        let p = CoupledFieldProfileV1 {
            selected_artifact_digest: artifact,
            window,
            dataset_digest: hash("test training dataset"),
            objective_digest: objective,
            solver_digest: hash("test solver"),
            runtime_digest: hash("test runtime"),
            norm_evidence_digest: hash("test norm"),
            policy,
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: layer.clone(),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            }],
            path_budget: FixedQ32::from_raw(25_000_000),
            blocks: vec![FieldBlockV1 {
                owner_id: sid("owner:field-test"),
                layer_id: layer,
                owner_frontier_digest: hash("test frontier"),
                response_digest: hash("test response"),
                rank: 1,
                parameters: vec![FieldParameterV1 {
                    parameter_id: parameter,
                    lower: lo,
                    upper: hi,
                    basis_q52: vec![1_i64 << 52],
                }],
            }],
            actions,
        };
        let g = generate_coupled_field_v1(&p).unwrap();
        assert_eq!(g.candidates.len(), if empty { 1 } else { 3 });
        let roles = vec![MetricRoleContractV2 {
            metric_id: sid("metric:test"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let mut registry = FinalHoldoutRegistry::new();
        let mut bundles = Vec::new();
        let mut bindings = Vec::new();
        for (i, c) in g
            .candidates
            .iter()
            .filter(|x| x.kind == ParameterCandidateKindV2::Update)
            .enumerate()
        {
            let dataset = hash(&format!("test evaluation dataset {i}"));
            let hold = sid(format!("test:holdout:{i}:1"));
            let plan = freeze_cross_fold_plan_v2(
                CrossFoldPlanV1 {
                    plan_id: sid(format!("plan:field-test:{i}")),
                    claim_scope: EvaluationClaimScopeV1::Qualification,
                    candidate_id: c.candidate_id.clone(),
                    baseline_id: sid("artifact:field-test-baseline"),
                    objective_digest: objective,
                    dataset_digest: dataset,
                    estimand_digest: hash("test estimand"),
                    metric_contracts: vec![MetricContractV1 {
                        metric_id: sid("metric:test"),
                        direction: EvaluationDirectionV1::Maximize,
                        safety_floor: None,
                    }],
                    family_alpha_ppm: 50_000,
                    simultaneous_comparisons: 2,
                    folds: (0..2)
                        .map(|j| CrossFoldPartitionV1 {
                            fold_id: sid(format!("fold:{i}:{j}")),
                            training_principals: vec![sid("train:principal")],
                            training_episodes: vec![sid("train:episode")],
                            training_windows: vec![sid("train:window")],
                            holdout_principals: vec![sid(format!("holdout:principal:{i}:{j}"))],
                            holdout_episodes: vec![sid(format!("holdout:episode:{i}:{j}"))],
                            holdout_windows: vec![sid(format!("test:holdout:{i}:{j}"))],
                            model_digest: hash("test fold model"),
                            predictions_digest: hash("test fold prediction"),
                        })
                        .collect(),
                    final_holdout_window_id: hold.clone(),
                    final_holdout_digest: hash(&format!("test final holdout {i}")),
                },
                roles.clone(),
            )
            .unwrap();
            let use_receipt = registry.consume(&plan).unwrap();
            bindings.push(CoupledFieldCandidateBindingV1 {
                candidate_id: c.candidate_id.clone(),
                artifact_bytes_digest: hash(&format!("test artifact bytes {i}")),
                evaluation_dataset_digest: dataset,
                plan_digest: plan.plan_digest,
                holdout_use_digest: use_receipt.use_digest,
            });
            let v = if i == 0 {
                FixedQ32::ONE
            } else {
                FixedQ32::from_raw(-1)
            };
            bundles.push(IndependentEvaluationBundleV1 {
                evaluation_id: sid(format!("evaluation:field-test:{i}")),
                candidate_id: c.candidate_id.clone(),
                baseline_id: sid("artifact:field-test-baseline"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                generator: principals[0].clone(),
                evaluator: principals[2].clone(),
                frozen_plan: plan,
                holdout_use: use_receipt,
                objective_digest: objective,
                dataset_digest: dataset,
                estimand_digest: hash("test estimand"),
                estimate_receipt_digest: hash("test estimate"),
                support_audit_digest: hash("test support"),
                confidence_receipt_digest: hash("test confidence"),
                retention_receipt_digests: vec![],
                unlearning_receipt_digest: Digest32::ZERO,
                snapshot_ids: vec![sid("snapshot:test")],
                future_window_ids: vec![hold],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 2,
                metrics: vec![MetricGateV1 {
                    metric_id: sid("metric:test"),
                    direction: EvaluationDirectionV1::Maximize,
                    candidate: EvaluationIntervalV1 { lower: v, upper: v },
                    baseline: EvaluationIntervalV1 {
                        lower: FixedQ32::ZERO,
                        upper: FixedQ32::ZERO,
                    },
                    safety_floor: None,
                    support_digest: hash("test metric support"),
                }],
            });
        }
        let s = CoupledFieldCurrentSnapshotV1 {
            scope_id: sid("scope:field-test"),
            profile_digest: g.profile_digest,
            objective_digest: objective,
            selected_artifact_digest: artifact,
            baseline_id: sid("artifact:field-test-baseline"),
            baseline_generation: Generation::new(10).unwrap(),
            candidate_generation: Generation::new(11).unwrap(),
            artifact_registry_head: hash("test artifact head"),
            learning_ledger_head: hash("test ledger head"),
            owner_evidence_set: hash("test owner evidence"),
            budget_receipt: hash("test budget"),
            trust_digest: verifier.trust_digest(),
            valid_until: 80,
            updates: bindings,
        };
        Self {
            keys,
            principals,
            verifier,
            p,
            g,
            s,
            bundles,
            roles,
        }
    }
    fn sign(
        &self,
        i: usize,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let mut e = SignedLearningEvidenceV1 {
            evidence_id: sid(format!("field-test-attestation:{i}")),
            principal_id: self.principals[i].principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: self.verifier.scope_digest(),
            objective_digest: self.verifier.objective_digest(),
            authority_epoch: self.verifier.authority_epoch(),
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        e.signature = self.keys[i].sign(&e.signing_bytes()).to_bytes();
        e
    }
    fn request(&self) -> CoupledFieldAdmissionRequestV1 {
        let generator_attestation = self.sign(
            0,
            LearningEvidenceRoleV1::Generator,
            &coupled_field_generator_payload_v1(&self.s).unwrap(),
        );
        let observer_attestation = self.sign(
            1,
            LearningEvidenceRoleV1::Observer,
            &coupled_field_observer_payload_v1(&self.s).unwrap(),
        );
        let evaluations = self
            .bundles
            .iter()
            .zip(&self.s.updates)
            .map(|(b, k)| CoupledFieldEvaluationV1 {
                bundle: b.clone(),
                metric_roles: self.roles.clone(),
                evidence: SignedEvaluationEvidenceV1 {
                    generator_plan: self.sign(
                        0,
                        LearningEvidenceRoleV1::Generator,
                        b.frozen_plan.plan_digest.as_array(),
                    ),
                    evaluator_bundle: self.sign(
                        2,
                        LearningEvidenceRoleV1::Evaluator,
                        &evaluation_signing_payload_v2(b, &self.roles).unwrap(),
                    ),
                },
                artifact_attestation: self.sign(
                    2,
                    LearningEvidenceRoleV1::Evaluator,
                    &coupled_field_evaluation_artifact_payload_v1(&self.s, k, b, &self.roles)
                        .unwrap(),
                ),
            })
            .collect();
        let no_change_attestation = if self.s.updates.is_empty() {
            let n = self
                .g
                .candidates
                .iter()
                .find(|c| c.kind == ParameterCandidateKindV2::NoChange)
                .unwrap();
            Some(self.sign(
                2,
                LearningEvidenceRoleV1::Evaluator,
                &coupled_field_no_change_payload_v1(&self.s, &n.candidate_id).unwrap(),
            ))
        } else {
            None
        };
        CoupledFieldAdmissionRequestV1 {
            profile: self.p.clone(),
            generated: self.g.clone(),
            generator_attestation,
            observer_attestation,
            evaluations,
            no_change_attestation,
        }
    }
    fn admit(
        &self,
        r: CoupledFieldAdmissionRequestV1,
    ) -> Result<CoupledFieldAdmissionReceiptV1, E> {
        admit_authenticated_coupled_field_v1(
            r,
            &self.s.scope_id,
            &mut Owner {
                snap: self.s.clone(),
                reads: 0,
                change: false,
            },
            &self.verifier,
            50,
        )
    }
}
#[test]
fn field_mixed_family_preserves_negative_outcome_and_no_authority() {
    let f = Fixture::new(false, None);
    let r = f.admit(f.request()).unwrap();
    assert_eq!(r.profile_digest(), f.g.profile_digest);
    assert_eq!(r.evaluated().len(), 2);
    assert_eq!(
        r.evaluated()[0].disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert_eq!(
        r.evaluated()[1].disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert!(!r.no_eligible_update());
    assert!(!r.authority().grants_any());
}
#[test]
fn field_requires_every_evaluation_and_unique_ids() {
    let f = Fixture::new(false, None);
    let mut r = f.request();
    r.evaluations.pop();
    assert!(matches!(f.admit(r), Err(E::MissingEvaluation)));
    let mut r = f.request();
    r.evaluations.push(r.evaluations[0].clone());
    assert!(matches!(f.admit(r), Err(E::DuplicateEvaluation)));
}
#[test]
fn field_rejects_modified_family_even_with_valid_old_signatures() {
    let f = Fixture::new(false, None);
    let mut r = f.request();
    r.profile.actions[0].coefficient_pico[0][0] += 1;
    assert!(matches!(
        f.admit(r),
        Err(E::Field(FieldError::ExpectedProfileMismatch))
    ));
    let mut r = f.request();
    r.generated.candidates.pop();
    assert!(matches!(
        f.admit(r),
        Err(E::Field(FieldError::CandidateMismatch))
    ));
}
#[test]
fn field_rejects_artifact_signature_substitution() {
    let f = Fixture::new(false, None);
    let mut r = f.request();
    r.evaluations[0].artifact_attestation = r.evaluations[1].artifact_attestation.clone();
    assert!(matches!(
        f.admit(r),
        Err(E::Signature(SignedEvidenceError::PayloadMismatch))
    ));
    let mut r = f.request();
    r.evaluations[0].artifact_attestation.signature[0] ^= 1;
    assert!(matches!(
        f.admit(r),
        Err(E::Signature(SignedEvidenceError::InvalidSignature))
    ));
}
#[test]
fn field_requires_owner_currentness_at_both_reads() {
    let f = Fixture::new(false, None);
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: true,
    };
    assert!(matches!(
        admit_authenticated_coupled_field_v1(f.request(), &f.s.scope_id, &mut o, &f.verifier, 50),
        Err(E::CurrentChanged)
    ));
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: false,
    };
    o.snap.artifact_registry_head = hash("different actual head");
    assert!(matches!(
        admit_authenticated_coupled_field_v1(f.request(), &f.s.scope_id, &mut o, &f.verifier, 50),
        Err(E::Signature(SignedEvidenceError::PayloadMismatch))
    ));
}
#[test]
fn field_rejects_expired_snapshot_and_wrong_scope() {
    let f = Fixture::new(false, None);
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: false,
    };
    assert!(matches!(
        admit_authenticated_coupled_field_v1(f.request(), &f.s.scope_id, &mut o, &f.verifier, 81),
        Err(E::InvalidSnapshot)
    ));
    assert!(matches!(
        admit_authenticated_coupled_field_v1(
            f.request(),
            &sid("scope:other"),
            &mut o,
            &f.verifier,
            50
        ),
        Err(E::OwnerUnavailable)
    ));
}
#[test]
fn field_rejects_both_evaluator_controller_collisions() {
    for i in [0, 1] {
        let f = Fixture::new(false, Some(i));
        assert!(matches!(
            f.admit(f.request()),
            Err(E::Signature(SignedEvidenceError::ControllerCollision))
        ));
    }
}
#[test]
fn field_no_change_requires_independent_terminal_attestation() {
    let f = Fixture::new(true, None);
    let r = f.admit(f.request()).unwrap();
    assert!(r.no_eligible_update());
    assert!(r.evaluated().is_empty());
    assert!(!r.authority().grants_any());
    let mut r = f.request();
    r.no_change_attestation = None;
    assert!(matches!(f.admit(r), Err(E::MissingNoChange)));
}
#[test]
fn field_rejects_wrong_holdout_owner_binding() {
    let f = Fixture::new(false, None);
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: false,
    };
    o.snap.updates[0].holdout_use_digest = hash("different actual holdout use");
    let mut r = f.request();
    r.generator_attestation = f.sign(
        0,
        LearningEvidenceRoleV1::Generator,
        &coupled_field_generator_payload_v1(&o.snap).unwrap(),
    );
    r.observer_attestation = f.sign(
        1,
        LearningEvidenceRoleV1::Observer,
        &coupled_field_observer_payload_v1(&o.snap).unwrap(),
    );
    assert!(matches!(
        admit_authenticated_coupled_field_v1(r, &f.s.scope_id, &mut o, &f.verifier, 50),
        Err(E::Binding("evaluation lineage"))
    ));
}

#[test]
fn field_all_signed_ineligible_candidates_return_no_eligible_update() {
    let f = Fixture::new(false, None);
    let mut r = f.request();
    for (x, k) in r.evaluations.iter_mut().zip(&f.s.updates) {
        let v = FixedQ32::from_raw(-1);
        x.bundle.metrics[0].candidate = EvaluationIntervalV1 { lower: v, upper: v };
        x.evidence.evaluator_bundle = f.sign(
            2,
            LearningEvidenceRoleV1::Evaluator,
            &evaluation_signing_payload_v2(&x.bundle, &x.metric_roles).unwrap(),
        );
        x.artifact_attestation = f.sign(
            2,
            LearningEvidenceRoleV1::Evaluator,
            &coupled_field_evaluation_artifact_payload_v1(&f.s, k, &x.bundle, &x.metric_roles)
                .unwrap(),
        );
    }
    let a = f.admit(r).unwrap();
    assert!(a.no_eligible_update());
    assert_eq!(a.evaluated().len(), 2);
    assert!(
        a.evaluated()
            .iter()
            .all(|x| x.disposition == IndependentEvaluationDispositionV1::Ineligible)
    );
    assert!(!a.authority().grants_any());
}
#[test]
fn field_current_artifact_change_requires_fresh_evaluator_binding() {
    let f = Fixture::new(false, None);
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: false,
    };
    o.snap.updates[0].artifact_bytes_digest = hash("changed actual candidate materialization");
    let mut r = f.request();
    r.generator_attestation = f.sign(
        0,
        LearningEvidenceRoleV1::Generator,
        &coupled_field_generator_payload_v1(&o.snap).unwrap(),
    );
    r.observer_attestation = f.sign(
        1,
        LearningEvidenceRoleV1::Observer,
        &coupled_field_observer_payload_v1(&o.snap).unwrap(),
    );
    assert!(matches!(
        admit_authenticated_coupled_field_v1(r, &f.s.scope_id, &mut o, &f.verifier, 50),
        Err(E::Signature(SignedEvidenceError::PayloadMismatch))
    ));
}
#[test]
fn field_training_dataset_is_not_independent_evaluation_dataset() {
    let f = Fixture::new(false, None);
    let mut o = Owner {
        snap: f.s.clone(),
        reads: 0,
        change: false,
    };
    o.snap.updates[0].evaluation_dataset_digest = f.p.dataset_digest;
    assert!(matches!(
        admit_authenticated_coupled_field_v1(f.request(), &f.s.scope_id, &mut o, &f.verifier, 50),
        Err(E::Binding("separate evaluation dataset"))
    ));
}
