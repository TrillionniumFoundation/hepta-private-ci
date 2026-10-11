//! Cross-crate Lane F shadow qualification.
//!
//! This crate is deliberately outside the product workspace. It proves only a
//! deterministic, bounded, authority-free composition over the selected source
//! candidate. It does not authenticate external evidence, load a real model,
//! select an artifact, mutate a current generation, or authorize deployment.

#![forbid(unsafe_code)]

use codex_hepta_intelligence::{IntelligencePlanReceipt, PlanCandidate, PlanningRequest, compose};
use codex_hepta_intuition::{ActionCandidate, DecisionRequest, IntuitionDecisionReceipt, decide};
use codex_hepta_neuron::{
    InhibitoryEdge, SparseConfig, SparseSignalReceipt, SparseTick, sparse_tick,
};
use codex_hepta_plasticity::{
    LayerNormDenominatorV2, ParameterCandidateKindV2, ParameterCandidateRequestV2,
    ParameterDeltaV2, ParameterProposalRequestV2, ParameterProposalV2, ProposalWindowV2,
    propose_v2,
};
use codex_hepta_prompt_optimizer::PromptCandidate;
use codex_hepta_prompt_optimizer::local_shadow::{
    LOCAL_NO_INTERVENTION_ID, LocalNoInterventionBaseline, LocalShadowInput, LocalShadowProposal,
    calculate_local_shadow,
};
use codex_hepta_types::{Digest32, FixedQ32, Generation, ProbabilityQ32, StableId};

const Q24: i64 = 1 << 24;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LaneFShadowReceipt {
    pub neuron: SparseSignalReceipt,
    pub prompt: LocalShadowProposal,
    pub intuition: IntuitionDecisionReceipt,
    pub intelligence: IntelligencePlanReceipt,
    pub plasticity: ParameterProposalV2,
    pub trace_digest: Digest32,
}

