//! Experimental Neuron feature projection using the same resource owner.

use std::str::FromStr;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

const MAX_NEURON_FEATURES: usize = 512;
const Q24_STATE_LIMIT: i64 = 8 * (1_i64 << 24);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureRequest {
    pub authorization: WorkerRequest,
    pub encoder_digest: String,
    pub head_digest: String,
    pub weights_digest: String,
    pub input_digest: String,
    pub feature_vector_q24: Vec<i64>,
    pub expected_output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverNeuronFeatureObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub encoder_digest: String,
    pub head_digest: String,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureExecutionObservation {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_generation: u64,
    pub manifest: ModelManifest,
    pub encoder_digest: String,
    pub head_digest: String,
    pub input_digest: String,
    pub status: ExecutionStatus,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub terminal_observed: bool,
}

/// Executes a frozen encoder/head feature request. Implementations must obey
/// admitted memory bounds; observations do not establish real-device evidence.
pub trait NeuronFeatureDriver: ModelDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error>;
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    pub fn run_neuron_features(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request.authorization)?;
        validate_neuron_feature_request(&request)?;
        if self
            .active_requests
            .contains_key(&request.authorization.request_id)
            || self.active_requests.len()
                >= self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS)
        {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.repair_required {
            return Err(Error::CleanupRequired);
        }
        if request.authorization.model_digest != loaded.manifest.model_digest
            || request.authorization.reservation_model_digest != loaded.manifest.model_digest
            || request.weights_digest != loaded.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.authorization.maximum_tokens > loaded.manifest.maximum_tokens
            || request.authorization.maximum_tokens
                > request.authorization.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        let payload_digest = canonical_neuron_feature_payload_digest(&request);
        if request.authorization.payload_digest != payload_digest
            || request.authorization.lease_payload_digest != payload_digest
        {
            return Err(Error::PayloadMismatch);
        }
        if request.authorization.cancelled {
            return Ok(NeuronFeatureExecutionObservation {
                request_id: request.authorization.request_id,
                reservation_id: request.authorization.reservation_id,
                worker_generation: self.generation,
                manifest: loaded.manifest.clone(),
                encoder_digest: request.encoder_digest,
                head_digest: request.head_digest,
                input_digest: request.input_digest,
                status: ExecutionStatus::Cancelled,
                drive_q24: Vec::new(),
                prediction_q24: Vec::new(),
                observed_memory_bytes: loaded.handle.observed_memory_bytes,
                transient_allocation_bytes: 0,
                queue_age_micros: 0,
                latency_micros: 0,
                terminal_observed: true,
            });
        }
        let workspace_bytes = request
            .authorization
            .maximum_kv_bytes
            .checked_add(request.authorization.maximum_transient_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let memory_limit = loaded
            .manifest
            .maximum_resident_bytes
            .checked_add(workspace_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let mut workspace = self.resources.reserve(workspace_bytes)?;
        let active_count = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        workspace.enter()?;
        loaded.active_requests = active_count;
        self.active_requests.insert(
            request.authorization.request_id.clone(),
            model_id.to_string(),
        );
        let observed = self.driver.run_neuron_features(&loaded.handle, &request);
        self.active_requests
            .remove(&request.authorization.request_id);
        loaded.active_requests = loaded
            .active_requests
            .checked_sub(1)
            .ok_or(Error::ResourceAccounting)?;
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                loaded.repair_required = true;
                return Err(error);
            }
        };
        if observed.terminal_observed {
            workspace.release_after_terminal()?;
        } else {
            loaded.repair_required = true;
            drop(workspace);
        }
        if observed.observed_memory_bytes > memory_limit
            || observed.transient_allocation_bytes > request.authorization.maximum_transient_bytes
        {
            self.resources.fence()?;
            return Err(Error::ModelCapacity);
        }
        let status = if !observed.terminal_observed {
            ExecutionStatus::Indeterminate
        } else if observed.succeeded {
            validate_neuron_feature_output(&request, &observed)?;
            ExecutionStatus::Succeeded
        } else {
            ExecutionStatus::Failed
        };
        Ok(NeuronFeatureExecutionObservation {
            request_id: request.authorization.request_id,
            reservation_id: request.authorization.reservation_id,
            worker_generation: self.generation,
            manifest: loaded.manifest.clone(),
            encoder_digest: observed.encoder_digest,
            head_digest: observed.head_digest,
            input_digest: request.input_digest,
            status,
            drive_q24: observed.drive_q24,
            prediction_q24: observed.prediction_q24,
            observed_memory_bytes: observed.observed_memory_bytes,
            transient_allocation_bytes: observed.transient_allocation_bytes,
            queue_age_micros: observed.queue_age_micros,
            latency_micros: observed.latency_micros,
            terminal_observed: observed.terminal_observed,
        })
    }

    /// Project an observation into the inference-control-owned receipt. This
    /// does not confer authority or turn an injected driver into real hardware.
    pub fn run_neuron_features_receipt(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        let request_copy = request.clone();
        let observed = self.run_neuron_features(now_ms, model_id, request)?;
        let generation =
            Generation::new(observed.worker_generation).map_err(|_| Error::FeatureContract)?;
        let control_request = NeuronFeatureRequestV1 {
            request_id: StableId::new(request_copy.authorization.request_id)
                .map_err(|_| Error::FeatureContract)?,
            generation,
            model_id: StableId::new(observed.manifest.model_id.clone())
                .map_err(|_| Error::FeatureContract)?,
            encoder_digest: parse_digest32(&request_copy.encoder_digest)?,
            head_digest: parse_digest32(&request_copy.head_digest)?,
            weights_digest: parse_digest32(&request_copy.weights_digest)?,
            input_digest: parse_digest32(&request_copy.input_digest)?,
            feature_vector_q24: request_copy.feature_vector_q24,
            expected_output_width: request_copy.expected_output_width,
        };
        let runtime_tuple = NeuronModelRuntimeTupleV1 {
            model_id: control_request.model_id.clone(),
            model_manifest_digest: parse_digest32(&observed.manifest.model_digest)?,
            weights_digest: parse_digest32(&observed.manifest.weights_digest)?,
            tokenizer_digest: parse_digest32(&observed.manifest.tokenizer_digest)?,
            preprocessor_digest: parse_digest32(&observed.manifest.preprocessor_digest)?,
            quantization_digest: parse_digest32(&observed.manifest.quantization_digest)?,
            runtime_digest: parse_digest32(&observed.manifest.runtime_digest)?,
            device_digest: parse_digest32(&observed.manifest.device_digest)?,
        };
        let status = match observed.status {
            ExecutionStatus::Succeeded => NeuronFeatureTerminalStatusV1::Succeeded,
            ExecutionStatus::Failed => NeuronFeatureTerminalStatusV1::Failed,
            ExecutionStatus::Cancelled => NeuronFeatureTerminalStatusV1::Cancelled,
            ExecutionStatus::Indeterminate => NeuronFeatureTerminalStatusV1::Indeterminate,
        };
        build_neuron_feature_receipt_v1(
            &control_request,
            runtime_tuple,
            NeuronFeatureObservationV1 {
                encoder_digest: parse_digest32(&observed.encoder_digest)?,
                head_digest: parse_digest32(&observed.head_digest)?,
                drive_q24: observed.drive_q24,
                prediction_q24: observed.prediction_q24,
                observed_memory_bytes: observed.observed_memory_bytes,
                transient_allocation_bytes: observed.transient_allocation_bytes,
                queue_age_micros: observed.queue_age_micros,
                latency_micros: observed.latency_micros,
                status,
            },
        )
        .map_err(|_| Error::FeatureContract)
    }
}

