//! Original Cell definition data from the Root-approved ordinary descriptor.
//! These conversions copy values; the original model, Cell and CURRENT owners
//! validate the complete definition and all executable/resource bindings.

use codex_hepta_neuron::{NeuronCalibrationProfileV1, NeuronResourceEnvelopeV1, NeuronRuntimeConfigV1, SparseConfig, InhibitoryEdge, CellCandidateV1, CellDefinitionV1, CellCandidateKindV1};
use codex_hepta_types::{Digest32, Generation, StableId};
use serde::{Deserialize, Serialize};
use crate::AgentdError;
use super::deployment_error;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum OriginalCandidateKindData { Action, Abstain, SlowPath }

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCalibrationData {
    pub calibration_artifact_digest: [u8; 32],
    pub ood_artifact_digest: [u8; 32],
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub zero_confidence_error_q24: i64,
    pub maximum_in_domain_error_q24: i64,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_active_ppm: u32,
    pub maximum_active_ppm: u32,
    pub maximum_projection_count: u32,
    pub measured_ece_ppm: u32,
    pub maximum_ece_ppm: u32,
    pub measured_false_acceptance_ppm: u32,
    pub maximum_false_acceptance_ppm: u32,
}

impl OriginalCalibrationData {
    pub(super) fn original(&self) -> Result<NeuronCalibrationProfileV1, AgentdError> {
        Ok(NeuronCalibrationProfileV1 {
            calibration_artifact_digest: Digest32::from_array(self.calibration_artifact_digest),
            ood_artifact_digest: Digest32::from_array(self.ood_artifact_digest),
            generation: Generation::new(self.generation).map_err(deployment_error)?,
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

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalResourceEnvelopeData {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}

impl OriginalResourceEnvelopeData {
    pub(super) fn original(&self) -> Result<NeuronResourceEnvelopeV1, AgentdError> {
        Ok(NeuronResourceEnvelopeV1 {
            p95_latency_micros: self.p95_latency_micros,
            p99_latency_micros: self.p99_latency_micros,
            transient_allocation_bytes: self.transient_allocation_bytes,
            checkpoint_bytes: self.checkpoint_bytes,
            write_amplification_ppm: self.write_amplification_ppm,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCellRuntimeData {
    pub config_id: String,
    pub generation: u64,
    pub model_id: String,
    pub model_manifest_digest: [u8; 32],
    pub encoder_digest: [u8; 32],
    pub head_digest: [u8; 32],
    pub weights_digest: [u8; 32],
    pub tokenizer_digest: [u8; 32],
    pub preprocessor_digest: [u8; 32],
    pub quantization_digest: [u8; 32],
    pub runtime_digest: [u8; 32],
    pub device_digest: [u8; 32],
    pub normalization_digest: [u8; 32],
    pub native_config_digest: [u8; 32],
    pub input_feature_dimension: usize,
    pub state_width: usize,
    pub modulator_dimension: usize,
    pub calibration: OriginalCalibrationData,
    pub resource_envelope: OriginalResourceEnvelopeData,
}

impl OriginalCellRuntimeData {
    pub(super) fn original(&self) -> Result<NeuronRuntimeConfigV1, AgentdError> {
        Ok(NeuronRuntimeConfigV1 {
            config_id: StableId::new(&self.config_id).map_err(deployment_error)?,
            generation: Generation::new(self.generation).map_err(deployment_error)?,
            model_id: StableId::new(&self.model_id).map_err(deployment_error)?,
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
            calibration: self.calibration.original()?,
            resource_envelope: self.resource_envelope.original()?,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSparseData {
    pub model_digest: [u8; 32],
    pub normalization_digest: [u8; 32],
    pub generation: u64,
    pub width: usize,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<OriginalInhibitoryEdgeData>,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}

impl OriginalSparseData {
    pub(super) fn original(&self) -> Result<SparseConfig, AgentdError> {
        Ok(SparseConfig {
            model_digest: Digest32::from_array(self.model_digest),
            normalization_digest: Digest32::from_array(self.normalization_digest),
            generation: Generation::new(self.generation).map_err(deployment_error)?,
            width: self.width,
            top_k: self.top_k,
            temporal_decay_q24: self.temporal_decay_q24,
            inhibition_gain_q24: self.inhibition_gain_q24,
            inhibition: self.inhibition.iter().map(OriginalInhibitoryEdgeData::original).collect::<Result<_, _>>()?,
            activity_decay_q24: self.activity_decay_q24,
            target_activity_q24: self.target_activity_q24,
            threshold_rate_q24: self.threshold_rate_q24,
            threshold_min_q24: self.threshold_min_q24,
            threshold_max_q24: self.threshold_max_q24,
            eligibility_decay_q24: self.eligibility_decay_q24,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalInhibitoryEdgeData {
    pub source: usize,
    pub target: usize,
    pub weight_q24: i64,
}

impl OriginalInhibitoryEdgeData {
    pub(super) fn original(&self) -> Result<InhibitoryEdge, AgentdError> {
        Ok(InhibitoryEdge {
            source: self.source,
            target: self.target,
            weight_q24: self.weight_q24,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCandidateData {
    pub candidate_id: String,
    pub activation_index: usize,
    pub kind: OriginalCandidateKindData,
}

impl OriginalCandidateData {
    pub(super) fn original(&self) -> Result<CellCandidateV1, AgentdError> {
        Ok(CellCandidateV1 {
            candidate_id: StableId::new(&self.candidate_id).map_err(deployment_error)?,
            activation_index: self.activation_index,
            kind: match self.kind { OriginalCandidateKindData::Action => CellCandidateKindV1::Action, OriginalCandidateKindData::Abstain => CellCandidateKindV1::Abstain, OriginalCandidateKindData::SlowPath => CellCandidateKindV1::SlowPath },
        })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalCellDefinitionData {
    pub cell_id: String,
    pub bundle_digest: [u8; 32],
    pub state_schema_digest: [u8; 32],
    pub runtime: OriginalCellRuntimeData,
    pub native: OriginalSparseData,
    pub candidates: Vec<OriginalCandidateData>,
    pub max_input_bytes: usize,
    pub max_queue_age_micros: u64,
    pub max_resident_bytes: u64,
}

impl OriginalCellDefinitionData {
    pub(super) fn original(&self) -> Result<CellDefinitionV1, AgentdError> {
        Ok(CellDefinitionV1 {
            cell_id: StableId::new(&self.cell_id).map_err(deployment_error)?,
            bundle_digest: Digest32::from_array(self.bundle_digest),
            state_schema_digest: Digest32::from_array(self.state_schema_digest),
            runtime: self.runtime.original()?,
            native: self.native.original()?,
            candidates: self.candidates.iter().map(OriginalCandidateData::original).collect::<Result<_, _>>()?,
            max_input_bytes: self.max_input_bytes,
            max_queue_age_micros: self.max_queue_age_micros,
            max_resident_bytes: self.max_resident_bytes,
        })
    }
}

