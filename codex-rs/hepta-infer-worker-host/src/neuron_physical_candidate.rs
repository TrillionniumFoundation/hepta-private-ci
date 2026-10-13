//! Read-only cross-owner correlation of selected Neuron Model descriptor,
//! witnessed Agentd model tuple, and real preopened-file Worker model load.
//! No CNS route, deployment authorization, final-use or NDU power is issued.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_agentd::AgentdNeuronOwner;
use codex_hepta_agentd::NeuronCandidateModelArtifactV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFileBoundModelLoadV1;
use crate::model_worker::NeuronPreopenedWeightModelDriver;
use crate::model_worker::NeuronWeightFileDiagnosticErrorV1;

const DOMAIN: &[u8] = b"hepta.neuron.candidate-physical-load-correlation.diagnostic.v1\0";

/// A checksum-only observation, never a production selection or CAS signature.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCandidatePhysicalLoadDiagnosticV1 {
    pub candidate_digest: Digest32,
    pub local_checkpoint_binding_digest: Digest32,
    pub file_bound_model_load_digest: Digest32,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_load_revision: u64,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronCandidatePhysicalLoadDiagnosticV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        for value in [
            self.candidate_digest,
            self.local_checkpoint_binding_digest,
            self.file_bound_model_load_digest,
        ] {
            bytes.extend_from_slice(value.as_array());
        }
        let id = self.worker_id.as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&self.worker_generation.to_be_bytes());
        bytes.extend_from_slice(&self.model_load_revision.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.candidate_digest.is_zero()
            && !self.local_checkpoint_binding_digest.is_zero()
            && !self.file_bound_model_load_digest.is_zero()
            && !self.worker_id.is_empty()
            && self.worker_generation != 0
            && self.model_load_revision != 0
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronCandidatePhysicalLoadErrorV1 {
    Witness(NeuronRuntimeError),
    Worker(NeuronWeightFileDiagnosticErrorV1),
    Mismatch(&'static str),
}

impl fmt::Display for NeuronCandidatePhysicalLoadErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for NeuronCandidatePhysicalLoadErrorV1 {}
impl From<NeuronRuntimeError> for NeuronCandidatePhysicalLoadErrorV1 {
    fn from(value: NeuronRuntimeError) -> Self {
        Self::Witness(value)
    }
}
impl From<NeuronWeightFileDiagnosticErrorV1> for NeuronCandidatePhysicalLoadErrorV1 {
    fn from(value: NeuronWeightFileDiagnosticErrorV1) -> Self {
        Self::Worker(value)
    }
}

/// The candidate has opaque fields and must have come from independent
/// Agentd selector/CURRENT verification, NOT a user-constructed DTO.
/// This is a diagnostic snapshot only: the caller must independently refresh
/// Artifact CURRENT, route/fence and source permission at actual final-use.
/// Worker process generation and Neuron model generation are distinct.
pub fn read_neuron_candidate_physical_load_v1<D, W, P>(
    worker: &InferenceWorker<D>,
    agentd: &AgentdNeuronOwner<W, P>,
    candidate: &NeuronCandidateModelArtifactV1,
    file_bound_load: &NeuronFileBoundModelLoadV1,
    now_ms: u64,
) -> Result<NeuronCandidatePhysicalLoadDiagnosticV1, NeuronCandidatePhysicalLoadErrorV1>
where
    D: ModelDriver + NeuronPreopenedWeightModelDriver,
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    if !candidate.validate_integrity() || !file_bound_load.validate_integrity() {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("candidate/load integrity"));
    }
    let before = agentd.read_local_checkpoint_binding_v1()?;
    if !before.validate_integrity()
        || candidate.local_checkpoint_binding_digest() != before.binding_digest
    {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("stale local candidate"));
    }
    worker.revalidate_file_bound_model_load_v1(now_ms, file_bound_load)?;
    let load = file_bound_load.model_load();
    if load.model_id != before.config.model_id.as_str()
        || file_bound_load.loaded_weights_digest() != before.config.weights_digest
    {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("physical weight/model mismatch"));
    }
    let manifest = worker
        .inspected_neuron_manifest(now_ms, before.config.model_id.as_str())
        .map_err(NeuronWeightFileDiagnosticErrorV1::Worker)?;
    if !manifest_matches_local(&before.config, manifest) {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("Worker model tuple mismatch"));
    }
    let after = agentd.read_local_checkpoint_binding_v1()?;
    worker.revalidate_file_bound_model_load_v1(now_ms, file_bound_load)?;
    if before != after {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("checkpoint advanced during read"));
    }
    let mut result = NeuronCandidatePhysicalLoadDiagnosticV1 {
        candidate_digest: candidate.candidate_digest(),
        local_checkpoint_binding_digest: before.binding_digest,
        file_bound_model_load_digest: file_bound_load.computed_digest(),
        worker_id: worker.worker_id().to_owned(),
        worker_generation: worker.worker_generation(),
        model_load_revision: file_bound_load.load_revision(),
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.diagnostic_digest = result.computed_digest();
    if !result.validate_integrity() {
        return Err(NeuronCandidatePhysicalLoadErrorV1::Mismatch("diagnostic invalid"));
    }
    Ok(result)
}