fn parse_digest32(value: &str) -> Result<Digest32, Error> {
    Digest32::from_str(value).map_err(|_| Error::FeatureContract)
}

pub fn canonical_neuron_feature_payload_digest(request: &NeuronFeatureRequest) -> String {
    // v2 explicitly binds the added resource limits; it does not silently
    // reinterpret the old v1 digest scope.
    let mut bytes = b"hepta.infer-worker.neuron-feature-request.v2".to_vec();
    bytes.extend_from_slice(request.authorization.model_digest.as_bytes());
    bytes.extend_from_slice(request.encoder_digest.as_bytes());
    bytes.extend_from_slice(request.head_digest.as_bytes());
    bytes.extend_from_slice(request.weights_digest.as_bytes());
    bytes.extend_from_slice(request.input_digest.as_bytes());
    bytes.extend_from_slice(&(request.feature_vector_q24.len() as u64).to_be_bytes());
    for value in &request.feature_vector_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&(request.expected_output_width as u64).to_be_bytes());
    bytes.extend_from_slice(&request.authorization.maximum_kv_bytes.to_be_bytes());
    bytes.extend_from_slice(&request.authorization.maximum_transient_bytes.to_be_bytes());
    Digest32::of_bytes(&bytes).to_string()
}

fn validate_neuron_feature_request(value: &NeuronFeatureRequest) -> Result<(), Error> {
    validate_digest(&value.encoder_digest, "encoder")?;
    validate_digest(&value.head_digest, "head")?;
    validate_digest(&value.weights_digest, "weights")?;
    validate_digest(&value.input_digest, "neuron input")?;
    if value.feature_vector_q24.is_empty()
        || value.feature_vector_q24.len() > MAX_NEURON_FEATURES
        || value.expected_output_width == 0
        || value.expected_output_width > MAX_NEURON_FEATURES
        || value
            .feature_vector_q24
            .iter()
            .any(|item| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(item))
    {
        return Err(Error::FeatureLimit);
    }
    Ok(())
}

fn validate_neuron_feature_output(
    request: &NeuronFeatureRequest,
    value: &DriverNeuronFeatureObservation,
) -> Result<(), Error> {
    if value.encoder_digest != request.encoder_digest
        || value.head_digest != request.head_digest
        || value.drive_q24.len() != request.expected_output_width
        || value.prediction_q24.len() != request.expected_output_width
        || value
            .drive_q24
            .iter()
            .chain(&value.prediction_q24)
            .any(|item| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(item))
    {
        return Err(Error::FeatureOutputMismatch);
    }
    validate_digest(&value.encoder_digest, "encoder")?;
    validate_digest(&value.head_digest, "head")?;
    Ok(())
}
