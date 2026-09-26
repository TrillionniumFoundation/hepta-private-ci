fn product_test_coordinator() -> AgentRunCoordinator {
    AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "019153a4-3088-7e03-a56a-9b1964f75dde".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("runtime-config").to_string(),
        ports_digest: digest("runtime-ports").to_string(),
        max_active_runs: 8,
    })
    .expect("test runtime coordinator")
}

use crate::AgentRunCoordinator;
#[cfg(feature = "qualification-legacy-learning-write")]
use crate::RunPhase;
use crate::RuntimeComposition;
#[cfg(feature = "qualification-legacy-learning-write")]
use std::fs::OpenOptions;

use super::*;
use crate::AgentdIntuitionPolicyPinsV2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use std::sync::Arc;
#[path = "intelligence_product_intuition_support.rs"]
mod intuition_support;
#[path = "intelligence_product_intuition_tests.rs"]
mod intuition_tests;
use codex_hepta_context_compiler::ContextItem;
use codex_hepta_context_compiler::ContextRole;
use codex_hepta_intelligence::CanonicalBudgetV1;
use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_intelligence::CanonicalSnapshotRequestV1;
use codex_hepta_intelligence::LegalActionCandidateSetRequestV1;
use codex_hepta_intelligence::LegalActionCandidateV1;
use codex_hepta_intelligence::OwnerBindingV1;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::AppendDisposition;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::DurableLedger;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::LedgerAnchor;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::LedgerEvent;
#[cfg(feature = "qualification-legacy-learning-write")]
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_objective::ConstraintClass;
use codex_hepta_objective::ObjectiveAbstentionRuleProfileV1;
use codex_hepta_objective::ObjectiveActionProfileV1;
use codex_hepta_objective::ObjectiveConstraintComparatorV1;
use codex_hepta_objective::ObjectiveConstraintProfileV1;
use codex_hepta_objective::ObjectiveEvidenceProfileV1;
use codex_hepta_objective::ObjectiveEvidenceRequirementV1;
use codex_hepta_objective::ObjectivePredicateComparatorV1;
use codex_hepta_objective::ObjectivePredicateProfileV1;
use codex_hepta_objective::ObjectiveProvenanceV1;
use codex_hepta_objective::ObjectiveResourceAxisProfileV1;
use codex_hepta_objective::ObjectiveResourceProfileV1;
use codex_hepta_objective::ObjectiveResourcesV1;
use codex_hepta_objective::ObjectiveRiskClassV1;
use codex_hepta_objective::ObjectiveRiskProfileV1;
use codex_hepta_objective::ObjectiveRiskV1;
use codex_hepta_objective::ObjectiveRollbackClassV1;
use codex_hepta_objective::ObjectiveSoftDimensionProfileV1;
use codex_hepta_objective::ObjectiveSoftDimensionV1;
use codex_hepta_objective::ObjectiveSoftDirectionV1;
use codex_hepta_objective::ObjectiveSourceAuthenticationV1;
use codex_hepta_objective::ObjectiveSourceConstraintV1;
use codex_hepta_objective::ObjectiveSourcePredicateV1;
use codex_hepta_objective::ObjectiveSourceTrustV1;
use codex_hepta_objective::ObjectiveStructuredIntentV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const Q24: i64 = 1 << 24;
const OBSERVED_MICROS: u64 = 1_788_861_600_000_000;
const NOW_MICROS: u64 = OBSERVED_MICROS + 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("revision")
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).expect("probability")
}

fn resource_axis(name: &str, class: ConstraintClass) -> ObjectiveResourceAxisProfileV1 {
    ObjectiveResourceAxisProfileV1 {
        constraint_id: id(&format!("resource.{name}.ceiling")),
        axis: id(&format!("resource.{name}")),
        class,
        q32_per_source_unit: FixedQ32::from_raw(1),
        evidence_source: id("objective.resource.profile"),
    }
}

