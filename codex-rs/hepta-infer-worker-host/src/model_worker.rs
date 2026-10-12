#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
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
const MAX_TOKENS: u32 = 1_000_000;
const MAX_NEURON_FEATURES: usize = 512;
// Bounded in-process tombstones. Production restart replay still requires the
// independent durable reservation owner and a new generation fence.
const MAX_NEURON_ATTEMPTS: usize = 65_536;
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
    NeuronReservationReplay,
    NeuronReservationCapacity,
    /// A prior model-load/unload outcome is unknown; retire this Worker
    /// generation rather than reusing potentially leaked physical resources.
    WorkerQuarantined,
    ModelHandleConflict,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

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
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
    // Exact request and reservation identity cannot run twice within one
    // Worker instance, even if a fresh ModelPort is constructed around it.
    used_neuron_requests: BTreeSet<Digest32>,
    used_neuron_reservations: BTreeSet<Digest32>,
    /// Unknown model-loader/unloader outcome poisons all future work in this
    /// instance, including attempts with freshly issued reservations.
    quarantined: bool,
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
            used_neuron_requests: BTreeSet::new(),
            used_neuron_reservations: BTreeSet::new(),
            quarantined: false,
        })
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    /// Current worker generation owned by this runtime instance. A process
    /// restart changes this; it is not an independent signed deployment fence.
    pub fn worker_generation(&self) -> u64 {
        self.generation
    }

    /// An ambiguous physical model-load or unload outcome requires external
    /// retirement/restart; changing the grant cannot clear this fence.
    #[must_use]
    pub fn is_quarantined(&self) -> bool {
        self.quarantined
    }

    /// Read only the actual in-memory loaded model and require a current
    /// resource grant. This does not prove a physical CAS load or selection.
    pub(crate) fn inspected_neuron_manifest(
        &self,
        now_ms: u64,
        model_id: &str,
    ) -> Result<&ModelManifest, Error> {
        self.validate_current_grant(now_ms)?;
        self.models
            .get(model_id)
            .map(|model| &model.manifest)
            .ok_or(Error::ModelNotLoaded)
    }

    pub fn load_model(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
    ) -> Result<ModelLoadObservation, Error> {
        self.load_model_with(now_ms, manifest, |driver, selected| driver.load(selected))
    }

    /// Shared single-owner admission for legacy and explicitly file-bound loads.
    /// An FD-bound path never falls back to ModelDriver::load.
    pub(crate) fn load_model_with(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
        loader: impl FnOnce(&mut D, &ModelManifest) -> Result<DriverModelHandle, Error>,
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
        // Bound the SUM of model resident allocations, not each individual
        // handle in isolation. With MAX_MODELS <= 8, this bounded reduction
        // cannot introduce a global lock or a per-cell O(n) hot-path scan.
        let already_loaded = self
            .models
            .values()
            .try_fold(0_u64, |sum, entry| {
                sum.checked_add(entry.handle.observed_memory_bytes)
            })
            .ok_or(Error::ArithmeticOverflow)?;
        // ModelDriver::load may allocate before returning an error. Fence the
        // entire Worker before calling it: only a fully checked live handle or
        // independently completed cleanup can release this fence.
        self.quarantined = true;
        let handle = loader(&mut self.driver, &manifest)?;
        if validate_identity(&handle.opaque_id, "model handle").is_err() {
            return self.dispose_failed_load(handle, Error::InvalidIdentity("model handle"));
        }
        if self
            .models
            .values()
            .any(|entry| entry.handle.opaque_id == handle.opaque_id)
        {
            // A reused opaque handle may alias a *currently live* model. Do
            // NOT call unload on it: that could destroy the first model.
            // The real loader violated identity isolation; quarantine forever.
            return Err(Error::ModelHandleConflict);
        }
        let total_resident = already_loaded
            .checked_add(handle.observed_memory_bytes)
            .ok_or(Error::ArithmeticOverflow);
        if handle.observed_memory_bytes == 0
            || total_resident.is_err()
            || total_resident
                .ok()
                .is_none_or(|value| value > self.grant.maximum_memory_bytes)
        {
            return self.dispose_failed_load(handle, Error::ModelCapacity);
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
            },
        );
        self.quarantined = false;
        Ok(observation)
    }

    /// Cleanup of an unadmitted physical model is itself a fallible, possibly
    /// indeterminate driver operation. A failed cleanup cannot release the
    /// Worker quarantine, even if the next model has different identifiers.
    fn dispose_failed_load(
        &mut self,
        handle: DriverModelHandle,
        rejection: Error,
    ) -> Result<ModelLoadObservation, Error> {
        self.driver.unload(handle)?;
        self.quarantined = false;
        Err(rejection)
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
        let observed = self.driver.run(&loaded.handle, &request);
        self.active_requests.remove(&request.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = observed?;
        if observed.consumed_tokens > request.maximum_tokens
            || observed.consumed_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if observed.observed_memory_bytes > self.grant.maximum_memory_bytes {
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
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        // Retain the tracked handle until the driver confirms success. On an
        // error the physical unload is unknown, so the entire Worker remains
        // quarantined rather than pretending the released budget is reusable.
        let handle = loaded.handle.clone();
        self.quarantined = true;
        self.driver.unload(handle)?;
        self.models.remove(model_id);
        self.quarantined = false;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    /// Read the actual in-process Neuron request/reservation tombstones without
    /// consuming them. The durable inference.control owner independently checks
    /// the matching reservation and current dispatch state. Neither owner alone
    /// can prove exactly-once execution across a Worker process restart.
    pub(crate) fn verify_neuron_attempt_unconsumed(
        &self,
        request_id: &str,
        reservation_id: &str,
    ) -> Result<(), Error> {
        validate_identity(request_id, "request")?;
        validate_identity(reservation_id, "reservation")?;
        let request_hash = Digest32::of_bytes(request_id.as_bytes());
        let reservation_hash = Digest32::of_bytes(reservation_id.as_bytes());
        if self.used_neuron_requests.contains(&request_hash)
            || self.used_neuron_reservations.contains(&reservation_hash)
        {
            return Err(Error::NeuronReservationReplay);
        }
        if self.used_neuron_requests.len() >= MAX_NEURON_ATTEMPTS
            || self.used_neuron_reservations.len() >= MAX_NEURON_ATTEMPTS
        {
            return Err(Error::NeuronReservationCapacity);
        }
        Ok(())
    }

    /// Consume one preexisting invocation identity before any model/lease check.
    /// This is NOT reservation authentication or crash-durable deduplication.
    /// A full tombstone budget fails closed until a separately admitted new
    /// Worker generation is created by the authoritative host.
    pub(crate) fn consume_neuron_attempt(&mut self, request: &WorkerRequest) -> Result<(), Error> {
        validate_identity(&request.request_id, "request")?;
        validate_identity(&request.reservation_id, "reservation")?;
        let request_hash = Digest32::of_bytes(request.request_id.as_bytes());
        let reservation_hash = Digest32::of_bytes(request.reservation_id.as_bytes());
        let replay = self.used_neuron_requests.contains(&request_hash)
            || self.used_neuron_reservations.contains(&reservation_hash);
        if replay {
            // Also tombstone the unused half of a mixed duplicate pair.
            // Otherwise two rejected attempts could be recombined to form a
            // third usable request without fresh external admission.
            if self.used_neuron_requests.len() < MAX_NEURON_ATTEMPTS {
                self.used_neuron_requests.insert(request_hash);
            }
            if self.used_neuron_reservations.len() < MAX_NEURON_ATTEMPTS {
                self.used_neuron_reservations.insert(reservation_hash);
            }
            return Err(Error::NeuronReservationReplay);
        }
        if self.used_neuron_requests.len() >= MAX_NEURON_ATTEMPTS
            || self.used_neuron_reservations.len() >= MAX_NEURON_ATTEMPTS
        {
            return Err(Error::NeuronReservationCapacity);
        }
        self.used_neuron_requests.insert(request_hash);
        self.used_neuron_reservations.insert(reservation_hash);
        Ok(())
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        if self.quarantined {
            return Err(Error::WorkerQuarantined);
        }
        validate_grant(now_ms, &self.grant)
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
    /// Tokens the backend actually observed consuming. A claimed quota is not
    /// evidence of physical usage, so validate this after the driver returns.
    pub consumed_tokens: u32,
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
    pub consumed_tokens: u32,
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
    /// Legacy direct feature execution for module-local tests only. Production
    /// must obtain its one-use WorkerNeuronControlPort from the fsynced
    /// claim_neuron_durable_dispatch_v1 path.
    #[cfg(test)]
    pub(crate) fn run_neuron_features(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.consume_neuron_attempt(&request.authorization)?;
        self.run_neuron_features_consumed(now_ms, model_id, request)
    }

    /// Internal continuation after an in-process identity tombstone has been
    /// committed. Only the owner that consumed the identity may call this.
    fn run_neuron_features_consumed(
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
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if request.authorization.model_digest != loaded.manifest.model_digest
            || request.authorization.reservation_model_digest != loaded.manifest.model_digest
            || request.weights_digest != loaded.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        // Never rely solely on the upstream durable owner to enforce token
        // budgets. Ordinary Worker::run checks both limits; the typed Neuron
        // path must impose the same bounds before invoking the real driver.
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
                consumed_tokens: 0,
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
        let observed = self.driver.run_neuron_features(&loaded.handle, &request);
        self.active_requests
            .remove(&request.authorization.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = observed?;
        // This is a post-driver resource check: the physical operation may
        // have happened. The owning ModelPort MUST classify this error as
        // Indeterminate and may not replay the consumed durable reservation.
        if observed.consumed_tokens > request.authorization.maximum_tokens
            || observed.consumed_tokens > request.authorization.reservation_maximum_tokens
            || observed.consumed_tokens > loaded.manifest.maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if observed.observed_memory_bytes > self.grant.maximum_memory_bytes {
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
            consumed_tokens: observed.consumed_tokens,
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
    /// Module-local compatibility test path. Not compiled into the product
    /// library: a caller must fsync inference.control's Dispatching claim
    /// before executing the typed Neuron Worker/ModelPort.
    #[cfg(test)]
    pub(crate) fn run_neuron_features_receipt(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        let logical_generation =
            Generation::new(self.generation).map_err(|_| Error::FeatureContract)?;
        self.consume_neuron_attempt(&request.authorization)?;
        self.run_neuron_features_receipt_consumed(now_ms, model_id, request, logical_generation)
    }

    /// Used by WorkerNeuronControlPort after it records the attempt BEFORE
    /// its own preflight. Never call without consuming in the same Worker.
    pub(crate) fn run_neuron_features_receipt_consumed(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
        logical_generation: Generation,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        let request_copy = request.clone();
        let observed = self.run_neuron_features_consumed(now_ms, model_id, request)?;
        // The worker generation is already checked by durable Assignment.
        // The typed request/receipt generation names the NEURON model, which
        // is allowed to survive an independently restarted Worker process.
        let control_request = NeuronFeatureRequestV1 {
            request_id: StableId::new(request_copy.authorization.request_id)
                .map_err(|_| Error::FeatureContract)?,
            generation: logical_generation,
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

#[path = "neuron_weight_file.rs"]
mod neuron_weight_file;
pub use neuron_weight_file::NeuronFileBoundModelLoadV1;
pub use neuron_weight_file::NeuronPreopenedWeightModelDriver;
pub use neuron_weight_file::NeuronWeightFileDiagnosticErrorV1;
pub use neuron_weight_file::NeuronWeightFileDiagnosticV1;
pub use neuron_weight_file::inspect_loaded_neuron_weight_file_v1;

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
