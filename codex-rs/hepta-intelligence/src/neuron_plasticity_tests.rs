use super::*;

use codex_hepta_neuron::EligibilityTraceSampleV1;
use codex_hepta_neuron::IndependentModulatorV1;
use codex_hepta_neuron::ParameterGroupMapV1;
use codex_hepta_neuron::PlasticityTrustRegionV1;
use codex_hepta_neuron::accumulate_plasticity;
use codex_hepta_plasticity::Error as ProposalError;
use codex_hepta_plasticity::ProposalStatus;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn statistics() -> PlasticitySufficientStatisticsV1 {
    let history = vec![
        EligibilityTraceSampleV1 {
            checkpoint_digest: Digest32::of_bytes(b"checkpoint-1"),
            eligibility_q24: vec![Q / 8, -Q / 8],
        },
        EligibilityTraceSampleV1 {
            checkpoint_digest: Digest32::of_bytes(b"checkpoint-2"),
            eligibility_q24: vec![Q / 8, -Q / 8],
        },
    ];
    let modulator = IndependentModulatorV1 {
        observation_receipt_digest: Digest32::of_bytes(b"independent-outcome"),
        values_q24: vec![Q],
    };
    let groups = vec![
        ParameterGroupMapV1 {
            group_id: checked(StableId::new("group:a")),
            eligibility_projection_q24: vec![Q, 0],
            modulator_projection_q24: vec![Q],
        },
        ParameterGroupMapV1 {
            group_id: checked(StableId::new("group:b")),
            eligibility_projection_q24: vec![0, Q],
            modulator_projection_q24: vec![Q],
        },
    ];
    checked(accumulate_plasticity(
        &history,
        &modulator,
        &groups,
        PlasticityTrustRegionV1 {
            learning_rate_q24: Q / 64,
            maximum_group_delta_q24: Q / 16,
            maximum_global_l1_q24: Q / 16,
        },
    ))
}

fn binding(group: &str, layer: &str, parameter: &str) -> NeuronParameterBindingV1 {
    NeuronParameterBindingV1 {
        group_id: checked(StableId::new(group)),
        layer_id: checked(StableId::new(layer)),
        parameter_id: checked(StableId::new(parameter)),
        lower_bound_q24: -Q,
        upper_bound_q24: Q,
        evidence_digest: Digest32::of_bytes(format!("evidence:{group}").as_bytes()),
    }
}

fn envelope(norm: u128) -> NeuronParameterProposalEnvelopeV1 {
    NeuronParameterProposalEnvelopeV1 {
        proposal_id: checked(StableId::new("proposal:neuron:1")),
        proposer_id: checked(StableId::new("neuron.runtime")),
        evaluator_id: checked(StableId::new("learning.eval")),
        selected_artifact_digest: Digest32::of_bytes(b"selected-artifact"),
        window: ProposalWindowV2 {
            window_id: checked(StableId::new("window:1")),
            window_digest: Digest32::of_bytes(b"window"),
        },
        baseline_generation: checked(Generation::new(7)),
        candidate_generation: checked(Generation::new(8)),
        dataset_digest: Digest32::of_bytes(b"dataset"),
        update_rule_digest: Digest32::of_bytes(b"three-factor-update"),
        evaluation_digest: Digest32::of_bytes(b"evaluation"),
        rollback_predecessor_digest: Digest32::of_bytes(b"selected-artifact"),
        norm_layers: vec![
            LayerNormDenominatorV2 {
                layer_id: checked(StableId::new("layer:a")),
                baseline_squared_l2_raw_q64: norm,
            },
            LayerNormDenominatorV2 {
                layer_id: checked(StableId::new("layer:b")),
                baseline_squared_l2_raw_q64: norm,
            },
        ],
        no_change_candidate_id: checked(StableId::new("candidate:no-change")),
        update_candidate_id: checked(StableId::new("candidate:update")),
        parameter_bindings: vec![
            binding("group:a", "layer:a", "parameter:a"),
            binding("group:b", "layer:b", "parameter:b"),
        ],
    }
}

#[test]
fn neuron_statistics_flow_into_existing_v2_trust_region_without_authority() {
    let proposal = checked(propose_neuron_parameter_candidate_v2(
        &statistics(),
        envelope(1_u128 << 80),
    ));
    assert_eq!(
        proposal.status,
        ProposalStatus::RequiresIndependentAcceptance
    );
    assert!(!proposal.authority.grants_any());
    assert_eq!(proposal.candidates.len(), 2);
    let update = proposal
        .candidates
        .iter()
        .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .expect("update candidate");
    assert_eq!(update.parameter_deltas.len(), 2);
    assert_eq!(proposal.modulator_digest, statistics().modulator_digest);
    assert_eq!(
        proposal.modulator_broadcast_digest,
        statistics().modulator_broadcast_digest
    );
    assert_eq!(proposal.eligibility_digest, statistics().eligibility_digest);
}

#[test]
fn artifact_relative_v2_norm_gate_can_reject_neuron_local_delta() {
    let error = propose_neuron_parameter_candidate_v2(&statistics(), envelope(1)).err();
    assert!(matches!(
        error,
        Some(NeuronPlasticityBridgeError::Proposal(
            ProposalError::PerLayerTrustRegionExceeded(_)
        ))
    ));
}

#[test]
fn bridge_requires_exact_group_to_parameter_bijection() {
    let mut request = envelope(1_u128 << 80);
    request.parameter_bindings[0].group_id = checked(StableId::new("group:wrong"));
    assert!(matches!(
        propose_neuron_parameter_candidate_v2(&statistics(), request),
        Err(NeuronPlasticityBridgeError::GroupBindingMismatch(_))
    ));
}
