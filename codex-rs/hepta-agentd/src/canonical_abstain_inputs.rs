//! Pure deterministic owner inputs for the conservative canonical abstain profile.

use codex_hepta_agent_components::context_compiler::CompilationRequest;
use codex_hepta_agent_components::intelligence::CanonicalIntelligenceSnapshotV1;
use codex_hepta_agent_components::intelligence_eval::EvaluationRequest;
use codex_hepta_agent_components::intuition::AssignmentModeV1;
use codex_hepta_agent_components::intuition::CalibratedActionCandidateV1;
use codex_hepta_agent_components::intuition::CalibratedDecisionRequestV1;
use codex_hepta_agent_components::intuition::CalibrationArtifactV1;
use codex_hepta_agent_components::intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_agent_components::intuition::OodArtifactV1;
use codex_hepta_agent_components::intuition::RiskClass;
use codex_hepta_agent_components::intuition::canonical_candidate_order_digest_v1;
use codex_hepta_agent_components::intuition::canonical_candidate_set_digest_v1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agent_components::ndu::AggregationOperator;
use codex_hepta_agent_components::ndu::AxisAggregationRule;
use codex_hepta_agent_components::ndu::AxisDirection;
use codex_hepta_agent_components::ndu::AxisValue;
use codex_hepta_agent_components::ndu::ContributionSet;
use codex_hepta_agent_components::ndu::EvaluationPolicyV1;
use codex_hepta_agent_components::ndu::FeasibilityPosture;
use codex_hepta_agent_components::ndu::RequiredOrganSet;
use codex_hepta_agent_components::ndu::ScalarizationProfile;
use codex_hepta_agent_components::ndu::UtilityContribution;
use codex_hepta_agent_components::ndu::UtilityProfile;
use codex_hepta_agent_components::ndu::evaluate_candidates_with_policy;
use codex_hepta_agent_components::neuron::SparseConfig;
use codex_hepta_agent_components::neuron::SparseTick;
use codex_hepta_agent_components::prompt_optimizer::OptimizationRequest;
use codex_hepta_agent_components::prompt_optimizer::PromptCandidate;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::ProbabilityQ32;
use codex_hepta_agent_components::types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;
use crate::AgentdObjectiveOwnerInputV1;

const Q24: i64 = 1 << 24;

