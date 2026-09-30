#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

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
    /// Aggregate retained model bytes plus additional invocation transient
    /// bytes. Drivers must enforce the physical allocation bound themselves;
    /// post-invocation observations cannot prevent an allocation or OOM.
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
    /// Retained bytes attributable to this model after load, excluding other
    /// models and per-invocation transient allocations.
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub output_digest: Option<String>,
    pub consumed_tokens: u32,
    /// Retained bytes attributable to this model after the invocation. The
    /// worker accounts the largest observation until confirmed unload.
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
    DriverUnavailable,
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

/// Executes model lifecycle operations and reports actual observations.
/// A driver error or nonterminal run does not prove that resources or execution
/// have stopped; the worker preserves the corresponding local fence.
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
    resident_memory_bytes: u64,
    active_requests: usize,
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
    driver_fenced: bool,
    resource_fenced: bool,
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
            driver_fenced: false,
            resource_fenced: false,
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
        let resident_memory = self.resident_memory_bytes()?;
        let handle = match self.driver.load(&manifest) {
            Ok(handle) => handle,
            Err(error) => {
                self.driver_fenced = true;
                return Err(error);
            }
        };
        let admission = validate_identity(&handle.opaque_id, "model handle").and_then(|()| {
            resident_memory
                .checked_add(handle.observed_memory_bytes)
                .filter(|total| *total <= self.grant.maximum_memory_bytes)
                .map(|_| ())
                .ok_or(Error::ModelCapacity)
        });
        if let Err(error) = admission {
            if let Err(cleanup_error) = self.driver.unload(handle) {
                self.driver_fenced = true;
                return Err(cleanup_error);
            }
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
                resident_memory_bytes: handle.observed_memory_bytes,
                handle,
                active_requests: 0,
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
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
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
                observed_memory_bytes: loaded.resident_memory_bytes,
                terminal_observed: true,
            });
        }

        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(request.request_id.clone(), model_id.to_string());
        let observed = self.driver.run(&loaded.handle, &request);
        let observed = observed?;
        if observed.terminal_observed {
            self.active_requests.remove(&request.request_id);
            loaded.active_requests = loaded.active_requests.saturating_sub(1);
        }
        self.observe_memory(model_id, observed.observed_memory_bytes, /*transient_bytes*/ 0)?;
        if observed.consumed_tokens > request.maximum_tokens
            || observed.consumed_tokens > request.reservation_maximum_tokens
        {
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

    /// Release a known idle model even after its grant expires or is revoked.
    /// An uncertain driver or active execution still requires external
    /// reconciliation; cleanup never retries an unknown unload outcome.
    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        if self.driver_fenced {
            return Err(Error::DriverUnavailable);
        }
        validate_identity(model_id, "model")?;
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        if let Err(error) = self.driver.unload(loaded.handle.clone()) {
            self.driver_fenced = true;
            return Err(error);
        }
        self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        if self.models.is_empty() {
            self.resource_fenced = false;
        }
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        if self.driver_fenced {
            return Err(Error::DriverUnavailable);
        }
        if self.resource_fenced {
            return Err(Error::ModelCapacity);
        }
        validate_grant(now_ms, &self.grant)
    }

    fn resident_memory_bytes(&self) -> Result<u64, Error> {
        self.models.values().try_fold(0_u64, |total, model| {
            total
                .checked_add(model.resident_memory_bytes)
                .ok_or(Error::ModelCapacity)
        })
    }

    fn observe_memory(
        &mut self,
        model_id: &str,
        observed_memory_bytes: u64,
        transient_bytes: u64,
    ) -> Result<(), Error> {
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.resident_memory_bytes = loaded.resident_memory_bytes.max(observed_memory_bytes);
        let within_limit = self
            .resident_memory_bytes()
            .ok()
            .and_then(|resident| resident.checked_add(transient_bytes))
            .is_some_and(|peak| peak <= self.grant.maximum_memory_bytes);
        if !within_limit {
            // Keep known handles available for cleanup, but admit no further
            // work until every model has actually been released.
            self.resource_fenced = true;
            return Err(Error::ModelCapacity);
        }
        Ok(())
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

#[path = "model_worker_features.rs"]
mod neuron_features;

pub use neuron_features::DriverNeuronFeatureObservation;
pub use neuron_features::NeuronFeatureDriver;
pub use neuron_features::NeuronFeatureExecutionObservation;
pub use neuron_features::NeuronFeatureRequest;
pub use neuron_features::canonical_neuron_feature_payload_digest;

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
