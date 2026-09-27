//! Experimental synchronous driver boundary, not a production local inference host.
//!
//! Resource observations are driver reports, not device attestations. Operation
//! history below prevents re-entry only within this instance; durable admission
//! and crash reconciliation remain owned by inference.control.

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

const MAX_MODELS: usize = 8;
const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_REQUEST_HISTORY: usize = 16_384;
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
    UnboundedDriver,
    RepairRequired,
    RequestConflict,
    RequestIndeterminate,
    HistoryCapacity,
    GenerationFenced,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Implementations must retain/reconcile any resource acquired before an error.
/// An unload success proves physical release, not merely that release was queued.
pub trait ModelDriver {
    /// Opt-in bounded loading. There is deliberately no fallback to `load`:
    /// implementing the old interface does not establish memory enforcement.
    fn load_with_budget(
        &mut self,
        _manifest: &ModelManifest,
        _maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error> {
        Err(Error::UnboundedDriver)
    }

    /// Inspect the exact handle after a failed unload; never infer absence from
    /// a timeout, connection failure, or an empty local registry.
    fn inspect_model(&mut self, _handle: &DriverModelHandle) -> Result<ModelPresence, Error> {
        Ok(ModelPresence::Unknown)
    }

    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error>;
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error>;
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelPresence {
    Present,
    Absent,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelLifecycle {
    Ready,
    RepairRequired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum RequestIdentity {
    Tokens(String, ModelManifest, WorkerRequest),
    Features(String, ModelManifest, NeuronFeatureRequest),
}

#[derive(Clone, Debug)]
enum RecordedOutput {
    Tokens(Box<InferenceExecutionObservation>),
    Features(Box<NeuronFeatureExecutionObservation>),
}

#[derive(Debug)]
struct RequestEvidence {
    identity: RequestIdentity,
    output: Option<RecordedOutput>,
}

#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    active_requests: usize,
    lifecycle: ModelLifecycle,
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
    history: BTreeMap<String, RequestEvidence>,
    fenced: bool,
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
            history: BTreeMap::new(),
            fenced: false,
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
        // This API has no trusted pre-load estimate. Bound this call by the
        // remaining allowance for the synchronous call, not the original cap.
        let remaining = self
            .grant
            .maximum_memory_bytes
            .checked_sub(self.resident_memory_bytes()?)
            .filter(|remaining| *remaining != 0)
            .ok_or(Error::ModelCapacity)?;
        let handle = match self.driver.load_with_budget(&manifest, remaining) {
            Ok(handle) => handle,
            Err(error) => {
                // The legacy error type cannot prove that nothing was acquired.
                self.fenced = true;
                return Err(error);
            }
        };
        let invalid = validate_identity(&handle.opaque_id, "model handle")
            .err()
            .or_else(|| (handle.observed_memory_bytes > remaining).then_some(Error::ModelCapacity));
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        // Register the acquired handle before any fallible cleanup. Retain the
        // original handle if the driver's release outcome is unknown.
        let model_id = manifest.model_id.clone();
        self.models.insert(
            model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                active_requests: 0,
                lifecycle: ModelLifecycle::Ready,
            },
        );
        if let Some(error) = invalid {
            self.unload_model(now_ms, &model_id)?;
            return Err(error);
        }
        Ok(observation)
    }

    pub fn run(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
    ) -> Result<InferenceExecutionObservation, Error> {
        if let Some(previous) = self.history.get(&request.request_id) {
            let same = match &previous.identity {
                RequestIdentity::Tokens(previous_model, manifest, previous_request) => {
                    previous_model == model_id
                        && previous_request == &request
                        && self
                            .models
                            .get(model_id)
                            .is_none_or(|current| &current.manifest == manifest)
                }
                RequestIdentity::Features(_, _, _) => false,
            };
            if !same {
                return Err(Error::RequestConflict);
            }
            return match &previous.output {
                Some(RecordedOutput::Tokens(output)) => Ok((**output).clone()),
                Some(RecordedOutput::Features(_)) | None => Err(Error::RequestIndeterminate),
            };
        }
        if self.history.len() >= MAX_REQUEST_HISTORY {
            return Err(Error::HistoryCapacity);
        }
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
        let other_memory = self.other_resident_memory(model_id)?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Ready {
            return Err(Error::RepairRequired);
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

        self.history.insert(
            request.request_id.clone(),
            RequestEvidence {
                identity: RequestIdentity::Tokens(
                    model_id.to_string(),
                    loaded.manifest.clone(),
                    request.clone(),
                ),
                output: None,
            },
        );
        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(request.request_id.clone(), model_id.to_string());
        let observed = match self.driver.run(&loaded.handle, &request) {
            Ok(observed) => observed,
            Err(error) => {
                loaded.lifecycle = ModelLifecycle::RepairRequired;
                self.fenced = true;
                return Err(error);
            }
        };
        if observed.terminal_observed {
            self.active_requests.remove(&request.request_id);
            loaded.active_requests = loaded
                .active_requests
                .checked_sub(1)
                .ok_or(Error::ArithmeticOverflow)?;
        } else {
            // Unknown execution still owns its slot and model handle.
            loaded.lifecycle = ModelLifecycle::RepairRequired;
            self.fenced = true;
        }
        loaded.handle.observed_memory_bytes = loaded
            .handle
            .observed_memory_bytes
            .max(observed.observed_memory_bytes);
        let total = other_memory.checked_add(loaded.handle.observed_memory_bytes);
        if total.is_none_or(|total| total > self.grant.maximum_memory_bytes) {
            loaded.lifecycle = ModelLifecycle::RepairRequired;
            self.fenced = true;
            return Err(Error::ModelCapacity);
        }
        if observed.consumed_tokens > request.maximum_tokens
            || observed.consumed_tokens > request.reservation_maximum_tokens
        {
            loaded.lifecycle = ModelLifecycle::RepairRequired;
            return Err(Error::TokenLimit);
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
        let output = InferenceExecutionObservation {
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
        };
        self.history
            .get_mut(&output.request_id)
            .ok_or(Error::RequestIndeterminate)?
            .output = Some(RecordedOutput::Tokens(Box::new(output.clone())));
        Ok(output)
    }

    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        // Revocation/expiry/fencing prohibit new work, never safe cleanup.
        validate_identity(model_id, "model")?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        if loaded.lifecycle == ModelLifecycle::RepairRequired {
            return Err(Error::RepairRequired);
        }
        loaded.lifecycle = ModelLifecycle::RepairRequired;
        self.driver.unload(loaded.handle.clone())?;
        self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    /// Reconcile a failed release before retrying it. Unknown remains held.
    pub fn reconcile_model_cleanup(
        &mut self,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        validate_identity(model_id, "model")?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        if loaded.lifecycle != ModelLifecycle::RepairRequired {
            return Err(Error::RepairRequired);
        }
        match self.driver.inspect_model(&loaded.handle)? {
            ModelPresence::Unknown => return Err(Error::RepairRequired),
            ModelPresence::Present => self.driver.unload(loaded.handle.clone())?,
            ModelPresence::Absent => {}
        }
        self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    pub fn model_lifecycle(&self, model_id: &str) -> Option<ModelLifecycle> {
        self.models.get(model_id).map(|model| model.lifecycle)
    }

    pub fn resident_memory_bytes(&self) -> Result<u64, Error> {
        self.models.values().try_fold(0_u64, |total, model| {
            total
                .checked_add(model.handle.observed_memory_bytes)
                .ok_or(Error::ArithmeticOverflow)
        })
    }

    /// A device reset fences this entire instance. It cannot be unfenced by
    /// changing a request ID or by clearing the in-memory history.
    pub fn fence_generation(&mut self) {
        self.fenced = true;
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        if self.fenced {
            return Err(Error::GenerationFenced);
        }
        validate_grant(now_ms, &self.grant)
    }

    fn other_resident_memory(&self, model_id: &str) -> Result<u64, Error> {
        let model = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        self.resident_memory_bytes()?
            .checked_sub(model.handle.observed_memory_bytes)
            .ok_or(Error::ArithmeticOverflow)
    }
}

fn validate_manifest(value: &ModelManifest) -> Result<(), Error> {
    validate_identity(&value.model_id, "model")?;
    for (digest, field) in [
        (&value.model_digest, "model"),
        (&value.weights_digest, "weights"),
        (&value.tokenizer_digest, "tokenizer"),
        (&value.preprocessor_digest, "preprocessor"),
        (&value.quantization_digest, "quantization"),
        (&value.runtime_digest, "runtime"),
        (&value.device_digest, "device"),
    ] {
        validate_digest(digest, field)?;
    }
    if value.maximum_tokens == 0 || value.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidManifest);
    }
    Ok(())
}

fn validate_grant(now_ms: u64, value: &ResourceGrant) -> Result<(), Error> {
    validate_identity(&value.grant_id, "grant")?;
    validate_digest(&value.semantic_digest, "grant semantic")?;
    if value.revoked {
        return Err(Error::GrantRevoked);
    }
    if value.authority_epoch == 0
        || value.generation == 0
        || value.maximum_models == 0
        || value.maximum_active_requests == 0
        || value.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidGrant);
    }
    if now_ms >= value.expires_at_ms {
        return Err(Error::GrantExpired);
    }
    Ok(())
}

