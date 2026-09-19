//! Canonical neuron runtime binding over the deterministic sparse kernel.
//!
//! This layer binds real model execution evidence, calibrated/OOD state and an
//! independently retained checkpoint witness to the existing Q24 journal. It
//! still grants no effect, selection, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::io;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::JournalAnchor;
use crate::JournalError;
use crate::SparseConfig;
use crate::SparseSignalReceipt;

const Q24: i64 = 1 << 24;
const H_Q24: i64 = 8 * Q24;
const MAX_PREDICTION_ERROR_Q24: i64 = 16 * Q24;
const PPM: u64 = 1_000_000;
const MAX_INPUT_FEATURES: usize = 512;
const MAX_MODULATORS: usize = 8;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalModelRuntimeReceiptV1 {
    pub model_id: StableId,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_id: StableId,
    pub backend_id: StableId,
    pub device_identity_digest: Digest32,
    pub latency_micros: u64,
    pub resident_bytes: u64,
}

impl LocalModelRuntimeReceiptV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronRuntimeError> {
        for (field, digest) in [
            ("weights", self.weights_digest),
            ("tokenizer", self.tokenizer_digest),
            ("preprocessor", self.preprocessor_digest),
            ("device", self.device_identity_digest),
        ] {
            if digest.is_zero() {
                return Err(NeuronRuntimeError::EmptyDigest(field));
            }
        }
        let mut bytes = b"hepta.neuron.local-model-runtime-receipt.v1".to_vec();
        push_id(&mut bytes, &self.model_id)?;
        for digest in [
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.quantization_id)?;
        push_id(&mut bytes, &self.backend_id)?;
        bytes.extend_from_slice(self.device_identity_digest.as_array());
        bytes.extend_from_slice(&self.latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resident_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCalibrationProfileV1 {
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub generation: Generation,
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

impl NeuronCalibrationProfileV1 {
    fn validate(&self, generation: Generation) -> Result<(), NeuronRuntimeError> {
        if self.calibration_artifact_digest.is_zero() {
            return Err(NeuronRuntimeError::EmptyDigest("calibration artifact"));
        }
        if self.ood_artifact_digest.is_zero() {
            return Err(NeuronRuntimeError::EmptyDigest("ood artifact"));
        }
        if self.generation != generation
            || self.valid_from_sequence == 0
            || self.valid_from_sequence > self.expires_after_sequence
            || !(1..=MAX_PREDICTION_ERROR_Q24).contains(&self.zero_confidence_error_q24)
            || !(1..=MAX_PREDICTION_ERROR_Q24).contains(&self.maximum_in_domain_error_q24)
            || self.minimum_confidence_ppm > PPM as u32
            || self.maximum_ood_ppm > PPM as u32
            || self.minimum_active_ppm > self.maximum_active_ppm
            || self.maximum_active_ppm > PPM as u32
            || self.maximum_ece_ppm > PPM as u32
            || self.maximum_false_acceptance_ppm > PPM as u32
            || self.measured_ece_ppm > self.maximum_ece_ppm
            || self.measured_false_acceptance_ppm > self.maximum_false_acceptance_ppm
        {
            return Err(NeuronRuntimeError::InvalidCalibration);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceEnvelopeV1 {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeConfigV1 {
    pub config_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub normalization_digest: Digest32,
    pub native_config_digest: Digest32,
    pub input_feature_dimension: usize,
    pub state_width: usize,
    pub modulator_dimension: usize,
    pub calibration: NeuronCalibrationProfileV1,
    pub resource_envelope: NeuronResourceEnvelopeV1,
}

impl NeuronRuntimeConfigV1 {
    pub(crate) fn validate_native(&self, native: &SparseConfig) -> Result<(), NeuronRuntimeError> {
        for (field, digest) in [
            ("encoder", self.encoder_digest),
            ("head", self.head_digest),
            ("weights", self.weights_digest),
            ("normalization", self.normalization_digest),
            ("native config", self.native_config_digest),
        ] {
            if digest.is_zero() {
                return Err(NeuronRuntimeError::EmptyDigest(field));
            }
        }
        if self.generation != native.generation
            || self.head_digest != native.model_digest
            || self.normalization_digest != native.normalization_digest
            || self.native_config_digest != native.digest().map_err(JournalError::Mechanism)?
            || self.state_width != native.width
            || !(1..=MAX_INPUT_FEATURES).contains(&self.input_feature_dimension)
            || !(1..=MAX_MODULATORS).contains(&self.modulator_dimension)
            || self.resource_envelope.p95_latency_micros == 0
            || self.resource_envelope.p99_latency_micros < self.resource_envelope.p95_latency_micros
            || self.resource_envelope.transient_allocation_bytes == 0
            || self.resource_envelope.checkpoint_bytes == 0
            || !(1_000_000..=4_000_000)
                .contains(&self.resource_envelope.write_amplification_ppm)
        {
            return Err(NeuronRuntimeError::InvalidConfig);
        }
        self.calibration.validate(self.generation)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTickInputV1 {
    pub tick_id: StableId,
    pub subject_id: StableId,
    pub logical_sequence: u64,
    pub monotonic_time_micros: u64,
    pub checkpoint_digest: Digest32,
    pub input_feature_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub body_generation: Option<u64>,
    pub modulator_digest: Option<Digest32>,
}

impl NeuronTickInputV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronRuntimeError> {
        validate_tick_input(self)?;
        let mut bytes = b"hepta.neuron.tick-input.v1".to_vec();
        push_id(&mut bytes, &self.tick_id)?;
        push_id(&mut bytes, &self.subject_id)?;
        bytes.extend_from_slice(&self.logical_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.monotonic_time_micros.to_be_bytes());
        for digest in [
            self.checkpoint_digest,
            self.input_feature_digest,
            self.objective_digest,
            self.ndu_snapshot_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        match self.body_generation {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
            None => bytes.push(0),
        }
        match self.modulator_digest {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(value.as_array());
            }
            None => bytes.push(0),
        }
        for value in &self.feature_vector_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronModelRequestV1 {
    pub config_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub input_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
    pub expected_output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronModelOutputV1 {
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub output_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub queue_age_micros: u64,
    pub transient_allocation_bytes: u64,
    pub runtime_receipt: LocalModelRuntimeReceiptV1,
}

/// Execute the exact frozen encoder/head tuple selected by the runtime config.
/// Implementations must authenticate the underlying model invocation and return
/// measurements from that invocation; a digest-only stub is not a product port.
pub trait NeuronModelPort {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronModelError {
    Unavailable,
    Rejected,
    Indeterminate,
}

impl fmt::Display for NeuronModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronModelError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum WitnessStoreError {
    Unavailable,
    Conflict,
    Busy,
    InvalidLimit,
    InvalidAnchor,
    NotRegular,
    Corrupt,
    ContextMismatch,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for WitnessStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WitnessStoreError {}

impl From<io::Error> for WitnessStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

/// Durable witness storage is independent from the journal. Implementations
/// must authenticate scope/generation and make compare-and-swap durable before
/// returning success.
pub trait AnchorWitnessStore {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError>;

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceReceiptV1 {
    pub execution_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub saturation_count: u32,
    pub queue_age_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTickReceiptV1 {
    pub tick_id: StableId,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_digest: Digest32,
    pub active_indices: Vec<u32>,
    pub sparsity_ppm: u32,
    pub threshold_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub prediction_error_q24: i64,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub resource_receipt: NeuronResourceReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSignalReceiptV1 {
    pub signal_set_id: StableId,
    pub model_runtime_digest: Digest32,
    pub temporal_state_digest: Digest32,
    pub signals_q24: Vec<i64>,
    pub activation_sparsity_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeOutputV1 {
    pub tick: NeuronTickReceiptV1,
    pub signal: NeuronSignalReceiptV1,
    pub model_runtime: LocalModelRuntimeReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronRuntimeError {
    EmptyDigest(&'static str),
    InvalidConfig,
    InvalidCalibration,
    InvalidInput,
    FeatureDigestMismatch,
    CheckpointMismatch,
    ModelBindingMismatch,
    ModelOutputMismatch,
    CalibrationExpired,
    BootstrapRequiresEmptyJournal,
    BootstrapWitnessPresent,
    RecoveryWitnessMismatch,
    PendingReconciliation,
    Model(NeuronModelError),
    Journal(JournalError),
    Witness(WitnessStoreError),
    WitnessAfterCommit {
        anchor: JournalAnchor,
        error: WitnessStoreError,
    },
    Arithmetic,
}

impl fmt::Display for NeuronRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronRuntimeError {}

impl From<JournalError> for NeuronRuntimeError {
    fn from(error: JournalError) -> Self {
        Self::Journal(error)
    }
}

impl From<NeuronModelError> for NeuronRuntimeError {
    fn from(error: NeuronModelError) -> Self {
        Self::Model(error)
    }
}

impl From<WitnessStoreError> for NeuronRuntimeError {
    fn from(error: WitnessStoreError) -> Self {
        Self::Witness(error)
    }
}

pub fn canonical_feature_vector_digest_v1(values: &[i64]) -> Digest32 {
    digest_q24_vector(b"hepta.neuron.input-features.q24.v1", values)
}

pub fn canonical_model_output_digest_v1(
    drive_q24: &[i64],
    prediction_q24: &[i64],
    runtime_receipt: &LocalModelRuntimeReceiptV1,
) -> Result<Digest32, NeuronRuntimeError> {
    let mut bytes = b"hepta.neuron.model-output.q24.v1".to_vec();
    bytes.extend_from_slice(runtime_receipt.semantic_digest()?.as_array());
    for values in [drive_q24, prediction_q24] {
        bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub(crate) fn validate_tick_input(input: &NeuronTickInputV1) -> Result<(), NeuronRuntimeError> {
    if input.logical_sequence == 0
        || input.monotonic_time_micros == 0
        || input.feature_vector_q24.is_empty()
        || input.feature_vector_q24.len() > MAX_INPUT_FEATURES
        || input
            .feature_vector_q24
            .iter()
            .any(|value| !(-H_Q24..=H_Q24).contains(value))
        || input.objective_digest.is_zero()
        || input.ndu_snapshot_digest.is_zero()
        || input.modulator_digest.is_some_and(Digest32::is_zero)
    {
        return Err(NeuronRuntimeError::InvalidInput);
    }
    if input.logical_sequence == 1 {
        if !input.checkpoint_digest.is_zero() {
            return Err(NeuronRuntimeError::InvalidInput);
        }
    } else if input.checkpoint_digest.is_zero() {
        return Err(NeuronRuntimeError::InvalidInput);
    }
    if canonical_feature_vector_digest_v1(&input.feature_vector_q24) != input.input_feature_digest {
        return Err(NeuronRuntimeError::FeatureDigestMismatch);
    }
    Ok(())
}

pub(crate) fn validate_model_output(
    config: &NeuronRuntimeConfigV1,
    output: &NeuronModelOutputV1,
) -> Result<(), NeuronRuntimeError> {
    if output.encoder_digest != config.encoder_digest
        || output.head_digest != config.head_digest
        || output.runtime_receipt.model_id != config.model_id
        || output.runtime_receipt.weights_digest != config.weights_digest
    {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    output.runtime_receipt.semantic_digest()?;
    if output.drive_q24.len() != config.state_width
        || output.prediction_q24.len() != config.state_width
        || output
            .drive_q24
            .iter()
            .chain(&output.prediction_q24)
            .any(|value| !(-H_Q24..=H_Q24).contains(value))
        || output.output_digest
            != canonical_model_output_digest_v1(
                &output.drive_q24,
                &output.prediction_q24,
                &output.runtime_receipt,
            )?
    {
        return Err(NeuronRuntimeError::ModelOutputMismatch);
    }
    Ok(())
}

pub(crate) fn calibrate(
    profile: &NeuronCalibrationProfileV1,
    receipt: &SparseSignalReceipt,
    sequence: u64,
) -> Result<(u32, u32, bool), NeuronRuntimeError> {
    if sequence < profile.valid_from_sequence || sequence > profile.expires_after_sequence {
        return Err(NeuronRuntimeError::CalibrationExpired);
    }
    let error = u64::try_from(receipt.prediction_error_q24)
        .map_err(|_| NeuronRuntimeError::Arithmetic)?;
    let zero_confidence = profile.zero_confidence_error_q24 as u64;
    let in_domain = profile.maximum_in_domain_error_q24 as u64;
    let confidence = PPM
        .saturating_sub(error.saturating_mul(PPM) / zero_confidence)
        .min(PPM);
    let ood = (error.saturating_mul(PPM) / in_domain).min(PPM);
    let confidence_ppm = confidence as u32;
    let ood_ppm = ood as u32;
    let abstain = confidence_ppm < profile.minimum_confidence_ppm
        || ood_ppm > profile.maximum_ood_ppm
        || receipt.active_fraction_ppm < profile.minimum_active_ppm
        || receipt.active_fraction_ppm > profile.maximum_active_ppm
        || receipt.projection_count > profile.maximum_projection_count;
    Ok((confidence_ppm, ood_ppm, abstain))
}

pub(crate) fn subject_scope_digest(subject: &StableId) -> Result<Digest32, NeuronRuntimeError> {
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    push_id(&mut bytes, subject)?;
    Ok(Digest32::of_bytes(&bytes))
}

pub(crate) fn body_digest(config: &NeuronRuntimeConfigV1, input: &NeuronTickInputV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.body-binding.v1".to_vec();
    bytes.extend_from_slice(config.head_digest.as_array());
    bytes.extend_from_slice(&config.generation.get().to_be_bytes());
    bytes.extend_from_slice(&input.body_generation.unwrap_or(0).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(crate) fn digest_model_binding(
    output: &NeuronModelOutputV1,
) -> Result<Digest32, NeuronRuntimeError> {
    let mut bytes = b"hepta.neuron.model-runtime-binding.v1".to_vec();
    bytes.extend_from_slice(output.encoder_digest.as_array());
    bytes.extend_from_slice(output.head_digest.as_array());
    bytes.extend_from_slice(output.output_digest.as_array());
    bytes.extend_from_slice(output.runtime_receipt.semantic_digest()?.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub(crate) fn digest_q24_vector(domain: &[u8], values: &[i64]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), NeuronRuntimeError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| NeuronRuntimeError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}