fn manifest_matches_local(config: &NeuronRuntimeConfigV1, loaded: &ModelManifest) -> bool {
    loaded.model_id == config.model_id.as_str()
        && loaded.model_digest == config.model_manifest_digest.to_string()
        && loaded.weights_digest == config.weights_digest.to_string()
        && loaded.tokenizer_digest == config.tokenizer_digest.to_string()
        && loaded.preprocessor_digest == config.preprocessor_digest.to_string()
        && loaded.quantization_digest == config.quantization_digest.to_string()
        && loaded.runtime_digest == config.runtime_digest.to_string()
        && loaded.device_digest == config.device_digest.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_neuron::NeuronCalibrationProfileV1;
    use codex_hepta_neuron::NeuronResourceEnvelopeV1;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn config() -> NeuronRuntimeConfigV1 {
        let generation = Generation::new(2).unwrap();
        NeuronRuntimeConfigV1 {
            config_id: StableId::new("config.1").unwrap(),
            generation,
            model_id: StableId::new("model.1").unwrap(),
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
            input_feature_dimension: 3,
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
        }
    }

    #[test]
    fn exact_model_tuple_matches_and_every_worker_identity_drift_denies() {
        let expected = config();
        let manifest = ModelManifest {
            model_id: expected.model_id.to_string(),
            model_digest: expected.model_manifest_digest.to_string(),
            weights_digest: expected.weights_digest.to_string(),
            tokenizer_digest: expected.tokenizer_digest.to_string(),
            preprocessor_digest: expected.preprocessor_digest.to_string(),
            quantization_digest: expected.quantization_digest.to_string(),
            runtime_digest: expected.runtime_digest.to_string(),
            device_digest: expected.device_digest.to_string(),
            maximum_tokens: 128,
        };
        assert!(manifest_matches_local(&expected, &manifest));
        let changes: [fn(&mut ModelManifest); 8] = [
            |m| m.model_id = "other-model".into(),
            |m| m.model_digest = digest("other-manifest").to_string(),
            |m| m.weights_digest = digest("other-weights").to_string(),
            |m| m.tokenizer_digest = digest("other-tokenizer").to_string(),
            |m| m.preprocessor_digest = digest("other-preprocessor").to_string(),
            |m| m.quantization_digest = digest("other-quantization").to_string(),
            |m| m.runtime_digest = digest("other-runtime").to_string(),
            |m| m.device_digest = digest("other-device").to_string(),
        ];
        for mutate in changes {
            let mut drift = manifest.clone();
            mutate(&mut drift);
            assert!(!manifest_matches_local(&expected, &drift));
        }
    }

    #[test]
    fn candidate_physical_diagnostic_never_authorizes_use() {
        let mut value = NeuronCandidatePhysicalLoadDiagnosticV1 {
            candidate_digest: digest("candidate"),
            local_checkpoint_binding_digest: digest("local"),
            file_bound_model_load_digest: digest("load"),
            worker_id: "worker.1".to_owned(),
            worker_generation: 4,
            model_load_revision: 1,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.diagnostic_digest = value.computed_digest();
        assert!(value.validate_integrity());
        value.worker_generation = 0;
        assert!(!value.validate_integrity());
        value.worker_generation = 4;
        value.authority = AuthorityPosture::DENY_ALL;
        value.local_checkpoint_binding_digest = digest("forged");
        assert!(!value.validate_integrity());
    }
}