fn validate_request(now_ms: u64, value: &WorkerRequest) -> Result<(), Error> {
    validate_identity(&value.request_id, "request")?;
    validate_identity(&value.reservation_id, "reservation")?;
    validate_digest(&value.model_digest, "model")?;
    validate_digest(&value.payload_digest, "payload")?;
    validate_digest(&value.lease_payload_digest, "lease payload")?;
    validate_digest(&value.reservation_model_digest, "reservation model")?;
    if value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.reservation_maximum_tokens == 0
        || value.reservation_maximum_tokens > MAX_TOKENS
    {
        return Err(Error::TokenLimit);
    }
    if now_ms >= value.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
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
        if let Some(previous) = self.history.get(&request.authorization.request_id) {
            let same = match &previous.identity {
                RequestIdentity::Features(previous_model, manifest, previous_request) => {
                    previous_model == model_id
                        && previous_request == &request
                        && self
                            .models
                            .get(model_id)
                            .is_none_or(|current| &current.manifest == manifest)
                }
                RequestIdentity::Tokens(_, _, _) => false,
            };
            if !same {
                return Err(Error::RequestConflict);
            }
            return match &previous.output {
                Some(RecordedOutput::Features(output)) => Ok((**output).clone()),
                Some(RecordedOutput::Tokens(_)) | None => Err(Error::RequestIndeterminate),
            };
        }
        if self.history.len() >= MAX_REQUEST_HISTORY {
            return Err(Error::HistoryCapacity);
        }
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
        let other_memory = self.other_resident_memory(model_id)?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Ready {
            return Err(Error::RepairRequired);
        }
        if request.authorization.model_digest != loaded.manifest.model_digest
            || request.authorization.reservation_model_digest != loaded.manifest.model_digest
            || request.weights_digest != loaded.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.authorization.maximum_tokens > loaded.manifest.maximum_tokens
            || request.authorization.maximum_tokens > request.authorization.reservation_maximum_tokens
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

        self.history.insert(
            request.authorization.request_id.clone(),
            RequestEvidence {
                identity: RequestIdentity::Features(
                    model_id.to_string(),
                    loaded.manifest.clone(),
                    request.clone(),
                ),
                output: None,
            },
        );
        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests.insert(
            request.authorization.request_id.clone(),
            model_id.to_string(),
        );
        let observed = match self.driver.run_neuron_features(&loaded.handle, &request) {
            Ok(observed) => observed,
            Err(error) => {
                loaded.lifecycle = ModelLifecycle::RepairRequired;
                self.fenced = true;
                return Err(error);
            }
        };
        if observed.terminal_observed {
            self.active_requests.remove(&request.authorization.request_id);
            loaded.active_requests = loaded
                .active_requests
                .checked_sub(1)
                .ok_or(Error::ArithmeticOverflow)?;
        } else {
            // Unknown execution still owns its slot and model handle.
            loaded.lifecycle = ModelLifecycle::RepairRequired;
            self.fenced = true;
        }
        loaded.handle.observed_memory_bytes = loaded
            .handle
            .observed_memory_bytes
            .max(observed.observed_memory_bytes);
        let total = other_memory
            .checked_add(loaded.handle.observed_memory_bytes)
            .and_then(|total| total.checked_add(observed.transient_allocation_bytes));
        if total.is_none_or(|total| total > self.grant.maximum_memory_bytes) {
            loaded.lifecycle = ModelLifecycle::RepairRequired;
            self.fenced = true;
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
        let output = NeuronFeatureExecutionObservation {
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
        };
        self.history
            .get_mut(&output.request_id)
            .ok_or(Error::RequestIndeterminate)?
            .output = Some(RecordedOutput::Features(Box::new(output.clone())));
        Ok(output)
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

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "model_worker_hardening_tests.rs"]
mod hardening_tests;