fn objective_profile() -> ObjectiveAdmissionProfileV1 {
    ObjectiveAdmissionProfileV1 {
        profile_id: id("objective.profile.agentd.v1"),
        profile_revision: revision(1),
        expected_input_schema_digest: digest("schema-v1"),
        expected_normalization_profile_digest: digest("normalization-v1"),
        principal_scope_digest: digest("principal-scope"),
        principal_scope: id("principal.alpha"),
        allowed_locales: vec!["en-US".to_string()],
        maximum_source_age_micros: 60_000_000,
        maximum_future_skew_micros: 1_000_000,
        deadline_required: true,
        allowed_trusted_source_identities: vec![id("adapter.console")],
        constraints: vec![ObjectiveConstraintProfileV1 {
            source_constraint_id: "latency.ceiling".to_string(),
            expected_unit: "micros".to_string(),
            class: ConstraintClass::Task,
            axis: id("latency.micros"),
        }],
        predicates: vec![
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.success".to_string(),
                expected_unit: "ratio".to_string(),
                axis: id("task.success.ratio"),
            },
            ObjectivePredicateProfileV1 {
                source_predicate_id: "task.terminal".to_string(),
                expected_unit: "boolean".to_string(),
                axis: id("task.terminal"),
            },
        ],
        actions: vec![
            ObjectiveActionProfileV1 {
                source_action_class: "read".to_string(),
                action_id: id("action.read"),
            },
            ObjectiveActionProfileV1 {
                source_action_class: "network".to_string(),
                action_id: id("action.network"),
            },
        ],
        soft_dimensions: vec![ObjectiveSoftDimensionProfileV1 {
            source_dimension_id: "quality".to_string(),
            expected_unit: "ratio".to_string(),
            expected_direction: ObjectiveSoftDirectionV1::Maximize,
            dimension: id("quality.ratio"),
            baseline_weight: FixedQ32::from_raw(1_i64 << 31),
        }],
        evidence_requirements: vec![ObjectiveEvidenceProfileV1 {
            source_requirement_id: "evidence.quality".to_string(),
            axis: id("evidence.confidence"),
        }],
        resources: ObjectiveResourceProfileV1 {
            time_micros: resource_axis("time", ConstraintClass::Task),
            token_count: resource_axis("tokens", ConstraintClass::Task),
            compute_micros: resource_axis("compute", ConstraintClass::Environment),
            memory_bytes: resource_axis("memory", ConstraintClass::Environment),
            network_bytes: resource_axis("network", ConstraintClass::Principal),
            external_effect_count: resource_axis("effects", ConstraintClass::Principal),
        },
        risk: ObjectiveRiskProfileV1 {
            evidence_source: id("objective.risk.profile"),
            class: ConstraintClass::Principal,
            risk_constraint_id: id("risk.class"),
            risk_axis: id("risk.class.value"),
            low_value: FixedQ32::from_raw(0),
            medium_value: FixedQ32::from_raw(1),
            high_value: FixedQ32::from_raw(2),
            critical_value: FixedQ32::from_raw(3),
            rollback_constraint_id: id("risk.rollback"),
            rollback_axis: id("risk.rollback.value"),
            rollback_none_value: FixedQ32::from_raw(0),
            rollback_reversible_value: FixedQ32::from_raw(1),
            rollback_compensatable_value: FixedQ32::from_raw(2),
            rollback_irreversible_value: FixedQ32::from_raw(3),
            compensation_constraint_id: id("risk.compensation"),
            compensation_axis: id("risk.compensation.value"),
            compensation_false_value: FixedQ32::from_raw(0),
            compensation_true_value: FixedQ32::from_raw(1),
            abstention_constraint_id: id("risk.abstention"),
            abstention_axis: id("risk.abstention.value"),
            abstention_rules: vec![ObjectiveAbstentionRuleProfileV1 {
                source_rule: "ask".to_string(),
                value: FixedQ32::from_raw(1),
            }],
        },
    }
}

