//! Bounded Root deployment data for the exact original Cell configuration.
//! Decoding creates data only; semantic validation and the independent Initial
//! task digest still have to agree before descriptors can be retained.

use std::io;

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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CellData {
    cell_id: String,
    bundle_digest: [u8; 32],
    state_schema_digest: [u8; 32],
    runtime: RuntimeData,
    native: NativeData,
    candidates: Vec<CandidateData>,
    max_input_bytes: usize,
    max_queue_age_micros: u64,
    max_resident_bytes: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateData {
    candidate_id: String,
    activation_index: usize,
    kind: CandidateKind,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum CandidateKind {
    Action,
    Abstain,
    SlowPath,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeData {
    model_digest: [u8; 32],
    normalization_digest: [u8; 32],
    generation: u64,
    width: usize,
    top_k: usize,
    temporal_decay_q24: i64,
    inhibition_gain_q24: i64,
    inhibition: Vec<EdgeData>,
    activity_decay_q24: i64,
    target_activity_q24: i64,
    threshold_rate_q24: i64,
    threshold_min_q24: i64,
    threshold_max_q24: i64,
    eligibility_decay_q24: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EdgeData {
    source: usize,
    target: usize,
    weight_q24: i64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeData {
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
    calibration: CalibrationData,
    resource_envelope: ResourceData,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CalibrationData {
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResourceData {
    p95_latency_micros: u64,
    p99_latency_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    write_amplification_ppm: u32,
}

impl CellData {
    pub(super) fn into_definition(self) -> io::Result<CellDefinitionV1> {
        let native = SparseConfig {
            model_digest: Digest32::from_array(self.native.model_digest),
            normalization_digest: Digest32::from_array(self.native.normalization_digest),
            generation: Generation::new(self.native.generation).map_err(io::Error::other)?,
            width: self.native.width,
            top_k: self.native.top_k,
            temporal_decay_q24: self.native.temporal_decay_q24,
            inhibition_gain_q24: self.native.inhibition_gain_q24,
            inhibition: self
                .native
                .inhibition
                .into_iter()
                .map(|edge| InhibitoryEdge {
                    source: edge.source,
                    target: edge.target,
                    weight_q24: edge.weight_q24,
                })
                .collect(),
            activity_decay_q24: self.native.activity_decay_q24,
            target_activity_q24: self.native.target_activity_q24,
            threshold_rate_q24: self.native.threshold_rate_q24,
            threshold_min_q24: self.native.threshold_min_q24,
            threshold_max_q24: self.native.threshold_max_q24,
            eligibility_decay_q24: self.native.eligibility_decay_q24,
        };
        let runtime = self.runtime;
        let calibration = runtime.calibration;
        let resources = runtime.resource_envelope;
        let runtime = NeuronRuntimeConfigV1 {
            config_id: StableId::new(runtime.config_id).map_err(io::Error::other)?,
            generation: Generation::new(runtime.generation).map_err(io::Error::other)?,
            model_id: StableId::new(runtime.model_id).map_err(io::Error::other)?,
            model_manifest_digest: Digest32::from_array(runtime.model_manifest_digest),
            encoder_digest: Digest32::from_array(runtime.encoder_digest),
            head_digest: Digest32::from_array(runtime.head_digest),
            weights_digest: Digest32::from_array(runtime.weights_digest),
            tokenizer_digest: Digest32::from_array(runtime.tokenizer_digest),
            preprocessor_digest: Digest32::from_array(runtime.preprocessor_digest),
            quantization_digest: Digest32::from_array(runtime.quantization_digest),
            runtime_digest: Digest32::from_array(runtime.runtime_digest),
            device_digest: Digest32::from_array(runtime.device_digest),
            normalization_digest: Digest32::from_array(runtime.normalization_digest),
            native_config_digest: Digest32::from_array(runtime.native_config_digest),
            input_feature_dimension: runtime.input_feature_dimension,
            state_width: runtime.state_width,
            modulator_dimension: runtime.modulator_dimension,
            calibration: NeuronCalibrationProfileV1 {
                calibration_artifact_digest: Digest32::from_array(
                    calibration.calibration_artifact_digest,
                ),
                ood_artifact_digest: Digest32::from_array(calibration.ood_artifact_digest),
                generation: Generation::new(calibration.generation).map_err(io::Error::other)?,
                valid_from_sequence: calibration.valid_from_sequence,
                expires_after_sequence: calibration.expires_after_sequence,
                zero_confidence_error_q24: calibration.zero_confidence_error_q24,
                maximum_in_domain_error_q24: calibration.maximum_in_domain_error_q24,
                minimum_confidence_ppm: calibration.minimum_confidence_ppm,
                maximum_ood_ppm: calibration.maximum_ood_ppm,
                minimum_active_ppm: calibration.minimum_active_ppm,
                maximum_active_ppm: calibration.maximum_active_ppm,
                maximum_projection_count: calibration.maximum_projection_count,
                measured_ece_ppm: calibration.measured_ece_ppm,
                maximum_ece_ppm: calibration.maximum_ece_ppm,
                measured_false_acceptance_ppm: calibration.measured_false_acceptance_ppm,
                maximum_false_acceptance_ppm: calibration.maximum_false_acceptance_ppm,
            },
            resource_envelope: NeuronResourceEnvelopeV1 {
                p95_latency_micros: resources.p95_latency_micros,
                p99_latency_micros: resources.p99_latency_micros,
                transient_allocation_bytes: resources.transient_allocation_bytes,
                checkpoint_bytes: resources.checkpoint_bytes,
                write_amplification_ppm: resources.write_amplification_ppm,
            },
        };
        let candidates = self
            .candidates
            .into_iter()
            .map(|candidate| {
                Ok(CellCandidateV1 {
                    candidate_id: StableId::new(candidate.candidate_id)
                        .map_err(io::Error::other)?,
                    activation_index: candidate.activation_index,
                    kind: match candidate.kind {
                        CandidateKind::Action => CellCandidateKindV1::Action,
                        CandidateKind::Abstain => CellCandidateKindV1::Abstain,
                        CandidateKind::SlowPath => CellCandidateKindV1::SlowPath,
                    },
                })
            })
            .collect::<io::Result<Vec<_>>>()?;
        let definition = CellDefinitionV1 {
            cell_id: StableId::new(self.cell_id).map_err(io::Error::other)?,
            bundle_digest: Digest32::from_array(self.bundle_digest),
            state_schema_digest: Digest32::from_array(self.state_schema_digest),
            runtime,
            native,
            candidates,
            max_input_bytes: self.max_input_bytes,
            max_queue_age_micros: self.max_queue_age_micros,
            max_resident_bytes: self.max_resident_bytes,
        };
        definition.semantic_digest().map_err(io::Error::other)?;
        Ok(definition)
    }
}
