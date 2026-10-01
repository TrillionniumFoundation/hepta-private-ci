#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
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

#[path = "model_worker_validation.rs"]
mod validation;

use validation::validate_digest;
use validation::validate_grant;
use validation::validate_identity;
use validation::validate_manifest;
use validation::validate_request;

const MAX_MODELS: usize = 8;
const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_TOKENS: u32 = 1_000_000;
const MAX_NEURON_FEATURES: usize = 512;
const Q24_STATE_LIMIT: i64 = 8 * (1_i64 << 24);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelManifest {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub maximum_tokens: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceGrant {
    pub grant_id: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
    pub maximum_models: usize,
    pub maximum_active_requests: usize,
    pub maximum_memory_bytes: u64,
    pub semantic_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerRequest {
    pub request_id: String,
    pub reservation_id: String,
    pub model_digest: String,
    pub payload_digest: String,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
    pub lease_payload_digest: String,
    pub reservation_model_digest: String,
    pub reservation_maximum_tokens: u32,
    pub cancelled: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverModelHandle {
    pub opaque_id: String,
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelLoadObservation {
    pub model_id: String,
    pub worker_generation: u64,
    pub handle_id: String,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ExecutionStatus {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceExecutionObservation {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_generation: u64,
    pub model_digest: String,
    pub payload_digest: String,
    pub status: ExecutionStatus,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    pub observed_memory_bytes: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelUnloadObservation {
    pub model_id: String,
    pub worker_generation: u64,
    pub terminal_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidManifest,
    InvalidGrant,
    GrantExpired,
    GrantRevoked,
    ModelCapacity,
    RequestCapacity,
    ModelAlreadyLoaded,
    ModelNotLoaded,
    ModelUnavailable,
    ModelMismatch,
    PayloadMismatch,
    TokenLimit,
    DeadlineExpired,
    ActiveRequests,
    DriverFailure(String),
    MissingTerminalOutput,
    ArithmeticOverflow,
    FeatureLimit,
    FeatureOutputMismatch,
    FeatureContract,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Physical model execution and cleanup owned by the local runtime driver.
///
/// A failed load must release acquired resources when no handle is returned.
/// If load unwinds without a handle, abandon the fenced worker generation and
/// physically clean driver resources before creating a new isolated worker.
/// `unload` must drain outstanding work and return `Ok` only after the handle's
/// resources are confirmed released. Failed unloads may be retried with the
/// same handle; the worker keeps uncertain models fenced until that succeeds.
pub trait ModelDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error>;
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error>;
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error>;
}

#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    active_requests: usize,
    cleanup_pending: bool,
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
    load_uncertain: bool,
}

impl<D: ModelDriver> InferenceWorker<D> {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        generation: u64,
        grant: ResourceGrant,
        driver: D,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        validate_grant(now_ms, &grant)?;
        if generation == 0 || generation != grant.generation {
            return Err(Error::InvalidGrant);
        }
        Ok(Self {
            worker_id,
            generation,
            grant,
            driver,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
            load_uncertain: false,
        })
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    pub fn load_model(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
    ) -> Result<ModelLoadObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_manifest(&manifest)?;
        if self.models.contains_key(&manifest.model_id) {
            return Err(Error::ModelAlreadyLoaded);
        }
        let model_limit = self.grant.maximum_models.min(MAX_MODELS);
        if self.models.len() >= model_limit {
            return Err(Error::ModelCapacity);
        }
        let resident_memory_bytes = self.resident_memory_bytes()?;
        if resident_memory_bytes >= self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        // A caller may catch the driver's unwind; unknown allocation stays fenced.
        self.load_uncertain = true;
        let loaded = self.driver.load(&manifest);
        self.load_uncertain = false;
        let handle = loaded?;
        let handle_validation =
            validate_identity(&handle.opaque_id, "model handle").and_then(|()| {
                let memory_bytes = resident_memory_bytes
                    .checked_add(handle.observed_memory_bytes)
                    .ok_or(Error::ArithmeticOverflow)?;
                if memory_bytes > self.grant.maximum_memory_bytes {
                    return Err(Error::ModelCapacity);
                }
                Ok(())
            });
        if let Err(error) = handle_validation {
            let model_id = manifest.model_id.clone();
            let cleanup_handle = handle.clone();
            self.models.insert(
                model_id.clone(),
                LoadedModel {
                    manifest,
                    handle,
                    active_requests: 0,
                    cleanup_pending: true,
                },
            );
            self.driver.unload(cleanup_handle)?;
            self.models.remove(&model_id);
            return Err(error);
        }
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        self.models.insert(
            manifest.model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                active_requests: 0,
                cleanup_pending: false,
            },
        );
        Ok(observation)
    }

    pub fn run(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
    ) -> Result<InferenceExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request)?;
        if self.active_requests.contains_key(&request.request_id) {
            return Err(Error::RequestCapacity);
        }
        let request_limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self.active_requests.len() >= request_limit {
            return Err(Error::RequestCapacity);
        }
        let resident_memory_bytes = self.resident_memory_bytes()?;
        if resident_memory_bytes > self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.cleanup_pending {
            return Err(Error::ModelUnavailable);
        }
        if request.model_digest != loaded.manifest.model_digest
            || request.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.maximum_tokens > loaded.manifest.maximum_tokens
            || request.maximum_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if request.payload_digest != request.lease_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        if request.cancelled {
            return Ok(InferenceExecutionObservation {
                request_id: request.request_id,
                reservation_id: request.reservation_id,
                worker_generation: self.generation,
                model_digest: request.model_digest,
                payload_digest: request.payload_digest,
                status: ExecutionStatus::Cancelled,
                output_digest: None,
                consumed_tokens: 0,
                observed_memory_bytes: loaded.handle.observed_memory_bytes,
                terminal_observed: true,
            });
        }

        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(request.request_id.clone(), model_id.to_string());
        loaded.cleanup_pending = true;
        let observed = self.driver.run(&loaded.handle, &request);
        self.active_requests.remove(&request.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                loaded.cleanup_pending = true;
                return Err(error);
            }
        };
        let other_memory_bytes = resident_memory_bytes - loaded.handle.observed_memory_bytes;
        loaded.handle.observed_memory_bytes = loaded
            .handle
            .observed_memory_bytes
            .max(observed.observed_memory_bytes);
        if observed.consumed_tokens > request.maximum_tokens
            || observed.consumed_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if other_memory_bytes
            .checked_add(loaded.handle.observed_memory_bytes)
            .ok_or(Error::ArithmeticOverflow)?
            > self.grant.maximum_memory_bytes
        {
            return Err(Error::ModelCapacity);
        }
        let (status, output_digest, terminal_observed) = if !observed.terminal_observed {
            (ExecutionStatus::Indeterminate, None, false)
        } else if observed.succeeded {
            let output = observed
                .output_digest
                .as_ref()
                .ok_or(Error::MissingTerminalOutput)?;
            validate_digest(output, "output")?;
            (ExecutionStatus::Succeeded, observed.output_digest, true)
        } else {
            if let Some(output) = &observed.output_digest {
                validate_digest(output, "output")?;
            }
            (ExecutionStatus::Failed, observed.output_digest, true)
        };
        loaded.cleanup_pending = !terminal_observed;
        Ok(InferenceExecutionObservation {
            request_id: request.request_id,
            reservation_id: request.reservation_id,
            worker_generation: self.generation,
            model_digest: request.model_digest,
            payload_digest: request.payload_digest,
            status,
            output_digest,
            consumed_tokens: observed.consumed_tokens,
            observed_memory_bytes: observed.observed_memory_bytes,
            terminal_observed,
        })
    }

    pub fn unload_model(
        &mut self,
        now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        match self.validate_current_grant(now_ms) {
            Ok(()) | Err(Error::GrantExpired | Error::GrantRevoked) => {}
            Err(error) => return Err(error),
        }
        validate_identity(model_id, "model")?;
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 && !loaded.cleanup_pending {
            return Err(Error::ActiveRequests);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.cleanup_pending = true;
        self.driver.unload(loaded.handle.clone())?;
        self.active_requests
            .retain(|_, active_model_id| active_model_id != model_id);
        self.models.remove(model_id);
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        validate_grant(now_ms, &self.grant)
    }

    fn resident_memory_bytes(&self) -> Result<u64, Error> {
        if self.load_uncertain {
            return Err(Error::ModelUnavailable);
        }
        self.models.values().try_fold(0_u64, |total, loaded| {
            if loaded.cleanup_pending {
                return Err(Error::ModelUnavailable);
            }
            total
                .checked_add(loaded.handle.observed_memory_bytes)
                .ok_or(Error::ArithmeticOverflow)
        })
    }
}

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

/// Executes the frozen encoder/head feature path for an already loaded model.
/// The driver must report the actual encoder/head identities and resource
/// measurements observed for this invocation.
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
        {
            return Err(Error::RequestCapacity);
        }
        let request_limit = self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS);
        if self.active_requests.len() >= request_limit {
            return Err(Error::RequestCapacity);
        }
        let resident_memory_bytes = self.resident_memory_bytes()?;
        if resident_memory_bytes > self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.cleanup_pending {
            return Err(Error::ModelUnavailable);
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

        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests.insert(
            request.authorization.request_id.clone(),
            model_id.to_string(),
        );
        loaded.cleanup_pending = true;
        let observed = self.driver.run_neuron_features(&loaded.handle, &request);
        self.active_requests
            .remove(&request.authorization.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let mut observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                loaded.cleanup_pending = true;
                return Err(error);
            }
        };
        let other_memory_bytes = resident_memory_bytes - loaded.handle.observed_memory_bytes;
        loaded.handle.observed_memory_bytes = loaded
            .handle
            .observed_memory_bytes
            .max(observed.observed_memory_bytes);
        if other_memory_bytes
            .checked_add(loaded.handle.observed_memory_bytes)
            .and_then(|total| total.checked_add(observed.transient_allocation_bytes))
            .ok_or(Error::ArithmeticOverflow)?
            > self.grant.maximum_memory_bytes
        {
            return Err(Error::ModelCapacity);
        }
        validate_digest(&observed.encoder_digest, "encoder")?;
        validate_digest(&observed.head_digest, "head")?;
        if observed.encoder_digest != request.encoder_digest
            || observed.head_digest != request.head_digest
        {
            return Err(Error::FeatureOutputMismatch);
        }
        let status = if !observed.terminal_observed {
            ExecutionStatus::Indeterminate
        } else if observed.succeeded {
            validate_neuron_feature_output(&request, &observed)?;
            ExecutionStatus::Succeeded
        } else {
            ExecutionStatus::Failed
        };
        if status != ExecutionStatus::Succeeded {
            observed.drive_q24.clear();
            observed.prediction_q24.clear();
        }
        loaded.cleanup_pending = !observed.terminal_observed;
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
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Execute the worker path and project the observed result into the
    /// inference-control-owned typed receipt.
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
    let mut bytes = b"hepta.infer-worker.neuron-feature-request.v1".to_vec();
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
    if value.drive_q24.len() != request.expected_output_width
        || value.prediction_q24.len() != request.expected_output_width
        || value
            .drive_q24
            .iter()
            .chain(&value.prediction_q24)
            .any(|item| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(item))
    {
        return Err(Error::FeatureOutputMismatch);
    }
    Ok(())
}

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