fn objective_envelope() -> ObjectiveSourceEnvelopeV1 {
    let mut envelope = ObjectiveSourceEnvelopeV1 {
        request_id: "request.agentd.001".to_string(),
        principal_scope_digest: digest("principal-scope"),
        intent_digest: Digest32::ZERO,
        structured_intent: ObjectiveStructuredIntentV1 {
            success_predicates: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.success".to_string(),
                unit: "ratio".to_string(),
                comparator: ObjectivePredicateComparatorV1::GreaterThanOrEqual,
                bound_q32: 1_i64 << 31,
                evidence_source_id: "observer.task".to_string(),
                terminal: false,
            }],
            terminal_conditions: vec![ObjectiveSourcePredicateV1 {
                predicate_id: "task.terminal".to_string(),
                unit: "boolean".to_string(),
                comparator: ObjectivePredicateComparatorV1::Equal,
                bound_q32: FixedQ32::ONE.raw(),
                evidence_source_id: "observer.task".to_string(),
                terminal: true,
            }],
            legal_action_classes: vec!["read".to_string()],
            forbidden_action_classes: vec!["network".to_string()],
            confirmation_action_classes: Vec::new(),
            constraints: vec![ObjectiveSourceConstraintV1 {
                constraint_id: "latency.ceiling".to_string(),
                unit: "micros".to_string(),
                comparator: ObjectiveConstraintComparatorV1::LessThanOrEqual,
                bound_q32: 5_000,
                evidence_source_id: "observer.clock".to_string(),
                terminal: false,
            }],
            soft_dimensions: vec![ObjectiveSoftDimensionV1 {
                dimension_id: "quality".to_string(),
                unit: "ratio".to_string(),
                direction: ObjectiveSoftDirectionV1::Maximize,
                minimum_weight_q32: 0,
                maximum_weight_q32: FixedQ32::ONE.raw(),
            }],
            evidence_requirements: vec![ObjectiveEvidenceRequirementV1 {
                requirement_id: "evidence.quality".to_string(),
                evidence_source_id: "observer.evidence".to_string(),
                minimum_confidence_ppm: 900_000,
                terminal: true,
            }],
            resources: ObjectiveResourcesV1 {
                time_micros: 10_000,
                token_count: 1_000,
                compute_micros: 50_000,
                memory_bytes: 1_048_576,
                network_bytes: 0,
                external_effect_count: 0,
            },
            risk: ObjectiveRiskV1 {
                risk_class: ObjectiveRiskClassV1::Low,
                abstention_rule: "ask".to_string(),
                rollback_class: ObjectiveRollbackClassV1::Reversible,
                compensation_required: false,
            },
            provenance: ObjectiveProvenanceV1 {
                source_digest: digest("source-bytes"),
                normalization_profile_digest: digest("normalization-v1"),
            },
        },
        source_trust_class: ObjectiveSourceTrustV1::AuthorizedAdapter,
        locale: "en-US".to_string(),
        observed_at: "2026-09-08T10:00:00Z".to_string(),
        deadline: Some("2026-09-08T10:05:00Z".to_string()),
        input_schema_digest: digest("schema-v1"),
    };
    envelope.intent_digest =
        canonical_objective_intent_digest_v1(&envelope).expect("objective intent");
    envelope
}

fn objective_context(
    profile: &ObjectiveAdmissionProfileV1,
    envelope: &ObjectiveSourceEnvelopeV1,
) -> ObjectiveAdmissionContextV1 {
    ObjectiveAdmissionContextV1 {
        revision: revision(7),
        now_unix_micros: NOW_MICROS,
        selected_profile_digest: profile.digest().expect("profile digest"),
        source_authentication: ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity: id("adapter.console"),
            source_digest: envelope.structured_intent.provenance.source_digest,
        },
    }
}

