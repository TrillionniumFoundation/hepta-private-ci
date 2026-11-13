//! Complete public Cell definition data from a protected Root deployment file.
//! Conversion grants no authority: the original semantic digest, model worker
//! and published-task factory validate every field against the real selection.

use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellCandidateV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::InhibitoryEdge;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::invalid;
use crate::AgentdError;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Definition {
    cell_id: String,
    bundle_digest: [u8; 32],
    state_schema_digest: [u8; 32],
    runtime: Runtime,
    native: Native,
    candidates: Vec<Candidate>,
    max_input_bytes: usize,
    max_queue_age_micros: u64,
    max_resident_bytes: u64,
}

impl Definition {
    pub(super) fn into_original(self) -> Result<CellDefinitionV1, AgentdError> {
        let definition = CellDefinitionV1 {
            cell_id: StableId::new(self.cell_id).map_err(invalid)?,
            bundle_digest: Digest32::from_array(self.bundle_digest),
            state_schema_digest: Digest32::from_array(self.state_schema_digest),
            runtime: self.runtime.into_original()?,
            native: self.native.into_original()?,
            candidates: self.candidates.into_iter().map(Candidate::into_original)
                .collect::<Result<_, _>>()?,
            max_input_bytes: self.max_input_bytes,
            max_queue_age_micros: self.max_queue_age_micros,
            max_resident_bytes: self.max_resident_bytes,
        };
        definition.semantic_digest().map_err(invalid)?;
        Ok(definition)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate {
    candidate_id: String,
    activation_index: usize,
    kind: CandidateKind,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum CandidateKind { Action, Abstain, SlowPath }

impl Candidate {
    fn into_original(self) -> Result<CellCandidateV1, AgentdError> {
        Ok(CellCandidateV1 {
            candidate_id: StableId::new(self.candidate_id).map_err(invalid)?,
            activation_index: self.activation_index,
            kind: match self.kind {
                CandidateKind::Action => CellCandidateKindV1::Action,
                CandidateKind::Abstain => CellCandidateKindV1::Abstain,
                CandidateKind::SlowPath => CellCandidateKindV1::SlowPath,
            },
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Runtime {
    config_id: String,
    generation: u64,
    model_id: String,
    model_manifest_digest: [u8; 32],
    encoder_digest: [u8; 32],
    head_digest: [u8; 32],
    weights_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    preprocessor_digest: [u8; 32],
    quantization_digest: [u8; 32],
    runtime_digest: [u8; 32],
    device_digest: [u8; 32],
    normalization_digest: [u8; 32],
    native_config_digest: [u8; 32],
    input_feature_dimension: usize,
    state_width: usize,
    modulator_dimension: usize,
    calibration: Calibration,
    resource_envelope: ResourceEnvelope,
}

impl Runtime {
    fn into_original(self) -> Result<NeuronRuntimeConfigV1, AgentdError> {
        Ok(NeuronRuntimeConfigV1 {
            config_id: StableId::new(self.config_id).map_err(invalid)?,
            generation: Generation::new(self.generation).map_err(invalid)?,
            model_id: StableId::new(self.model_id).map_err(invalid)?,
            model_manifest_digest: Digest32::from_array(self.model_manifest_digest),
            encoder_digest: Digest32::from_array(self.encoder_digest),
            head_digest: Digest32::from_array(self.head_digest),
            weights_digest: Digest32::from_array(self.weights_digest),
            tokenizer_digest: Digest32::from_array(self.tokenizer_digest),
            preprocessor_digest: Digest32::from_array(self.preprocessor_digest),
            quantization_digest: Digest32::from_array(self.quantization_digest),
            runtime_digest: Digest32::from_array(self.runtime_digest),
            device_digest: Digest32::from_array(self.device_digest),
            normalization_digest: Digest32::from_array(self.normalization_digest),
            native_config_digest: Digest32::from_array(self.native_config_digest),
            input_feature_dimension: self.input_feature_dimension,
            state_width: self.state_width,
            modulator_dimension: self.modulator_dimension,
            calibration: self.calibration.into_original()?,
            resource_envelope: self.resource_envelope.into_original(),
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Calibration {
    calibration_artifact_digest: [u8; 32],
    ood_artifact_digest: [u8; 32],
    generation: u64,
    valid_from_sequence: u64,
    expires_after_sequence: u64,
    zero_confidence_error_q24: i64,
    maximum_in_domain_error_q24: i64,
    minimum_confidence_ppm: u32,
    maximum_ood_ppm: u32,
    minimum_active_ppm: u32,
    maximum_active_ppm: u32,
    maximum_projection_count: u32,
    measured_ece_ppm: u32,
    maximum_ece_ppm: u32,
    measured_false_acceptance_ppm: u32,
    maximum_false_acceptance_ppm: u32,
}

impl Calibration {
    fn into_original(self) -> Result<NeuronCalibrationProfileV1, AgentdError> {
        Ok(NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::from_array(self.calibration_artifact_digest),
            ood_artifact_digest: Digest32::from_array(self.ood_artifact_digest),
            generation: Generation::new(self.generation).map_err(invalid)?,
            valid_from_sequence: self.valid_from_sequence,
            expires_after_sequence: self.expires_after_sequence,
            zero_confidence_error_q24: self.zero_confidence_error_q24,
            maximum_in_domain_error_q24: self.maximum_in_domain_error_q24,
            minimum_confidence_ppm: self.minimum_confidence_ppm,
            maximum_ood_ppm: self.maximum_ood_ppm,
            minimum_active_ppm: self.minimum_active_ppm,
            maximum_active_ppm: self.maximum_active_ppm,
            maximum_projection_count: self.maximum_projection_count,
            measured_ece_ppm: self.measured_ece_ppm,
            maximum_ece_ppm: self.maximum_ece_ppm,
            measured_false_acceptance_ppm: self.measured_false_acceptance_ppm,
            maximum_false_acceptance_ppm: self.maximum_false_acceptance_ppm,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceEnvelope {
    p95_latency_micros: u64,
    p99_latency_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    write_amplification_ppm: u32,
}

impl ResourceEnvelope {
    fn into_original(self) -> NeuronResourceEnvelopeV1 {
        NeuronResourceEnvelopeV1 {
            p95_latency_micros: self.p95_latency_micros,
            p99_latency_micros: self.p99_latency_micros,
            transient_allocation_bytes: self.transient_allocation_bytes,
            checkpoint_bytes: self.checkpoint_bytes,
            write_amplification_ppm: self.write_amplification_ppm,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Native {
    model_digest: [u8; 32],
    normalization_digest: [u8; 32],
    generation: u64,
    width: usize,
    top_k: usize,
    temporal_decay_q24: i64,
    inhibition_gain_q24: i64,
    inhibition: Vec<Inhibition>,
    activity_decay_q24: i64,
    target_activity_q24: i64,
    threshold_rate_q24: i64,
    threshold_min_q24: i64,
    threshold_max_q24: i64,
    eligibility_decay_q24: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Inhibition { source: usize, target: usize, weight_q24: i64 }

impl Native {
    fn into_original(self) -> Result<SparseConfig, AgentdError> {
        Ok(SparseConfig {
            model_digest: Digest32::from_array(self.model_digest),
            normalization_digest: Digest32::from_array(self.normalization_digest),
            generation: Generation::new(self.generation).map_err(invalid)?,
            width: self.width,
            top_k: self.top_k,
            temporal_decay_q24: self.temporal_decay_q24,
            inhibition_gain_q24: self.inhibition_gain_q24,
            inhibition: self.inhibition.into_iter().map(|edge| InhibitoryEdge {
                source: edge.source, target: edge.target, weight_q24: edge.weight_q24,
            }).collect(),
            activity_decay_q24: self.activity_decay_q24,
            target_activity_q24: self.target_activity_q24,
            threshold_rate_q24: self.threshold_rate_q24,
            threshold_min_q24: self.threshold_min_q24,
            threshold_max_q24: self.threshold_max_q24,
            eligibility_decay_q24: self.eligibility_decay_q24,
        })
    }
}
