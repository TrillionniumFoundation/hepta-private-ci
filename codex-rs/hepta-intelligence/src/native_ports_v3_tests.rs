use super::*;

use std::fs::OpenOptions;

use codex_hepta_intelligence_eval::*;
use codex_hepta_intuition::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_ndu::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::CapabilityBindingV2;
use crate::CapabilityNecessityV2;
use crate::CapabilityRequirementV2;
use crate::CapabilitySnapshotRequestV2;
use crate::CapabilitySnapshotV2;
use crate::LaneFBudgetV3;
use crate::LaneFRunRequestV3;
use crate::LegalActionCandidateV1;
use crate::PipelineDispositionV3;
use crate::build_legal_candidates_v1;
use crate::run_composition_v3;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn capability_snapshot(objective_digest: Digest32) -> CapabilitySnapshotV2 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let requirements = required
        .iter()
        .map(|(capability, owner)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        })
        .chain(
            [
                ("neural.signal", "neuron.runtime"),
                ("prompt.portfolio", "prompt.optimizer"),
            ]
            .iter()
            .map(|(capability, owner)| CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: digest(&format!("contract:{capability}")),
                necessity: CapabilityNecessityV2::Optional,
            }),
        )
        .collect::<Vec<_>>();
    let bindings = requirements
        .iter()
        .filter(|requirement| requirement.necessity == CapabilityNecessityV2::Required)
        .map(|requirement| CapabilityBindingV2 {
            capability_id: requirement.capability_id.clone(),
            owner_id: requirement.owner_id.clone(),
            contract_digest: requirement.contract_digest,
            implementation_digest: digest(&format!("impl:{}", requirement.capability_id.as_str())),
            generation: generation(1),
        })
        .collect();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest,
        authority_epoch: 1,
        body_generation: generation(1),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("capability snapshot")
}

