//! Deterministic, bounded temporal signal runtime for qualification use.
//!
//! Pure mechanisms emit state and signal receipts. An optional host-authorized
//! journal persists owned checkpoints; it grants no model dispatch, physical
//! effect, selection, promotion or release authority.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

mod artifact_binding;
mod deletion;
mod generation_store_v2;
mod inference_control;
mod journal;
mod journal_lock;
mod operation_codec;
mod operation_store;
mod plasticity;
mod population_v2;
mod protocol;
mod qualification;
mod runtime;
mod runtime_types;
mod semantic_v2;
mod sparse;
mod store_manifest;
mod witness;

pub use artifact_binding::NEURON_CALIBRATION_SUMMARY_SCHEMA_V1;
pub use artifact_binding::NEURON_OOD_SUMMARY_SCHEMA_V1;
pub use deletion::DeletionRebuildError;
pub use deletion::NeuronDeletionRebuildPlanV1;
pub use deletion::NeuronDeletionRebuildReceiptV1;
pub use deletion::validate_deletion_rebuild;
pub use generation_store_v2::FileNeuronGenerationStoreV2;
pub use generation_store_v2::GenerationStoreError;
pub use generation_store_v2::NeuronGenerationAdmissionV2;
pub use generation_store_v2::NeuronGenerationCommitResultV2;
pub use generation_store_v2::NeuronGenerationCommitV2;
pub use generation_store_v2::NeuronGenerationRecordV2;
pub use generation_store_v2::NeuronGenerationStoreContextV2;
pub use inference_control::InferenceControlModelPort;
pub use inference_control::NeuronInferenceControlPort;
pub use journal::JournalAnchor;
pub use journal::JournalError;
pub use journal::JournalScope;
pub use journal::SparseJournal;
pub use operation_store::FileNeuronOperationStore;
pub use operation_store::OperationStoreError;
pub use plasticity::EligibilityTraceSampleV1;
pub use plasticity::IndependentModulatorV1;
pub use plasticity::ParameterGroupDeltaV1;
pub use plasticity::ParameterGroupMapV1;
pub use plasticity::PlasticityError;
pub use plasticity::PlasticitySufficientStatisticsV1;
pub use plasticity::PlasticityTrustRegionV1;
pub use plasticity::accumulate_plasticity;
pub use population_v2::ActivationPopulationV2;
pub use population_v2::PopulationSparseCheckpointV2;
pub use population_v2::PopulationSparseConfigV2;
pub use population_v2::PopulationSparseError;
pub use population_v2::PopulationSparseSignalReceiptV2;
pub use population_v2::PopulationSparseTickV2;
pub use population_v2::TemporalProjectionEdgeV2;
pub use population_v2::population_sparse_tick_v2;
pub use protocol::NeuronActivationSummaryV1;
pub use protocol::NeuronCheckpointV1;
pub use protocol::NeuronProtocolError;
pub use protocol::NeuronRuntimeConfigProtocolV1;
pub use protocol::NeuronTickReceiptProtocolV1;
pub use protocol::canonical_checkpoint_v1;
pub use protocol::canonical_runtime_config_v1;
pub use protocol::canonical_tick_receipt_v1;
pub use protocol::decode_neuron_checkpoint_v1;
pub use protocol::decode_neuron_runtime_config_v1;
pub use protocol::decode_neuron_signal_receipt_v1;
pub use protocol::decode_neuron_tick_input_v1;
pub use protocol::decode_neuron_tick_receipt_v1;
pub use protocol::encode_neuron_checkpoint_v1;
pub use protocol::encode_neuron_runtime_config_v1;
pub use protocol::encode_neuron_signal_receipt_v1;
pub use protocol::encode_neuron_tick_input_v1;
pub use protocol::encode_neuron_tick_receipt_v1;
pub use qualification::NeuronAblationProfileV1;
pub use qualification::NeuronResourceSampleV1;
pub use qualification::NeuronResourceSummaryV1;
pub use qualification::QualificationError;
pub use qualification::ablate_eligibility_history;
pub use qualification::ablate_parameter_groups;
pub use qualification::ablate_sparse_config;
pub use qualification::requires_external_replay_ablation;
pub use qualification::summarize_resource_samples;
pub use runtime::NeuronAdmissionError;
pub use runtime::NeuronAdmissionGuard;
pub use runtime::NeuronRuntime;
pub use runtime_types::AnchorWitnessStore;
pub use runtime_types::LocalModelRuntimeReceiptV1;
pub use runtime_types::NeuronCalibrationProfileV1;
pub use runtime_types::NeuronModelError;
pub use runtime_types::NeuronModelOutputV1;
pub use runtime_types::NeuronModelPort;
pub use runtime_types::NeuronModelRequestV1;
pub use runtime_types::NeuronResourceEnvelopeV1;
pub use runtime_types::NeuronResourceReceiptV1;
pub use runtime_types::NeuronRuntimeConfigV1;
pub use runtime_types::NeuronRuntimeError;
pub use runtime_types::NeuronRuntimeOutputV1;
pub use runtime_types::NeuronSignalReceiptV1;
pub use runtime_types::NeuronTickInputV1;
pub use runtime_types::NeuronTickReceiptV1;
pub use runtime_types::WitnessStoreError;
pub use runtime_types::canonical_feature_vector_digest_v1;
pub use runtime_types::canonical_model_output_digest_v1;
pub use semantic_v2::AbstainReasonV1;
pub use semantic_v2::CalibrationExpiryPolicyV1;
pub use semantic_v2::CalibrationWindowDecisionV1;
pub use semantic_v2::DegradationReasonV1;
pub use semantic_v2::ModelExecutionObservationV1;
pub use semantic_v2::ModelSemanticIdentityV2;
pub use semantic_v2::NeuronBodyBundleIdentityV1;
pub use semantic_v2::NeuronCommitDispositionV1;
pub use semantic_v2::NeuronOperationKeyV2;
pub use semantic_v2::NeuronSemanticV2Error;
pub use sparse::InhibitoryEdge;
pub use sparse::SparseCheckpoint;
pub use sparse::SparseConfig;
pub use sparse::SparseError;
pub use sparse::SparseSignalReceipt;
pub use sparse::SparseTick;
pub use sparse::sparse_tick;
pub use store_manifest::NEURON_JOURNAL_ROOT_FORMAT_V1;
pub use store_manifest::NEURON_JOURNAL_SUCCESSOR_FORMAT_V1;
pub use store_manifest::NEURON_OPERATION_FORMAT_V1;
pub use store_manifest::NEURON_STORE_MANIFEST_SCHEMA_V1;
pub use store_manifest::NEURON_WITNESS_ROOT_FORMAT_V1;
pub use store_manifest::NEURON_WITNESS_SUCCESSOR_FORMAT_V1;
pub use store_manifest::NeuronStoreBootstrapV1;
pub use store_manifest::NeuronStoreManifestError;
pub use store_manifest::NeuronStoreManifestV1;
pub use store_manifest::NeuronStoreMigrationV1;
pub use store_manifest::NeuronStoreReplayPlanV1;
pub use store_manifest::NeuronStoreSegmentKindV1;
pub use store_manifest::NeuronStoreSegmentV1;
pub use store_manifest::read_neuron_store_manifest_v1;
pub use store_manifest::write_neuron_store_manifest_v1;
pub use witness::FileAnchorWitnessStore;