/// Run one complete qualification-only Lane F shadow decision.
///
/// Every input is a deterministic fixture. The function intentionally exposes
/// no model, provider, tool, filesystem, network, selection, promotion, release
/// or production-writer capability.
pub fn run_lane_f_shadow() -> Result<LaneFShadowReceipt, String> {
    let neuron_config = SparseConfig {
        model_digest: digest(b"lane-f-model"),
        normalization_digest: digest(b"lane-f-normalization"),
        generation: generation(1)?,
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: Q24 / 4,
        inhibition: vec![InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q24 / 4,
        }],
        activity_decay_q24: Q24 / 2,
        target_activity_q24: Q24 / 5,
        threshold_rate_q24: Q24 / 16,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    };
    let neuron_tick = SparseTick {
        scope_digest: digest(b"lane-f-scope"),
        objective_digest: digest(b"lane-f-objective"),
        ndu_digest: digest(b"lane-f-ndu"),
        body_digest: digest(b"lane-f-body"),
        input_digest: digest(b"lane-f-input"),
        sequence: 1,
        monotonic_micros: 1,
        drive_q24: vec![Q24 / 2, Q24 / 4, Q24 / 8, 0, -Q24 / 8],
        prediction_q24: vec![0; 5],
    };
    let (checkpoint, neuron) = sparse_tick(&neuron_config, &neuron_tick, None)
        .map_err(|error| format!("neuron: {error:?}"))?;
    if neuron.authority.grants_any() || !neuron.requires_calibration {
        return Err("neuron authority/calibration invariant".to_string());
    }

    let registry_digest = digest(b"lane-f-prompt-registry");
    let prompt_candidate = PromptCandidate {
        candidate_id: id("prompt:candidate:1")?,
        factor_id: id("prompt:factor:1")?,
        realization_id: id("prompt:realization:1")?,
        admitted: true,
        legal: true,
        expected_gain: FixedQ32::from_raw(10),
        cost: 1,
        registry_digest,
        support_digest: digest(b"lane-f-prompt-support"),
    };
    let prompt = calculate_local_shadow(LocalShadowInput {
        decision_id: id("prompt:decision:1")?,
        objective_digest: neuron_tick.objective_digest,
        state_digest: checkpoint.digest(),
        registry_snapshot_digest: registry_digest,
        token_budget: 8,
        maximum_selected_factors: 1,
        no_intervention: LocalNoInterventionBaseline {
            arm_id: id(LOCAL_NO_INTERVENTION_ID)?,
            registry_digest,
            support_reference_digest: digest(b"lane-f-no-intervention-support"),
        },
        factor_candidates: vec![prompt_candidate],
        interaction_edges: Vec::new(),
        hard_constraints: Vec::new(),
    })
    .map_err(|error| format!("prompt: {error:?}"))?;
    if prompt.authority().grants_any() || prompt.selections.len() != 1 {
        return Err("prompt authority/selection invariant".to_string());
    }

    let prompt_action = id("action:prompt:1")?;
    let intuition = decide(DecisionRequest {
        decision_id: id("intuition:decision:1")?,
        objective_digest: neuron_tick.objective_digest,
        candidate_set_digest: prompt.proposal_digest,
        minimum_confidence: probability(1)?,
        candidates: vec![
            ActionCandidate {
                candidate_id: id("action:no-change")?,
                legal: true,
                hard_veto: false,
                utility: FixedQ32::ZERO,
                confidence: ProbabilityQ32::ONE,
                support_digest: digest(b"lane-f-no-change-support"),
            },
            ActionCandidate {
                candidate_id: prompt_action.clone(),
                legal: true,
                hard_veto: false,
                utility: FixedQ32::from_raw(10),
                confidence: ProbabilityQ32::ONE,
                support_digest: prompt.proposal_digest,
            },
        ],
    })
    .map_err(|error| format!("intuition: {error:?}"))?;
    if intuition.authority.grants_any() {
        return Err("intuition authority invariant".to_string());
    }

    let intelligence = compose(PlanningRequest {
        plan_id: id("intelligence:plan:1")?,
        objective_digest: neuron_tick.objective_digest,
        context_digest: prompt.proposal_digest,
        snapshot_digest: checkpoint.digest(),
        candidates: vec![PlanCandidate {
            candidate_id: prompt_action,
            legal: true,
            hard_veto: false,
            score: FixedQ32::from_raw(10),
            support_digest: intuition.receipt_digest,
        }],
    })
    .map_err(|error| format!("intelligence: {error:?}"))?;
    if intelligence.authority.grants_any() || intelligence.effect_authority {
        return Err("intelligence authority invariant".to_string());
    }

    let selected_artifact = digest(b"lane-f-selected-artifact");
    let plasticity = propose_v2(ParameterProposalRequestV2 {
        proposal_id: id("plasticity:proposal:1")?,
        proposer_id: id("plasticity:proposer:1")?,
        evaluator_id: id("plasticity:evaluator:1")?,
        selected_artifact_digest: selected_artifact,
        window: ProposalWindowV2 {
            window_id: id("plasticity:window:1")?,
            window_digest: digest(b"lane-f-window"),
        },
        baseline_generation: generation(1)?,
        candidate_generation: generation(2)?,
        dataset_digest: digest(b"lane-f-dataset"),
        update_rule_digest: digest(b"lane-f-update-rule"),
        modulator_digest: neuron.checkpoint_after,
        modulator_broadcast_digest: digest(b"lane-f-broadcast"),
        eligibility_digest: checkpoint.digest(),
        evaluation_digest: intelligence.plan_digest,
        rollback_predecessor_digest: selected_artifact,
        norm_layers: vec![LayerNormDenominatorV2 {
            layer_id: id("layer:adapter")?,
            baseline_squared_l2_raw_q64: 1_000_000,
        }],
        candidates: vec![
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:no-change")?,
                kind: ParameterCandidateKindV2::NoChange,
                parameter_deltas: Vec::new(),
            },
            ParameterCandidateRequestV2 {
                candidate_id: id("candidate:update")?,
                kind: ParameterCandidateKindV2::Update,
                parameter_deltas: vec![ParameterDeltaV2 {
                    layer_id: id("layer:adapter")?,
                    parameter_id: id("parameter:adapter:1")?,
                    delta: FixedQ32::from_raw(1),
                    lower_bound: FixedQ32::from_raw(-10),
                    upper_bound: FixedQ32::from_raw(10),
                    evidence_digest: intelligence.plan_digest,
                }],
            },
        ],
    })
    .map_err(|error| format!("plasticity: {error:?}"))?;
    if plasticity.authority.grants_any()
        || plasticity.selected_artifact_digest != selected_artifact
        || plasticity.rollback_predecessor_digest != selected_artifact
    {
        return Err("plasticity authority/predecessor invariant".to_string());
    }

    let trace_digest = digest_trace(
        neuron.checkpoint_after,
        prompt.proposal_digest,
        intuition.receipt_digest,
        intelligence.plan_digest,
        plasticity.proposal_digest,
    );
    Ok(LaneFShadowReceipt {
        neuron,
        prompt,
        intuition,
        intelligence,
        plasticity,
        trace_digest,
    })
}

fn id(value: &str) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| format!("id {value}: {error}"))
}

fn generation(value: u64) -> Result<Generation, String> {
    Generation::new(value).map_err(|error| format!("generation {value}: {error}"))
}

fn probability(value: u64) -> Result<ProbabilityQ32, String> {
    ProbabilityQ32::from_raw(value).map_err(|error| format!("probability {value}: {error}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn digest_trace(
    neuron: Digest32,
    prompt: Digest32,
    intuition: Digest32,
    intelligence: Digest32,
    plasticity: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.lane-f.shadow-trace.v1".to_vec();
    for value in [neuron, prompt, intuition, intelligence, plasticity] {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vertical_is_deterministic_bounded_and_authority_free() {
        let first = run_lane_f_shadow().expect("first deterministic shadow run");
        let second = run_lane_f_shadow().expect("second deterministic shadow run");
        assert_eq!(first, second);
        assert!(!first.neuron.authority.grants_any());
        assert!(!first.prompt.authority().grants_any());
        assert!(!first.intuition.authority.grants_any());
        assert!(!first.intelligence.authority.grants_any());
        assert!(!first.plasticity.authority.grants_any());
        assert!(!first.trace_digest.is_zero());
    }

    #[test]
    fn current_artifact_and_rollback_predecessor_remain_identical() {
        let receipt = run_lane_f_shadow().expect("deterministic shadow run");
        assert_eq!(
            receipt.plasticity.selected_artifact_digest,
            receipt.plasticity.rollback_predecessor_digest
        );
        assert_eq!(receipt.plasticity.candidates.len(), 2);
        assert!(matches!(
            receipt.plasticity.candidates[0].kind,
            ParameterCandidateKindV2::NoChange
        ));
    }
}