fn owner_bindings() -> Vec<OwnerBindingV1> {
    [
        "objective.compiler",
        "utility.ndu",
        "neuron.runtime",
        "prompt.optimizer",
        "intuition.policy",
        "context.compiler",
        "learning.eval",
    ]
    .into_iter()
    .enumerate()
    .map(|(index, owner)| OwnerBindingV1 {
        owner_id: id(owner),
        generation: generation((index + 1) as u64),
        implementation_digest: digest(&format!("{owner}:impl")),
        key_digest: digest(&format!("{owner}:key")),
        key_epoch: (index + 1) as u64,
    })
    .collect()
}

fn authority_signing_key() -> SigningKey {
    SigningKey::from_bytes(&[7_u8; 32])
}

fn authority_verifier() -> IntelligenceAuthorityVerifierV1 {
    let signing = authority_signing_key();
    IntelligenceAuthorityVerifierV1 {
        signer_id: "qualification.intelligence-authority".to_string(),
        verifying_key: signing.verifying_key().to_bytes(),
    }
}

fn write_authority_file(path: &std::path::Path, owners: &[OwnerBindingV1], frontier: Digest32) {
    let file = IntelligenceAuthorityFileV1 {
        schema_version: 1,
        authority_epoch: 11,
        revocation_frontier_digest: frontier.to_string(),
        owners: owners
            .iter()
            .map(|owner| IntelligenceAuthorityOwnerFileV1 {
                owner_id: owner.owner_id.to_string(),
                generation: owner.generation.get(),
                implementation_digest: owner.implementation_digest.to_string(),
                key_digest: owner.key_digest.to_string(),
                key_epoch: owner.key_epoch,
            })
            .collect(),
        signer_id: "qualification.intelligence-authority".to_string(),
        signature: Vec::new(),
    };
    let mut file = file;
    let signing = authority_signing_key();
    file.signature = signing
        .sign(&authority_signing_payload(&file).expect("authority payload"))
        .to_bytes()
        .to_vec();
    std::fs::write(path, serde_json::to_vec(&file).expect("authority json"))
        .expect("write authority");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
            .expect("private authority file");
    }
}

struct Fixture {
    request: CanonicalIntelligenceRunRequestV1,
    inputs: AgentdIntelligenceOwnerInputsV1,
    owners: Vec<OwnerBindingV1>,
    intuition_host: Arc<AgentdIntuitionPolicyHostV2>,
}