pub(super) fn owner_inputs(
    record: &RunStartRecordV1,
    snapshot: &CanonicalIntelligenceSnapshotV1,
    candidate_id: StableId,
    candidate_support: Digest32,
    now_micros: u64,
) -> Result<AgentdIntelligenceOwnerInputsV1, AgentdError> {
    let generation = Generation::new(record.snapshot.generation)
        .map_err(|error| invalid(&format!("RunStart generation: {error}")))?;
    let utility_axis = id("utility.safe-abstain")?;
    let organ_id = id("intelligence.control")?;
    let utility_contributions = ContributionSet {
        objective_digest: record.snapshot.objective_digest,
        generation,
        contributions: vec![UtilityContribution {
            candidate_id: candidate_id.clone(),
            organ_id: organ_id.clone(),
            objective_digest: record.snapshot.objective_digest,
            generation,
            feasibility: FeasibilityPosture::Feasible,
            utility: vec![AxisValue {
                axis: utility_axis.clone(),
                value: FixedQ32::ZERO,
            }],
            risk: vec![],
            resource: vec![],
            uncertainty: vec![AxisValue {
                axis: utility_axis.clone(),
                value: FixedQ32::ZERO,
            }],
            support_digest: candidate_support,
        }],
    };
    let utility_profile = UtilityProfile {
        profile_id: id("utility-profile.safe-abstain")?,
        axis_registry_digest: bound_digest(
            b"hepta.agentd.safe-abstain.utility-axis.v1\0",
            record,
            snapshot.digest(),
        ),
        normalization_manifest_digest: bound_digest(
            b"hepta.agentd.safe-abstain.utility-normalization.v1\0",
            record,
            snapshot.digest(),
        ),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![organ_id],
        },
    };
    let utility_scalarization = Some(ScalarizationProfile {
        profile_id: id("utility-scalarization.safe-abstain")?,
        weights: vec![AxisValue {
            axis: utility_axis.clone(),
            value: FixedQ32::ONE,
        }],
    });
    let utility_policy = EvaluationPolicyV1 {
        policy_id: id("utility-policy.safe-abstain")?,
        utility_rules: vec![AxisAggregationRule {
            axis: utility_axis.clone(),
            operator: AggregationOperator::Sum,
        }],
        risk_rules: vec![],
        resource_rules: vec![],
        uncertainty_rules: vec![AxisAggregationRule {
            axis: utility_axis.clone(),
            operator: AggregationOperator::Maximum,
        }],
        pareto_absolute_tolerances: vec![AxisValue {
            axis: utility_axis,
            value: FixedQ32::ZERO,
        }],
    };
    let ndu = evaluate_candidates_with_policy(
        utility_contributions.clone(),
        utility_profile.clone(),
        utility_scalarization.clone(),
        utility_policy.clone(),
    )
    .map_err(|error| invalid(&format!("conservative NDU profile: {error}")))?;

    let neural_config = SparseConfig {
        model_digest: record.snapshot.model_tuple_digest,
        normalization_digest: bound_digest(
            b"hepta.agentd.safe-abstain.neural-normalization.v1\0",
            record,
            snapshot.digest(),
        ),
        generation,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: Q24,
        target_activity_q24: 0,
        threshold_rate_q24: 0,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24,
    };
    let neural_tick = SparseTick {
        scope_digest: record.snapshot.fence_digest,
        objective_digest: record.snapshot.objective_digest,
        ndu_digest: ndu.evaluation_digest_v2,
        body_digest: record.runtime_body_digest,
        input_digest: bound_digest(
            b"hepta.agentd.safe-abstain.neural-input.v1\0",
            record,
            snapshot.digest(),
        ),
        sequence: 1,
        monotonic_micros: now_micros,
        drive_q24: vec![0; 5],
        prediction_q24: vec![0; 5],
    };

    let prompt_support = bound_digest(
        b"hepta.agentd.safe-abstain.prompt-support.v1\0",
        record,
        snapshot.digest(),
    );
    let prompt_request = OptimizationRequest {
        decision_id: id("prompt-decision.safe-abstain")?,
        objective_digest: record.snapshot.objective_digest,
        registry_snapshot_digest: record.snapshot.prompt_registry_digest,
        budget: 1,
        maximum_selected: 1,
        candidates: vec![PromptCandidate {
            candidate_id: id("prompt.safe-abstain")?,
            factor_id: id("prompt-factor.safe-abstain")?,
            realization_id: id("prompt-realization.safe-abstain")?,
            admitted: true,
            legal: true,
            expected_gain: FixedQ32::ONE,
            cost: 1,
            registry_digest: record.snapshot.prompt_registry_digest,
            support_digest: prompt_support,
        }],
    };

    let calibrated_candidate = CalibratedActionCandidateV1 {
        candidate_id: candidate_id.clone(),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::ZERO,
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: candidate_support,
    };
    let calibrated_candidates = vec![calibrated_candidate];
    let candidate_set_digest = canonical_candidate_set_digest_v1(&calibrated_candidates)
        .map_err(|error| invalid(&format!("calibrated candidate set: {error}")))?;
    let candidate_order_digest = canonical_candidate_order_digest_v1(&calibrated_candidates)
        .map_err(|error| invalid(&format!("calibrated candidate order: {error}")))?;
    let policy_digest = bound_digest(
        b"hepta.agentd.safe-abstain.intuition-policy.v1\0",
        record,
        snapshot.digest(),
    );
    let sequence = record.authentication.sequence.max(1);
    let intuition_request = CalibratedDecisionRequestV1 {
        decision_id: id("intuition-decision.safe-abstain")?,
        objective_digest: record.snapshot.objective_digest,
        objective_class_digest: record.snapshot.hard_constraint_digest,
        state_digest: record.snapshot.objective_digest,
        policy_digest,
        policy_generation: record.snapshot.generation,
        sequence,
        minimum_confidence: ProbabilityQ32::ONE,
        maximum_ece_ppm: 0,
        maximum_ood_false_acceptance_ppm: 0,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: bound_digest(
                b"hepta.agentd.safe-abstain.completeness.v1\0",
                record,
                snapshot.digest(),
            ),
            generator_digest: bound_digest(
                b"hepta.agentd.safe-abstain.generator.v1\0",
                record,
                snapshot.digest(),
            ),
            grammar_digest: bound_digest(
                b"hepta.agentd.safe-abstain.intuition-grammar.v1\0",
                record,
                snapshot.digest(),
            ),
            hard_filter_digest: bound_digest(
                b"hepta.agentd.safe-abstain.hard-filter.v1\0",
                record,
                snapshot.digest(),
            ),
            truncation_digest: bound_digest(
                b"hepta.agentd.safe-abstain.truncation.v1\0",
                record,
                snapshot.digest(),
            ),
            candidate_set_digest,
            canonical_order_digest: candidate_order_digest,
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: bound_digest(
                b"hepta.agentd.safe-abstain.calibration-artifact.v1\0",
                record,
                snapshot.digest(),
            ),
            policy_digest,
            objective_class_digest: record.snapshot.hard_constraint_digest,
            generation: record.snapshot.generation,
            valid_from_sequence: sequence,
            expires_after_sequence: sequence,
            measured_ece_ppm: 0,
            subgroup_audit_digest: bound_digest(
                b"hepta.agentd.safe-abstain.calibration-audit.v1\0",
                record,
                snapshot.digest(),
            ),
        },
        ood: OodArtifactV1 {
            artifact_digest: bound_digest(
                b"hepta.agentd.safe-abstain.ood-artifact.v1\0",
                record,
                snapshot.digest(),
            ),
            policy_digest,
            detector_digest: bound_digest(
                b"hepta.agentd.safe-abstain.ood-detector.v1\0",
                record,
                snapshot.digest(),
            ),
            support_digest: candidate_support,
            generation: record.snapshot.generation,
            valid_from_sequence: sequence,
            expires_after_sequence: sequence,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::CounterBased {
            random_stream_digest: bound_digest(
                b"hepta.agentd.safe-abstain.assignment.v1\0",
                record,
                snapshot.digest(),
            ),
            draw: ProbabilityQ32::ZERO,
            abstain_probability: ProbabilityQ32::ONE,
        },
        candidates: calibrated_candidates,
    };

    Ok(AgentdIntelligenceOwnerInputsV1 {
        run_identity: None,
        objective: AgentdObjectiveOwnerInputV1::DurableRunStart(Box::new(record.clone())),
        utility_contributions,
        utility_profile,
        utility_scalarization,
        utility_policy,
        neural_config,
        neural_tick,
        neural_previous: None,
        prompt_request,
        intuition_request,
        context_request: CompilationRequest {
            compilation_id: id("context.safe-abstain")?,
            run_snapshot_digest: snapshot.digest(),
            objective_digest: record.snapshot.objective_digest,
            token_budget: 1,
            items: vec![],
        },
        evaluation_request: EvaluationRequest {
            evaluation_id: id("evaluation.safe-abstain")?,
            evaluator_id: id("learning.eval")?,
            candidate_id,
            candidate_producer_id: id("intelligence.control")?,
            baseline_id: id("baseline.safe-abstain")?,
            objective_digest: record.snapshot.objective_digest,
            comparisons: vec![],
        },
        signed_evaluation: None,
    })
}

pub(super) fn configuration_digest(
    identity: &AgentdIdentity,
    record: &RunStartRecordV1,
    frontier: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.safe-abstain.configuration.v1\0".to_vec();
    push_text(&mut bytes, identity.agent_id.as_str());
    for digest in [
        record.snapshot.objective_digest,
        record.snapshot.hard_constraint_digest,
        record.snapshot.preference_state_digest,
        record.snapshot.model_tuple_digest,
        record.snapshot.prompt_registry_digest,
        record.snapshot.artifact_set_digest,
        record.snapshot.fence_digest,
        record.runtime_body_digest,
        record.admission.profile_digest,
        record.objective_function_v1_digest,
        frontier,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&record.snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(super) fn bound_digest(
    domain: &[u8],
    record: &RunStartRecordV1,
    snapshot_digest: Digest32,
) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(record.snapshot.objective_digest.as_array());
    bytes.extend_from_slice(record.snapshot.fence_digest.as_array());
    bytes.extend_from_slice(record.runtime_body_digest.as_array());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn id(value: &str) -> Result<StableId, AgentdError> {
    StableId::new(value)
        .map_err(|error| AgentdError::Invalid(format!("safe-abstain stable id {value}: {error}")))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(message.to_string())
}