fn signed_evaluation(objective_digest: Digest32) -> NativeEvaluationInputV3 {
    let keys = [
        SigningKey::from_bytes(&[31; 32]),
        SigningKey::from_bytes(&[47; 32]),
    ];
    let principals = keys
        .iter()
        .enumerate()
        .map(|(index, key)| AuthenticatedPrincipalV1 {
            principal_id: id(&format!("native-v3-signer-{index}")),
            credential_chain_digest: digest(&format!("credential-{index}")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("native-v3-scope"),
            authority_epoch: 1,
            authenticated_at: 10,
            expires_at: 100,
        })
        .collect::<Vec<_>>();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("native-v3-scope"),
        objective_digest,
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
    .expect("trust");

    let roles = vec![MetricRoleContractV2 {
        metric_id: id("native-v3-primary"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let dataset_digest = digest("native-v3-dataset");
    let plan = freeze_cross_fold_plan_v2(
        CrossFoldPlanV1 {
            plan_id: id("native-v3-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("native-v3-policy"),
            baseline_id: id("native-v3-baseline"),
            objective_digest,
            dataset_digest,
            estimand_digest: digest("native-v3-estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("native-v3-primary"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: None,
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: (0..2)
                .map(|index| CrossFoldPartitionV1 {
                    fold_id: id(&format!("native-v3-fold-{index}")),
                    training_principals: vec![id("training-principal")],
                    training_episodes: vec![id("training-episode")],
                    training_windows: vec![id("training-window")],
                    holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                    holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                    holdout_windows: vec![id(&format!("holdout-window-{index}"))],
                    model_digest: digest("native-v3-fold-model"),
                    predictions_digest: digest("native-v3-predictions"),
                })
                .collect(),
            final_holdout_window_id: id("holdout-window-1"),
            final_holdout_digest: digest("native-v3-final-holdout"),
        },
        roles.clone(),
    )
    .expect("frozen evaluation plan");
    let holdout_use = FinalHoldoutRegistry::new()
        .consume(&plan)
        .expect("holdout use");
    let bundle = IndependentEvaluationBundleV1 {
        evaluation_id: id("native-v3-evaluation"),
        candidate_id: id("native-v3-policy"),
        baseline_id: id("native-v3-baseline"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        generator: principals[0].clone(),
        evaluator: principals[1].clone(),
        frozen_plan: plan,
        holdout_use,
        objective_digest,
        dataset_digest,
        estimand_digest: digest("native-v3-estimand"),
        estimate_receipt_digest: digest("native-v3-estimate"),
        support_audit_digest: digest("native-v3-support"),
        confidence_receipt_digest: digest("native-v3-confidence"),
        retention_receipt_digests: vec![],
        unlearning_receipt_digest: Digest32::ZERO,
        snapshot_ids: vec![id("native-v3-snapshot")],
        future_window_ids: vec![id("holdout-window-1")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![MetricGateV1 {
            metric_id: id("native-v3-primary"),
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
            support_digest: digest("native-v3-metric-support"),
        }],
    };
    let generator_plan = sign_evidence(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        objective_digest,
        bundle.frozen_plan.plan_digest.as_array(),
    );
    let evaluator_bundle = sign_evidence(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Evaluator,
        objective_digest,
        &evaluation_signing_payload_v2(&bundle, &roles).expect("evaluation payload"),
    );
    NativeEvaluationInputV3 {
        bundle,
        roles,
        evidence: SignedEvaluationEvidenceV1 {
            generator_plan,
            evaluator_bundle,
        },
        verifier,
        now: 50,
    }
}

fn sign_evidence(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

fn calibrated_request(
    objective_digest: Digest32,
    snapshot_digest: Digest32,
    legal: &LegalActionCandidateSetV1,
) -> CalibratedDecisionRequestV1 {
    let mut candidates = legal
        .candidates
        .iter()
        .enumerate()
        .map(|(index, candidate)| CalibratedActionCandidateV1 {
            candidate_id: candidate.candidate_id.clone(),
            legal: true,
            hard_veto: false,
            utility: if index == 0 {
                FixedQ32::ONE
            } else {
                FixedQ32::ZERO
            },
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: candidate.support_digest,
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let policy_digest = digest("native-v3-policy");
    let objective_class_digest = digest("native-v3-objective-class");
    CalibratedDecisionRequestV1 {
        decision_id: id("placeholder-run"),
        objective_digest,
        objective_class_digest,
        state_digest: snapshot_digest,
        policy_digest,
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: ProbabilityQ32::ONE,
        maximum_ece_ppm: 1,
        maximum_ood_false_acceptance_ppm: 1,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("native-v3-completeness"),
            generator_digest: digest("native-v3-generator"),
            grammar_digest: legal.grammar_digest,
            hard_filter_digest: digest("native-v3-hard-filter"),
            truncation_digest: digest("native-v3-truncation"),
            candidate_set_digest: canonical_candidate_set_digest_v1(&candidates)
                .expect("candidate set digest"),
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("candidate order digest"),
            candidate_count: u32::try_from(candidates.len()).expect("candidate count"),
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("native-v3-calibration"),
            policy_digest,
            objective_class_digest,
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest("native-v3-subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("native-v3-ood"),
            policy_digest,
            detector_digest: digest("native-v3-detector"),
            support_digest: digest("native-v3-ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            maximum_in_domain_score: ProbabilityQ32::ZERO,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    }
}

#[derive(Default)]
struct RecordingHost {
    accepted: Option<Digest32>,
}

impl HostEnvelopePortV3 for RecordingHost {
    fn accept_host_envelope_v3(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        envelope.validate().map_err(|_| PortFailureV3 {
            class: PortFailureClassV3::Rejected,
            evidence_digest: digest("invalid-host-envelope"),
        })?;
        self.accepted = Some(envelope.envelope_digest);
        let mut bytes = b"native-v3-host-acceptance".to_vec();
        bytes.extend_from_slice(envelope.envelope_digest.as_array());
        Ok(PortReceiptV3 {
            stage: input.stage,
            producer: id("runtime.agentd"),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: Digest32::of_bytes(&bytes),
            decision: PortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[test]
fn native_v3_traverses_admitted_owner_apis_and_real_durable_ledger() {
    let vertical = crate::vertical_tests::vertical_request();
    let objective = codex_hepta_objective::admit_and_compile_objective_v1(
        &vertical.objective_envelope,
        &vertical.objective_profile,
        &vertical.objective_context,
    )
    .expect("objective admission")
    .compile_result
    .expect("objective compile");
    let objective_digest = objective.objective.semantic_digest;
    let snapshot = capability_snapshot(objective_digest);
    let legal = build_legal_candidates_v1(
        id("native-v3-legal-set"),
        snapshot.digest(),
        digest("native-v3-grammar"),
        0,
        objective
            .objective
            .legal_actions
            .iter()
            .map(|action| LegalActionCandidateV1 {
                candidate_id: action.id.clone(),
                action_digest: digest(&format!("action:{}", action.id.as_str())),
                support_digest: digest(&format!("support:{}", action.id.as_str())),
                support_ppm: 1_000_000,
            })
            .collect(),
    )
    .expect("legal candidate set");

    let profile = vertical.ndu_profile.clone();
    let axis = profile.dimensions[0].0.clone();
    let organ = profile.required_organs.organ_ids[0].clone();
    let mut contribution_ids = legal
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    contribution_ids.push(id("abstain"));
    let utility_set = ContributionSet {
        objective_digest,
        generation: generation(1),
        contributions: contribution_ids
            .into_iter()
            .enumerate()
            .map(|(index, candidate_id)| UtilityContribution {
                candidate_id,
                organ_id: organ.clone(),
                objective_digest,
                generation: generation(1),
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: axis.clone(),
                    value: if index == 0 {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: vec![],
                resource: vec![],
                uncertainty: vec![AxisValue {
                    axis: axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest(&format!("utility-support-{index}")),
            })
            .collect(),
    };
    let policy = EvaluationPolicyV1 {
        policy_id: id("native-v3-ndu-policy"),
        utility_rules: vec![AxisAggregationRule {
            axis: axis.clone(),
            operator: AggregationOperator::Sum,
        }],
        risk_rules: vec![],
        resource_rules: vec![],
        uncertainty_rules: vec![AxisAggregationRule {
            axis: axis.clone(),
            operator: AggregationOperator::Maximum,
        }],
        pareto_absolute_tolerances: vec![AxisValue {
            axis,
            value: FixedQ32::ZERO,
        }],
    };

    let body_digest = digest("native-v3-body");
    let inputs = NativeV3OwnerInputs {
        expected_snapshot_digest: snapshot.digest(),
        expected_objective_digest: objective_digest,
        expected_body_digest: body_digest,
        legal_candidates: legal.clone(),
        objective: NativeObjectiveInputV3 {
            envelope: vertical.objective_envelope,
            profile: vertical.objective_profile,
            context: vertical.objective_context,
        },
        utility: NativeUtilityInputV3 {
            set: utility_set,
            profile,
            scalarization: None,
            policy,
        },
        evaluation: signed_evaluation(objective_digest),
        neuron: None,
        prompt: None,
        intuition: calibrated_request(objective_digest, snapshot.digest(), &legal),
        context: vertical.context,
        learning: LearningDecisionTemplateV3 {
            episode_id: id("native-v3-episode"),
            policy_id: id("native-v3-policy"),
        },
    };

    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("ledger file");
    let mut ledger = DurableLedger::create(file, digest("native-v3-ledger"), 8).expect("ledger");
    let mut ports = NativeV3OwnerPorts::new(
        inputs,
        &mut ledger,
        Digest32::ZERO,
        RecordingHost::default(),
    );
    let receipt = run_composition_v3(
        LaneFRunRequestV3 {
            run_id: id("native-v3-run"),
            request_digest: digest("native-v3-request"),
            body_digest,
            artifact_set_digest: digest("native-v3-artifact-set"),
            snapshot,
            legal_candidates: legal,
            budget: LaneFBudgetV3 {
                total_micros: 11_000_000,
                objective_micros: 1_000_000,
                legal_set_micros: 1_000_000,
                utility_micros: 1_000_000,
                evaluation_micros: 1_000_000,
                neural_micros: 1_000_000,
                prompt_micros: 1_000_000,
                intuition_micros: 1_000_000,
                context_micros: 1_000_000,
                envelope_micros: 1_000_000,
                host_handoff_micros: 1_000_000,
                ledger_micros: 1_000_000,
            },
            deadline_unix_micros: 4_000_000_000_000_000,
        },
        &mut ports,
    )
    .expect("native V3 composition");

    assert_eq!(
        receipt.disposition,
        PipelineDispositionV3::HostHandoffAccepted
    );
    assert!(ports.host().accepted.is_some());
    assert!(ports.learning_append().is_some());
    assert_eq!(ledger.records().expect("ledger records").len(), 1);
    assert!(!receipt.authority.grants_any());
    receipt.validate().expect("receipt validation");
}