fn fixture() -> Fixture {
    let profile = objective_profile();
    let envelope = objective_envelope();
    let objective_context = objective_context(&profile, &envelope);
    let objective = admit_and_compile_objective_v1(&envelope, &profile, &objective_context)
        .expect("objective admission")
        .compile_result
        .expect("compiled objective");
    let objective_digest = objective.objective.semantic_digest;

    let utility_profile = UtilityProfile {
        profile_id: id("utility.agentd.v1"),
        axis_registry_digest: digest("utility.agentd.v1-axis-registry"),
        normalization_manifest_digest: digest("utility.agentd.v1-normalization"),
        dimensions: vec![(id("quality.ratio"), AxisDirection::Maximize)],
        risk_ceilings: Vec::new(),
        resource_ceilings: Vec::new(),
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    };
    let mut utility_contributions = ContributionSet {
        objective_digest,
        generation: generation(7),
        contributions: vec![UtilityContribution {
            candidate_id: id("action.read"),
            organ_id: id("planner"),
            objective_digest,
            generation: generation(7),
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![AxisValue {
                axis: id("quality.ratio"),
                value: FixedQ32::ONE,
            }],
            risk: Vec::new(),
            resource: Vec::new(),
            uncertainty: vec![AxisValue {
                axis: id("quality.ratio"),
                value: FixedQ32::ZERO,
            }],
            support_digest: digest("utility-support"),
        }],
    };
    let mut abstain = utility_contributions.contributions[0].clone();
    abstain.candidate_id = id("abstain");
    abstain.utility[0].value = FixedQ32::ZERO;
    utility_contributions.contributions.push(abstain);
    let utility_policy = EvaluationPolicyV1 {
        policy_id: id("utility-policy.agentd.v1"),
        utility_rules: vec![AxisAggregationRule {
            axis: id("quality.ratio"),
            operator: AggregationOperator::Sum,
        }],
        risk_rules: Vec::new(),
        resource_rules: Vec::new(),
        uncertainty_rules: vec![AxisAggregationRule {
            axis: id("quality.ratio"),
            operator: AggregationOperator::Maximum,
        }],
        pareto_absolute_tolerances: vec![AxisValue {
            axis: id("quality.ratio"),
            value: FixedQ32::ZERO,
        }],
    };
    let utility_scalarization = Some(ScalarizationProfile {
        profile_id: id("scalarization.agentd.v1"),
        weights: vec![AxisValue {
            axis: id("quality.ratio"),
            value: FixedQ32::ONE,
        }],
    });
    let ndu = evaluate_candidates_with_policy(
        utility_contributions.clone(),
        utility_profile.clone(),
        utility_scalarization.clone(),
        utility_policy.clone(),
    )
    .expect("NDU");

    let model_digest = digest("model-artifact");
    let neural_config = SparseConfig {
        model_digest,
        normalization_digest: digest("normalization"),
        generation: generation(7),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: Q24 / 2,
        target_activity_q24: Q24 / 5,
        threshold_rate_q24: Q24 / 10,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let neural_tick = SparseTick {
        scope_digest: digest("scope"),
        objective_digest,
        ndu_digest: ndu.evaluation_digest_v2,
        body_digest: digest("body"),
        input_digest: digest("approved-input"),
        sequence: 1,
        monotonic_micros: 1,
        drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let (_, neural_receipt) = sparse_tick(&neural_config, &neural_tick, None).expect("neural tick");

    let prompt_registry = digest("prompt-registry");
    let prompt_request = OptimizationRequest {
        decision_id: id("prompt-decision"),
        objective_digest,
        registry_snapshot_digest: prompt_registry,
        budget: 64,
        maximum_selected: 1,
        candidates: vec![PromptCandidate {
            candidate_id: id("prompt.one"),
            factor_id: id("factor.one"),
            realization_id: id("realization.one"),
            admitted: true,
            legal: true,
            expected_gain: FixedQ32::ONE,
            cost: 1,
            registry_digest: prompt_registry,
            support_digest: digest("prompt-support"),
        }],
    };

    let intuition_candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("action.read"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::ONE,
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("action-support"),
    }];
    let intuition_candidate_digest =
        canonical_candidate_set_digest_v1(&intuition_candidates).expect("candidate digest");
    let intuition_order_digest =
        canonical_candidate_order_digest_v1(&intuition_candidates).expect("order digest");
    let policy_digest = digest("intuition-policy");
    let objective_class_digest = digest("objective-class");
    let intuition_request = CalibratedDecisionRequestV1 {
        decision_id: id("run:agentd-intelligence"),
        objective_digest,
        objective_class_digest,
        state_digest: neural_receipt.checkpoint_after,
        policy_digest,
        policy_generation: 7,
        sequence: 1,
        minimum_confidence: probability(ProbabilityQ32::ONE.raw() / 2),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("candidate-completeness-receipt"),
            generator_digest: digest("candidate-generator"),
            grammar_digest: digest("candidate-grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest: intuition_candidate_digest,
            canonical_order_digest: intuition_order_digest,
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest("calibration-artifact"),
            policy_digest,
            objective_class_digest,
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            measured_ece_ppm: 1_000,
            subgroup_audit_digest: digest("subgroup-audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest("ood-artifact"),
            policy_digest,
            detector_digest: digest("ood-detector"),
            support_digest: digest("ood-support"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 10,
            maximum_in_domain_score: probability(ProbabilityQ32::ONE.raw() / 4),
            measured_false_acceptance_ppm: 100,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates: intuition_candidates,
    };

    let intuition = intuition_support::build(
        intuition_request,
        model_digest,
        intuition_support::TEST_AGENT_ID,
        1,
        wall_clock_ms().expect("intuition fixture clock"),
    );
    let mut owners = owner_bindings();
    let intuition_owner = owners
        .iter_mut()
        .find(|owner| owner.owner_id.as_str() == "intuition.policy")
        .expect("intuition owner");
    intuition_owner.generation = generation(intuition.input.profile.generation);
    intuition_owner.key_digest = intuition.root_key_digest;
    intuition_owner.key_epoch = intuition.authority_epoch;
    let snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest,
        authority_epoch: 11,
        body_generation: generation(7),
        configuration_digest: digest("agentd-intelligence-config"),
        revocation_frontier_digest: digest("revocation-frontier"),
        owner_bindings: owners.clone(),
    })
    .expect("canonical snapshot");

    let context_request = CompilationRequest {
        compilation_id: id("context.agentd"),
        run_snapshot_digest: snapshot.digest(),
        objective_digest,
        token_budget: 16,
        items: vec![ContextItem {
            item_id: id("instruction.readonly"),
            role: ContextRole::TrustedInstruction,
            content_digest: digest("instruction"),
            source_digest: digest("instruction-source"),
            token_count: 2,
            contains_secret: false,
        }],
    };

    let evaluation_request = EvaluationRequest {
        evaluation_id: id("evaluation.agentd"),
        evaluator_id: id("learning.eval"),
        candidate_id: id("action.read"),
        candidate_producer_id: id("intuition.policy"),
        baseline_id: id("baseline.noop"),
        objective_digest,
        comparisons: vec![codex_hepta_intelligence_eval::MetricComparison {
            metric_id: id("quality"),
            direction: codex_hepta_intelligence_eval::Direction::Maximize,
            candidate: FixedQ32::ONE,
            baseline: FixedQ32::ZERO,
            minimum_delta: FixedQ32::ZERO,
            hard: true,
            support_digest: digest("evaluation-support"),
        }],
    };

    Fixture {
        request: CanonicalIntelligenceRunRequestV1 {
            run_id: id("run:agentd-intelligence"),
            snapshot,
            legal_candidates: LegalActionCandidateSetRequestV1 {
                candidate_set_id: id("candidate-set.agentd"),
                state_digest: objective_digest,
                generator_id: id("intelligence.control"),
                grammar_digest: digest("legal-grammar"),
                candidates: vec![LegalActionCandidateV1 {
                    candidate_id: id("action.read"),
                    support_digest: digest("action-support"),
                }],
                support_floor_ppm: 1,
            },
            budget: CanonicalBudgetV1 {
                total_micros: 70_000_000,
                objective_micros: 10_000_000,
                utility_micros: 10_000_000,
                neural_micros: 10_000_000,
                prompt_micros: 10_000_000,
                intuition_micros: 10_000_000,
                context_micros: 10_000_000,
                evaluation_micros: 10_000_000,
            },
        },
        inputs: AgentdIntelligenceOwnerInputsV1 {
            objective_envelope: envelope,
            objective_profile: profile,
            objective_context,
            utility_contributions,
            utility_profile,
            utility_scalarization,
            utility_policy,
            neural_config,
            neural_tick,
            neural_previous: None,
            prompt_request,
            intuition: intuition.input,
            context_request,
            evaluation_request,
            signed_evaluation: None,
        },
        owners,
        intuition_host: intuition.host,
    }
}

fn product_runner(authority: PathBuf, fixture: &Fixture) -> AgentdIntelligenceProductRunnerV1 {
    AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
        .expect("runner")
        .with_intuition_policy_host(Arc::clone(&fixture.intuition_host))
        .expect("authenticated intuition host")
}

#[cfg(feature = "qualification-legacy-learning-write")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_owner_product_path_records_decision_outcome_and_reopens() {
    let fixture = fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority, &fixture);
    let mut coordinator = product_test_coordinator();
    let outcome = runner
        .prepare_and_admit(&mut coordinator, fixture.request, fixture.inputs)
        .await
        .expect("product prepare and Agentd admission");
    let AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt: attached,
    } = outcome
    else {
        panic!("selected real-owner path must be ready");
    };
    assert!(!prepared.envelope.utility_receipt_digest.is_zero());
    assert!(!prepared.dispatch_proposal_digest.is_zero());
    assert!(!prepared.envelope.authority.grants_any());
    assert_eq!(attached.phase, RunPhase::ContextAttached);
    assert_eq!(
        attached.compilation_receipt_digest.as_deref(),
        Some(prepared.envelope.envelope_digest.to_string().as_str())
    );
    let dispatched = coordinator
        .mark_dispatched(
            wall_clock_ms().expect("dispatch clock"),
            &attached.run_id,
            attached.revision,
        )
        .expect("commit dispatch before physical effect");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);

    let ledger_path = temp.path().join("learning-ledger");
    let binding = digest("agentd-intelligence-ledger-binding");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("create ledger");
    let mut ledger = DurableLedger::create(file, binding, 16).expect("ledger");
    let decision = runner
        .append_decision(
            &mut ledger,
            Digest32::ZERO,
            &prepared,
            id("episode.agentd"),
            id("intuition.policy"),
        )
        .expect("decision append");
    assert_eq!(decision.disposition, AppendDisposition::Appended);

    let outcome = runner
        .append_outcome(
            &mut ledger,
            decision.chain_digest,
            &prepared,
            id("outcome-record.agentd"),
            id("outcome.agentd"),
            id("episode.agentd"),
            id("observer.independent"),
            FixedQ32::ONE,
            OutcomeFinality::Terminal,
            digest("terminal-observation"),
        )
        .expect("outcome append");
    assert_eq!(outcome.disposition, AppendDisposition::Appended);
    let terminal = coordinator
        .observe_terminal(
            &dispatched.run_id,
            dispatched.revision,
            RunPhase::Succeeded,
            /*terminal_observed*/ true,
        )
        .expect("commit independently observed terminal");
    assert_eq!(terminal.phase, RunPhase::Succeeded);
    assert!(terminal.terminal_observed);
    assert_eq!(
        terminal.compilation_receipt_digest.as_deref(),
        Some(prepared.envelope.envelope_digest.to_string().as_str())
    );
    assert_eq!(ledger.records().expect("records").len(), 2);
    assert!(matches!(
        ledger.records().expect("records")[0].event,
        LedgerEvent::Decision(_)
    ));
    assert!(matches!(
        ledger.records().expect("records")[1].event,
        LedgerEvent::Outcome(_)
    ));

    drop(ledger);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("reopen ledger");
    let mut recovered = DurableLedger::recover(
        file,
        binding,
        16,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: 2,
            chain_digest: outcome.chain_digest,
        }),
    )
    .expect("recover");
    assert_eq!(recovered.records().expect("recovered records").len(), 2);

    let replay = runner
        .append_outcome(
            &mut recovered,
            decision.chain_digest,
            &prepared,
            id("outcome-record.agentd"),
            id("outcome.agentd"),
            id("episode.agentd"),
            id("observer.independent"),
            FixedQ32::ONE,
            OutcomeFinality::Terminal,
            digest("terminal-observation"),
        )
        .expect("exact outcome retry");
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unsigned_currentness_substitution_fails_before_owner_use() {
    let fixture = fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&authority).expect("authority bytes"))
            .expect("authority json");
    value["authority_epoch"] = serde_json::json!(12);
    std::fs::write(
        &authority,
        serde_json::to_vec(&value).expect("tampered authority json"),
    )
    .expect("tamper authority");
    let runner = product_runner(authority, &fixture);
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::FreshnessUnavailable(_)
        ))
    ));
}

