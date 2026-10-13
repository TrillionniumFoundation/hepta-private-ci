//! Fail-closed, signed final-use preflight for an already witnessed Neuron tick.
//!
//! This builds one exact operation identity for the independent kernel.authority
//! issuer. Caller-provided payload digests or a Model descriptor cannot replace
//! an actual NeuronRuntime/Witness read. This is NOT production CNS selection.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_types::Digest32;

const OPERATION: &str = "hepta.agentd.neuron.tick.v1";
const REQUEST_DOMAIN: &[u8] = b"hepta.agentd.neuron.tick-final-use.v1\0";

#[derive(Debug, thiserror::Error)]
pub enum AgentdNeuronSignedTickErrorV1 {
    #[error("missing or mismatched native Neuron final-use context")]
    InvalidContext,
    #[error("Neuron owner: {0}")]
    Neuron(#[from] NeuronRuntimeError),
    #[error("independent final-use authority: {0}")]
    Authority(#[from] FinalUseError),
}

/// A pure request proposal. It is NEVER a grant. Production callers must
/// obtain a genuine signed issuer grant and enter the effect fence; calling
/// this helper does not authorize model execution.
pub(crate) fn exact_neuron_tick_final_use_binding_v1(
    local: &NeuronLocalCheckpointBindingV1,
    input: &NeuronTickInputV1,
) -> Result<FinalUseBinding, AgentdNeuronSignedTickErrorV1> {
    if !local.validate_integrity()
        || input.objective_digest != local.scope.objective_digest
        || input.checkpoint_digest != local.anchor.checkpoint_digest
        || input.logical_sequence != local
            .anchor
            .sequence
            .checked_add(1)
            .ok_or(AgentdNeuronSignedTickErrorV1::InvalidContext)?
        || input.body_generation != Some(local.config.generation.get())
        || input.input_feature_digest
            != canonical_feature_vector_digest_v1(&input.feature_vector_q24)
    {
        return Err(AgentdNeuronSignedTickErrorV1::InvalidContext);
    }

    // Same V1 subject-scope domain and u32 length prefix as the immutable
    // Neuron Runtime. Never accept an arbitrary caller-submitted scope hash.
    let subject = input.subject_id.as_str().as_bytes();
    let len = u32::try_from(subject.len())
        .map_err(|_| AgentdNeuronSignedTickErrorV1::InvalidContext)?;
    let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    scope_bytes.extend_from_slice(&len.to_be_bytes());
    scope_bytes.extend_from_slice(subject);
    if Digest32::of_bytes(&scope_bytes) != local.scope.scope_digest {
        return Err(AgentdNeuronSignedTickErrorV1::InvalidContext);
    }

    // The input digest includes exact Q24 features, timestamp, NDU snapshot,
    // generation, current checkpoint and objective. The owner-issued local
    // binding covers the full model/toolchain/config, calibration, resource
    // envelope, Scope and separately acknowledged checkpoint.
    let input_digest = input.semantic_digest()?;
    let mut request = REQUEST_DOMAIN.to_vec();
    request.extend_from_slice(local.binding_digest.as_array());
    request.extend_from_slice(input_digest.as_array());
    let exact_request = Digest32::of_bytes(&request);
    Ok(FinalUseBinding {
        subject_id: input.subject_id.to_string(),
        destination_id: OPERATION.to_string(),
        request_sha256: *exact_request.as_array(),
        scope_sha256: *local.scope.scope_digest.as_array(),
        payload_sha256: *input_digest.as_array(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_neuron::JournalAnchor;
    use codex_hepta_neuron::JournalScope;
    use codex_hepta_neuron::NeuronCalibrationProfileV1;
    use codex_hepta_neuron::NeuronResourceEnvelopeV1;
    use codex_hepta_neuron::NeuronRuntimeConfigV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    fn digest(name: &str) -> Digest32 {
        Digest32::of_bytes(name.as_bytes())
    }

    fn setup() -> (NeuronLocalCheckpointBindingV1, NeuronTickInputV1) {
        let subject = StableId::new("subject.1").unwrap();
        let generation = Generation::new(3).unwrap();
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let objective = digest("objective");
        let config = NeuronRuntimeConfigV1 {
            config_id: StableId::new("config.1").unwrap(),
            generation,
            model_id: StableId::new("selected.model.1").unwrap(),
            model_manifest_digest: digest("manifest"),
            encoder_digest: digest("encoder"),
            head_digest: digest("head"),
            weights_digest: digest("weights"),
            tokenizer_digest: digest("tokenizer"),
            preprocessor_digest: digest("preprocessor"),
            quantization_digest: digest("quantization"),
            runtime_digest: digest("runtime"),
            device_digest: digest("device"),
            normalization_digest: digest("normalization"),
            native_config_digest: digest("native"),
            input_feature_dimension: 2,
            state_width: 5,
            modulator_dimension: 4,
            calibration: NeuronCalibrationProfileV1 {
                calibration_artifact_digest: digest("calibration"),
                ood_artifact_digest: digest("ood"),
                generation,
                valid_from_sequence: 1,
                expires_after_sequence: 32,
                zero_confidence_error_q24: 1,
                maximum_in_domain_error_q24: 1,
                minimum_confidence_ppm: 500_000,
                maximum_ood_ppm: 500_000,
                minimum_active_ppm: 100_000,
                maximum_active_ppm: 300_000,
                maximum_projection_count: 8,
                measured_ece_ppm: 10_000,
                maximum_ece_ppm: 50_000,
                measured_false_acceptance_ppm: 5_000,
                maximum_false_acceptance_ppm: 20_000,
            },
            resource_envelope: NeuronResourceEnvelopeV1 {
                p95_latency_micros: 1000,
                p99_latency_micros: 2000,
                transient_allocation_bytes: 4096,
                checkpoint_bytes: 4096,
                write_amplification_ppm: 1_000_000,
            },
        };
        let mut local = NeuronLocalCheckpointBindingV1 {
            config,
            scope: JournalScope {
                scope_digest: Digest32::of_bytes(&scope_bytes),
                objective_digest: objective,
            },
            anchor: JournalAnchor {
                sequence: 7,
                checkpoint_digest: digest("checkpoint-7"),
            },
            binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        local.binding_digest = local.computed_digest();
        let features = vec![1 << 22, -(1 << 21)];
        let tick = NeuronTickInputV1 {
            tick_id: StableId::new("tick.8").unwrap(),
            subject_id: subject,
            logical_sequence: 8,
            monotonic_time_micros: 8000,
            checkpoint_digest: local.anchor.checkpoint_digest,
            input_feature_digest: canonical_feature_vector_digest_v1(&features),
            feature_vector_q24: features,
            objective_digest: objective,
            ndu_snapshot_digest: digest("ndu-snapshot"),
            body_generation: Some(3),
            modulator_digest: None,
        };
        (local, tick)
    }

    #[test]
    fn final_use_proposal_binds_exact_current_model_checkpoint_and_input() {
        let (local, input) = setup();
        let original = exact_neuron_tick_final_use_binding_v1(&local, &input).unwrap();
        assert_eq!(original.destination_id, OPERATION);
        assert_eq!(original.subject_id, input.subject_id.as_str());
        assert_eq!(original.scope_sha256, *local.scope.scope_digest.as_array());
        assert_eq!(original.payload_sha256, *input.semantic_digest().unwrap().as_array());
        let mut changed = input.clone();
        changed.tick_id = StableId::new("tick.altered").unwrap();
        assert_ne!(
            original,
            exact_neuron_tick_final_use_binding_v1(&local, &changed).unwrap()
        );
        let mut changed = input.clone();
        changed.feature_vector_q24[0] += 1;
        changed.input_feature_digest =
            canonical_feature_vector_digest_v1(&changed.feature_vector_q24);
        assert_ne!(
            original,
            exact_neuron_tick_final_use_binding_v1(&local, &changed).unwrap()
        );
        let mut changed = local.clone();
        changed.config.weights_digest = digest("other-weights");
        changed.binding_digest = changed.computed_digest();
        assert_ne!(
            original,
            exact_neuron_tick_final_use_binding_v1(&changed, &input).unwrap()
        );
    }

    #[test]
    fn stale_checkpoint_wrong_subject_objective_generation_or_sequence_deny_before_grant() {
        let (local, input) = setup();
        let mut broken = input.clone();
        broken.checkpoint_digest = digest("stale");
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = input.clone();
        broken.logical_sequence += 1;
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = input.clone();
        broken.body_generation = None;
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = input.clone();
        broken.objective_digest = digest("other-objective");
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = input.clone();
        broken.subject_id = StableId::new("other-subject").unwrap();
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = input.clone();
        broken.feature_vector_q24[0] += 1;
        assert!(exact_neuron_tick_final_use_binding_v1(&local, &broken).is_err());
        let mut broken = local.clone();
        broken.binding_digest = digest("forged");
        assert!(exact_neuron_tick_final_use_binding_v1(&broken, &input).is_err());
    }
}