const MAX_FEATURES: usize = 4_096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronState {
    pub model_digest: Digest32,
    pub generation: Generation,
    pub values: Vec<FixedQ32>,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepRequest {
    pub run_id: StableId,
    pub model_digest: Digest32,
    pub source_digest: Digest32,
    pub generation: Generation,
    pub decay: FixedQ32,
    pub features: Vec<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSignalReceipt {
    pub run_id: StableId,
    pub model_digest: Digest32,
    pub source_digest: Digest32,
    pub state_digest: Digest32,
    pub signal_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyFeatures,
    FeatureLimitExceeded,
    EmptyDigest(&'static str),
    InvalidDecay,
    ModelDrift,
    WidthDrift,
    GenerationNotAdvanced,
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn step(
    request: StepRequest,
    previous: Option<&NeuronState>,
) -> Result<(NeuronState, NeuronSignalReceipt), Error> {
    validate_request(&request, previous)?;

    let complement = FixedQ32::ONE
        .checked_sub(request.decay)
        .map_err(|_| Error::Arithmetic)?;
    let mut values = Vec::with_capacity(request.features.len());
    for (index, feature) in request.features.iter().copied().enumerate() {
        let prior = previous.map_or(FixedQ32::ZERO, |state| state.values[index]);
        let retained = prior
            .checked_mul(request.decay)
            .map_err(|_| Error::Arithmetic)?;
        let injected = feature
            .checked_mul(complement)
            .map_err(|_| Error::Arithmetic)?;
        values.push(
            retained
                .checked_add(injected)
                .map_err(|_| Error::Arithmetic)?,
        );
    }

    let previous_digest = previous.map_or(Digest32::ZERO, |state| state.state_digest);
    let state_digest = digest_state(&request, previous_digest, &values);
    let signal_digest = digest_signal(&request, state_digest, &values);
    let state = NeuronState {
        model_digest: request.model_digest,
        generation: request.generation,
        values,
        state_digest,
    };
    let receipt = NeuronSignalReceipt {
        run_id: request.run_id,
        model_digest: request.model_digest,
        source_digest: request.source_digest,
        state_digest,
        signal_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((state, receipt))
}

fn validate_request(request: &StepRequest, previous: Option<&NeuronState>) -> Result<(), Error> {
    if request.features.is_empty() {
        return Err(Error::EmptyFeatures);
    }
    if request.features.len() > MAX_FEATURES {
        return Err(Error::FeatureLimitExceeded);
    }
    if request.model_digest.is_zero() {
        return Err(Error::EmptyDigest("model"));
    }
    if request.source_digest.is_zero() {
        return Err(Error::EmptyDigest("source"));
    }
    if request.decay < FixedQ32::ZERO || request.decay > FixedQ32::ONE {
        return Err(Error::InvalidDecay);
    }
    if let Some(state) = previous {
        if state.model_digest != request.model_digest {
            return Err(Error::ModelDrift);
        }
        if state.values.len() != request.features.len() {
            return Err(Error::WidthDrift);
        }
        if request.generation <= state.generation {
            return Err(Error::GenerationNotAdvanced);
        }
        if state.state_digest.is_zero() {
            return Err(Error::EmptyDigest("previous state"));
        }
    }
    Ok(())
}

fn digest_state(request: &StepRequest, previous_digest: Digest32, values: &[FixedQ32]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.state.v1");
    push_id(&mut bytes, &request.run_id);
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(request.source_digest.as_array());
    bytes.extend_from_slice(&request.generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.decay.raw().to_be_bytes());
    bytes.extend_from_slice(previous_digest.as_array());
    for value in values {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_signal(request: &StepRequest, state_digest: Digest32, values: &[FixedQ32]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.neuron.signal.v1");
    push_id(&mut bytes, &request.run_id);
    bytes.extend_from_slice(state_digest.as_array());
    for value in values {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