#[cfg(feature = "qualification-legacy-learning-write")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_use_revocation_race_fails_before_decision_publication() {
    let fixture = fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority.clone(), &fixture);
    let outcome = runner
        .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
        .await
        .expect("prepare");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
        panic!("ready");
    };

    write_authority_file(
        &authority,
        &fixture.owners,
        digest("new-revocation-frontier"),
    );

    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("create ledger");
    let mut ledger =
        DurableLedger::create(file, digest("binding"), 16).expect("create durable ledger");
    assert!(matches!(
        runner.append_decision(
            &mut ledger,
            Digest32::ZERO,
            &prepared,
            id("episode.agentd"),
            id("intuition.policy"),
        ),
        Err(AgentdIntelligenceLedgerError::Currentness(
            CanonicalIntelligenceError::RevocationFrontierDrift(_)
        ))
    ));
    assert!(ledger.records().expect("records").is_empty());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn missing_current_owner_fails_before_product_use() {
    let fixture = fixture();
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    let mut owners = fixture.owners.clone();
    owners.retain(|owner| owner.owner_id.as_str() != "utility.ndu");
    write_authority_file(
        &authority,
        &owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority, &fixture);
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::FreshnessUnavailable(_)
        ))
    ));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn total_budget_timeout_never_creates_a_dispatch_or_ledger_capability() {
    let mut fixture = fixture();
    fixture.request.budget = CanonicalBudgetV1 {
        total_micros: 7,
        objective_micros: 1,
        utility_micros: 1,
        neural_micros: 1,
        prompt_micros: 1,
        intuition_micros: 1,
        context_micros: 1,
        evaluation_micros: 1,
    };
    let temp = tempfile::tempdir().expect("tempdir");
    let authority = temp.path().join("intelligence-authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority, &fixture);
    let result = runner
        .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
        .await;
    assert!(
        matches!(
            result,
            Err(AgentdIntelligenceProductError::TimedOut)
                | Err(AgentdIntelligenceProductError::Canonical(
                    CanonicalIntelligenceError::PortFailure {
                        class: CanonicalPortFailureClassV1::TimedOut,
                        ..
                    }
                ))
        ),
        "either total or owner-local deadline must reject before admission: {result:?}"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn aborted_owner_work_retains_its_budget_until_computation_finishes() {
    let temp = tempfile::tempdir().expect("tempdir");
    let fixture = fixture();
    let authority = temp.path().join("authority.json");
    write_authority_file(
        &authority,
        &fixture.owners,
        fixture.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority, &fixture);
    let mut releases = Vec::new();
    let mut workers = Vec::new();
    for _ in 0..MAX_CANONICAL_OWNER_WORKERS {
        let (started, ready) = tokio::sync::oneshot::channel();
        let (release, finish) = std::sync::mpsc::sync_channel::<()>(1);
        let worker = runner
            .spawn_owner_work(move || {
                started.send(()).expect("announce worker start");
                finish.recv().expect("test releases worker");
            })
            .expect("bounded admission");
        timeout(Duration::from_secs(5), ready)
            .await
            .expect("worker started")
            .expect("start acknowledgement");
        worker.abort();
        releases.push(release);
        workers.push(worker);
    }
    assert_eq!(runner.worker_slots.available_permits(), 0);
    let result = runner
        .prepare(&product_test_coordinator(), fixture.request, fixture.inputs)
        .await;
    assert!(matches!(result, Err(AgentdIntelligenceProductError::Busy)));
    for release in releases {
        release.send(()).expect("release real worker");
    }
    for worker in workers {
        timeout(Duration::from_secs(5), worker)
            .await
            .expect("bounded completion")
            .expect("already-running worker completes");
    }
    assert_eq!(
        runner.worker_slots.available_permits(),
        MAX_CANONICAL_OWNER_WORKERS
    );
    let ready = runner
        .spawn_owner_work(|| 7_u32)
        .expect("capacity restored");
    assert_eq!(ready.await.expect("new work completes"), 7);
}

#[path = "intelligence_product_signed_tests.rs"]
mod signed;
