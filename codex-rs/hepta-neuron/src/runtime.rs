//! Canonical-to-native temporal signal runtime binding.
//!
//! The adapter keeps the sparse mechanism pure while binding a real model
//! execution receipt, calibrated slow-path semantics, and measured resource
//! observations to the canonical V1 receipts.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::InhibitoryEdge;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickInputV1;
use crate::NeuronTickReceiptV1;
use crate::ProtocolError;
use crate::Q24_ONE;
use crate::Q24_STATE_LIMIT;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseError;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::sparse_tick;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SparseNativeProfileV1 {
    pub normalization_digest: Digest32,
    pub body_digest: Digest32,
    pub body_generation: u64,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<InhibitoryEdge>,
    pub target_activity_q24: i64,
    pub selected_top_k: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenModelRequestV1 {
    pub runtime_config_digest: Digest32,
    pub tick_input_digest: Digest32,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenModelExecutionV1 {
    pub runtime_receipt: LocalModelRuntimeReceiptV1,
    pub head_digest: Digest32,
    pub request_digest: Digest32,
    pub output_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
}

pub trait FrozenNeuronModel {
    type Error: StdError;

    fn execute(
        &mut self,
        request: &FrozenModelRequestV1,
    ) -> Result<FrozenModelExecutionV1, Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCalibrationArtifactV1 {
    pub artifact_digest: Digest32,
    pub runtime_config_digest: Digest32,
    pub model_runtime_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub maximum_in_domain_error_q24: i64,
    pub confidence_floor_ppm: u32,
    pub maximum_ood_ppm: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CalibratedSignalV1 {
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PendingNeuronTickV1 {
    pub checkpoint: SparseCheckpoint,
    pub sparse_receipt: SparseSignalReceipt,
    pub model_runtime_receipt: LocalModelRuntimeReceiptV1,
    pub activation_digest: Digest32,
    pub active_indices: Vec<u32>,
    pub threshold_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub calibration: CalibratedSignalV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeFallbackDispositionV1 {
    TemporalSignal,
    StatelessSelectedHead,
    DeterministicCalibratedRule,
    SlowPathAbstain,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeHealthReasonV1 {
    Healthy,
    DeadActivation,
    ExcessiveProjection,
    CalibrationAbstain,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeHealthV1 {
    pub disposition: RuntimeFallbackDispositionV1,
    pub reason: RuntimeHealthReasonV1,
    pub health_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTickOutputV1 {
    pub checkpoint: SparseCheckpoint,
    pub tick_receipt: NeuronTickReceiptV1,
    pub signal_receipt: NeuronSignalReceiptV1,
    pub model_runtime_receipt: LocalModelRuntimeReceiptV1,
    pub health: RuntimeHealthV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeError {
    Protocol(ProtocolError),
    NativeProfile(&'static str),
    Model(String),
    ModelRequestMismatch,
    ModelOutputDigest,
    ModelRuntimeBinding,
    ModelVector,
    CheckpointMismatch,
    CalibrationArtifact,
    CalibrationWindow,
    ResourceCeiling(&'static str),
    Sparse(SparseError),
    Arithmetic,
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeError {}

impl From<ProtocolError> for RuntimeError {
    fn from(value: ProtocolError) -> Self {
        Self::Protocol(value)
    }
}

impl From<SparseError> for RuntimeError {
    fn from(value: SparseError) -> Self {
        Self::Sparse(value)
    }
}

pub fn composite_model_digest(config: &NeuronRuntimeConfigV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.encoder-head.v1".to_vec();
    bytes.extend_from_slice(config.encoder_digest.as_array());
    bytes.extend_from_slice(config.head_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub fn inhibition_digest(edges: &[InhibitoryEdge]) -> Result<Digest32, RuntimeError> {
    let mut edges = edges.to_vec();
    edges.sort();
    let mut bytes = b"hepta.neuron.inhibition.v1".to_vec();
    let length = u32::try_from(edges.len()).map_err(|_| RuntimeError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for edge in edges {
        bytes.extend_from_slice(
            &u32::try_from(edge.source)
                .map_err(|_| RuntimeError::Arithmetic)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(
            &u32::try_from(edge.target)
                .map_err(|_| RuntimeError::Arithmetic)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn compile_sparse_config(
    config: &NeuronRuntimeConfigV1,
    profile: &SparseNativeProfileV1,
) -> Result<SparseConfig, RuntimeError> {
    config.validate()?;
    if config.state_dimensions.temporal_state != config.state_dimensions.activation
        || config.eligibility_profile.trace_dimension != config.state_dimensions.activation
        || config.top_k_policy.per_population_first
    {
        return Err(RuntimeError::NativeProfile(
            "current native profile is single-population with shared temporal/activation width",
        ));
    }
    if config.state_dimensions.inhibition_edges
        != u32::try_from(profile.inhibition.len()).map_err(|_| RuntimeError::Arithmetic)?
        || config.inhibition_digest != inhibition_digest(&profile.inhibition)?
    {
        return Err(RuntimeError::NativeProfile("inhibition binding"));
    }
    if profile.normalization_digest.is_zero()
        || profile.body_digest.is_zero()
        || profile.body_generation == 0
        || !(0..=Q24_ONE).contains(&profile.temporal_decay_q24)
        || !(0..=Q24_ONE).contains(&profile.inhibition_gain_q24)
        || !(0..=Q24_ONE).contains(&profile.target_activity_q24)
    {
        return Err(RuntimeError::NativeProfile("profile bounds"));
    }
    let width = usize::try_from(config.state_dimensions.activation)
        .map_err(|_| RuntimeError::Arithmetic)?;
    if profile.selected_top_k == 0 || profile.selected_top_k > width {
        return Err(RuntimeError::NativeProfile("top-k"));
    }
    let selected_ppm = u32::try_from(
        profile
            .selected_top_k
            .checked_mul(1_000_000)
            .ok_or(RuntimeError::Arithmetic)?
            / width,
    )
    .map_err(|_| RuntimeError::Arithmetic)?;
    if selected_ppm < config.top_k_policy.minimum_ratio_ppm
        || selected_ppm > config.top_k_policy.maximum_ratio_ppm
    {
        return Err(RuntimeError::NativeProfile("top-k policy"));
    }
    let sparse = SparseConfig {
        model_digest: composite_model_digest(config),
        normalization_digest: profile.normalization_digest,
        generation: config.generation,
        width,
        top_k: profile.selected_top_k,
        temporal_decay_q24: profile.temporal_decay_q24,
        inhibition_gain_q24: profile.inhibition_gain_q24,
        inhibition: profile.inhibition.clone(),
        activity_decay_q24: config.homeostasis_profile.moving_average_alpha_q24,
        target_activity_q24: profile.target_activity_q24,
        threshold_rate_q24: config.homeostasis_profile.threshold_step_q24,
        threshold_min_q24: config.homeostasis_profile.threshold_minimum_q24,
        threshold_max_q24: config.homeostasis_profile.threshold_maximum_q24,
        eligibility_decay_q24: config.eligibility_profile.decay_q24,
    };
    sparse.digest()?;
    Ok(sparse)
}

pub fn prepare_tick<M: FrozenNeuronModel>(
    config: &NeuronRuntimeConfigV1,
    profile: &SparseNativeProfileV1,
    model: &mut M,
    input: &NeuronTickInputV1,
    previous: Option<&SparseCheckpoint>,
    calibration: &NeuronCalibrationArtifactV1,
) -> Result<PendingNeuronTickV1, RuntimeError> {
    config.validate()?;
    input.validate()?;
    let config_digest = config.semantic_digest()?;
    let tick_digest = input.semantic_digest()?;
    let expected_before = previous.map_or(Digest32::ZERO, SparseCheckpoint::digest);
    if expected_before != input.checkpoint_digest {
        return Err(RuntimeError::CheckpointMismatch);
    }
    if input
        .body_generation
        .is_some_and(|generation| generation != profile.body_generation)
    {
        return Err(RuntimeError::NativeProfile("body generation"));
    }
    let sparse_config = compile_sparse_config(config, profile)?;
    let model_request = FrozenModelRequestV1 {
        runtime_config_digest: config_digest,
        tick_input_digest: tick_digest,
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        feature_vector_q24: input.feature_vector_q24.clone(),
    };
    let execution = model
        .execute(&model_request)
        .map_err(|error| RuntimeError::Model(error.to_string()))?;
    validate_model_execution(config, &model_request, &execution, sparse_config.width)?;
    let sparse_input = SparseTick {
        scope_digest: subject_scope_digest(input),
        objective_digest: input.objective_digest,
        ndu_digest: input.ndu_snapshot_digest,
        body_digest: profile.body_digest,
        input_digest: input.input_feature_digest,
        sequence: input.logical_sequence,
        monotonic_micros: input.monotonic_time_micros,
        drive_q24: execution.drive_q24,
        prediction_q24: execution.prediction_q24,
    };
    let (checkpoint, sparse_receipt) = sparse_tick(&sparse_config, &sparse_input, previous)?;
    let activation_digest = digest_q24(b"hepta.neuron.activation.v1", checkpoint.activation_q24())?;
    let threshold_digest = digest_q24(b"hepta.neuron.threshold.v1", checkpoint.thresholds_q24())?;
    let eligibility_digest =
        digest_q24(b"hepta.neuron.eligibility.v1", checkpoint.eligibility_q24())?;
    let active_indices = checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter_map(|(index, value)| {
            (*value > 0).then(|| u32::try_from(index).map_err(|_| RuntimeError::Arithmetic))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let calibrated = calibrate(
        config,
        input,
        execution.runtime_receipt.receipt_digest,
        sparse_receipt.prediction_error_q24,
        calibration,
    )?;
    Ok(PendingNeuronTickV1 {
        checkpoint,
        sparse_receipt,
        model_runtime_receipt: execution.runtime_receipt,
        activation_digest,
        active_indices,
        threshold_digest,
        eligibility_digest,
        calibration: calibrated,
    })
}

pub fn finalize_tick(
    config: &NeuronRuntimeConfigV1,
    input: &NeuronTickInputV1,
    pending: PendingNeuronTickV1,
    resources: NeuronResourceReceiptV1,
) -> Result<RuntimeTickOutputV1, RuntimeError> {
    if resources.saturation_count != pending.sparse_receipt.projection_count {
        return Err(RuntimeError::ResourceCeiling("saturation count binding"));
    }
    validate_resources(config, &resources)?;
    let mut tick_receipt = NeuronTickReceiptV1 {
        tick_id: input.tick_id.clone(),
        checkpoint_before: pending.sparse_receipt.checkpoint_before,
        checkpoint_after: pending.sparse_receipt.checkpoint_after,
        activation_digest: pending.activation_digest,
        active_indices: pending.active_indices,
        sparsity_ppm: pending.sparse_receipt.active_fraction_ppm,
        threshold_digest: pending.threshold_digest,
        eligibility_digest: pending.eligibility_digest,
        prediction_error_q24: pending.sparse_receipt.prediction_error_q24,
        confidence_ppm: pending.calibration.confidence_ppm,
        ood_ppm: pending.calibration.ood_ppm,
        abstain: pending.calibration.abstain,
        resource_receipt: resources,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    tick_receipt.receipt_digest = tick_receipt.calculate_digest()?;
    tick_receipt.validate()?;

    let mut signal_receipt = NeuronSignalReceiptV1 {
        signal_set_id: input.tick_id.clone(),
        model_runtime_digest: pending.model_runtime_receipt.receipt_digest,
        temporal_state_digest: pending.checkpoint.digest(),
        signals_q24: pending.checkpoint.activation_q24().to_vec(),
        activation_sparsity_ppm: tick_receipt.sparsity_ppm,
        ood_ppm: tick_receipt.ood_ppm,
        abstain: tick_receipt.abstain,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    signal_receipt.receipt_digest = signal_receipt.calculate_digest()?;
    signal_receipt.validate()?;
    let health = assess_runtime_health(
        config,
        &pending.sparse_receipt,
        &tick_receipt.active_indices,
        pending.calibration,
    );

    Ok(RuntimeTickOutputV1 {
        checkpoint: pending.checkpoint,
        tick_receipt,
        signal_receipt,
        model_runtime_receipt: pending.model_runtime_receipt,
        health,
    })
}

fn validate_model_execution(
    config: &NeuronRuntimeConfigV1,
    request: &FrozenModelRequestV1,
    execution: &FrozenModelExecutionV1,
    width: usize,
) -> Result<(), RuntimeError> {
    execution.runtime_receipt.validate()?;
    if execution.request_digest != model_request_digest(request)? {
        return Err(RuntimeError::ModelRequestMismatch);
    }
    if execution.output_digest.is_zero() {
        return Err(RuntimeError::ModelOutputDigest);
    }
    if execution.runtime_receipt.weights_digest != config.encoder_digest
        || execution.head_digest != config.head_digest
    {
        return Err(RuntimeError::ModelRuntimeBinding);
    }
    if execution.drive_q24.len() != width
        || execution.prediction_q24.len() != width
        || execution
            .drive_q24
            .iter()
            .chain(&execution.prediction_q24)
            .any(|value| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(value))
    {
        return Err(RuntimeError::ModelVector);
    }
    let mut bytes = b"hepta.neuron.frozen-model-output.v1".to_vec();
    bytes.extend_from_slice(execution.request_digest.as_array());
    bytes.extend_from_slice(execution.runtime_receipt.receipt_digest.as_array());
    bytes.extend_from_slice(execution.head_digest.as_array());
    append_q24(&mut bytes, &execution.drive_q24)?;
    append_q24(&mut bytes, &execution.prediction_q24)?;
    if Digest32::of_bytes(&bytes) != execution.output_digest {
        return Err(RuntimeError::ModelOutputDigest);
    }
    Ok(())
}

pub fn model_request_digest(request: &FrozenModelRequestV1) -> Result<Digest32, RuntimeError> {
    let mut bytes = b"hepta.neuron.frozen-model-request.v1".to_vec();
    for digest in [
        request.runtime_config_digest,
        request.tick_input_digest,
        request.encoder_digest,
        request.head_digest,
    ] {
        if digest.is_zero() {
            return Err(RuntimeError::ModelRequestMismatch);
        }
        bytes.extend_from_slice(digest.as_array());
    }
    append_q24(&mut bytes, &request.feature_vector_q24)?;
    Ok(Digest32::of_bytes(&bytes))
}

pub fn frozen_model_output_digest(
    request_digest: Digest32,
    runtime_receipt_digest: Digest32,
    head_digest: Digest32,
    drive_q24: &[i64],
    prediction_q24: &[i64],
) -> Result<Digest32, RuntimeError> {
    if request_digest.is_zero() || runtime_receipt_digest.is_zero() || head_digest.is_zero() {
        return Err(RuntimeError::ModelOutputDigest);
    }
    let mut bytes = b"hepta.neuron.frozen-model-output.v1".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(runtime_receipt_digest.as_array());
    bytes.extend_from_slice(head_digest.as_array());
    append_q24(&mut bytes, drive_q24)?;
    append_q24(&mut bytes, prediction_q24)?;
    Ok(Digest32::of_bytes(&bytes))
}

pub fn assess_runtime_health(
    config: &NeuronRuntimeConfigV1,
    sparse_receipt: &SparseSignalReceipt,
    active_indices: &[u32],
    calibration: CalibratedSignalV1,
) -> RuntimeHealthV1 {
    let (disposition, reason) = if calibration.abstain {
        (
            RuntimeFallbackDispositionV1::SlowPathAbstain,
            RuntimeHealthReasonV1::CalibrationAbstain,
        )
    } else if active_indices.is_empty() {
        (
            RuntimeFallbackDispositionV1::StatelessSelectedHead,
            RuntimeHealthReasonV1::DeadActivation,
        )
    } else if sparse_receipt.projection_count > config.homeostasis_profile.saturation_limit {
        (
            RuntimeFallbackDispositionV1::DeterministicCalibratedRule,
            RuntimeHealthReasonV1::ExcessiveProjection,
        )
    } else {
        (
            RuntimeFallbackDispositionV1::TemporalSignal,
            RuntimeHealthReasonV1::Healthy,
        )
    };
    let mut bytes = b"hepta.neuron.runtime-health.v1".to_vec();
    bytes.extend_from_slice(sparse_receipt.checkpoint_after.as_array());
    bytes.extend_from_slice(&sparse_receipt.projection_count.to_be_bytes());
    bytes.extend_from_slice(&calibration.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&calibration.ood_ppm.to_be_bytes());
    bytes.push(u8::from(calibration.abstain));
    bytes.push(match disposition {
        RuntimeFallbackDispositionV1::TemporalSignal => 0,
        RuntimeFallbackDispositionV1::StatelessSelectedHead => 1,
        RuntimeFallbackDispositionV1::DeterministicCalibratedRule => 2,
        RuntimeFallbackDispositionV1::SlowPathAbstain => 3,
    });
    RuntimeHealthV1 {
        disposition,
        reason,
        health_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn calibrate(
    config: &NeuronRuntimeConfigV1,
    input: &NeuronTickInputV1,
    model_runtime_digest: Digest32,
    prediction_error_q24: i64,
    artifact: &NeuronCalibrationArtifactV1,
) -> Result<CalibratedSignalV1, RuntimeError> {
    if artifact.artifact_digest.is_zero()
        || artifact.runtime_config_digest != config.semantic_digest()?
        || artifact.model_runtime_digest != model_runtime_digest
        || artifact.generation != config.generation.get()
        || artifact.maximum_in_domain_error_q24 <= 0
        || artifact.confidence_floor_ppm > 1_000_000
        || artifact.maximum_ood_ppm > 1_000_000
    {
        return Err(RuntimeError::CalibrationArtifact);
    }
    if input.logical_sequence < artifact.valid_from_sequence
        || input.logical_sequence > artifact.expires_after_sequence
        || artifact.valid_from_sequence == 0
        || artifact.valid_from_sequence > artifact.expires_after_sequence
    {
        return Err(RuntimeError::CalibrationWindow);
    }
    let error = prediction_error_q24.max(0);
    let scaled = i128::from(error)
        .checked_mul(1_000_000)
        .ok_or(RuntimeError::Arithmetic)?;
    let denominator = i128::from(artifact.maximum_in_domain_error_q24);
    let raw_ood = if error > artifact.maximum_in_domain_error_q24 {
        1_000_000
    } else {
        u32::try_from(scaled / denominator).map_err(|_| RuntimeError::Arithmetic)?
    };
    let ood_ppm = raw_ood.min(1_000_000);
    let confidence_ppm = 1_000_000_u32.saturating_sub(ood_ppm);
    let abstain = error > artifact.maximum_in_domain_error_q24
        || ood_ppm > artifact.maximum_ood_ppm
        || confidence_ppm < artifact.confidence_floor_ppm;
    Ok(CalibratedSignalV1 {
        confidence_ppm,
        ood_ppm,
        abstain,
    })
}

fn validate_resources(
    config: &NeuronRuntimeConfigV1,
    observed: &NeuronResourceReceiptV1,
) -> Result<(), RuntimeError> {
    let envelope = &config.resource_envelope;
    if observed.execution_micros > envelope.p99_latency_micros {
        return Err(RuntimeError::ResourceCeiling("execution latency"));
    }
    if observed.transient_allocation_bytes > envelope.transient_allocation_bytes {
        return Err(RuntimeError::ResourceCeiling("transient allocation"));
    }
    if observed.checkpoint_bytes > envelope.checkpoint_bytes {
        return Err(RuntimeError::ResourceCeiling("checkpoint bytes"));
    }
    if observed.saturation_count > config.homeostasis_profile.saturation_limit {
        return Err(RuntimeError::ResourceCeiling("saturation count"));
    }
    Ok(())
}

fn subject_scope_digest(input: &NeuronTickInputV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.subject-scope.v1".to_vec();
    bytes.extend_from_slice(input.subject_id.as_str().as_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_q24(domain: &[u8], values: &[i64]) -> Result<Digest32, RuntimeError> {
    let mut bytes = domain.to_vec();
    append_q24(&mut bytes, values)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn append_q24(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), RuntimeError> {
    let length = u32::try_from(values.len()).map_err(|_| RuntimeError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
