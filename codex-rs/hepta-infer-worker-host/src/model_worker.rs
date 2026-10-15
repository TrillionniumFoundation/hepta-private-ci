#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_infer_core::BoundStemNeuronRequestV1;
use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::StemAccessContextV1;
use codex_hepta_infer_core::StemFeatureRefV1;
use codex_hepta_infer_core::StemHeadBindingV1;
use codex_hepta_infer_core::bind_stem_feature_request_v1;
use codex_hepta_infer_core::borrow_stem_feature_request_v1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::stem_artifact_cas::StemArtifactCasVerifierV1;
use crate::stem_artifact_cas::VerifiedStemCasArtifactsV1;

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
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
    IndeterminateLifecycle,
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
    FinalUseDenied,
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
    poisoned: bool,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
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
            poisoned: false,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
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
        let handle = match self.driver.load(&manifest) {
            Ok(handle) => handle,
            Err(_) => {
                // The driver has not proven that partial allocations did
                // not occur before returning its error. A fresh Worker
                // generation needs independent resource reconciliation.
                self.poisoned = true;
                return Err(Error::IndeterminateLifecycle);
            }
        };
        if let Err(error) = validate_identity(&handle.opaque_id, "model handle") {
            if self.driver.unload(handle).is_err() {
                self.poisoned = true;
                return Err(Error::IndeterminateLifecycle);
            }
            return Err(error);
        }
        // Opaque handles are owned by one loaded model. If a buggy driver
        // returns an already-live handle for another manifest, unloading the
        // new handle could also unload the original model. Keep both physical
        // outcomes quarantined for owner-led generation reconciliation.
        if self
            .models
            .values()
            .any(|loaded| loaded.handle.opaque_id == handle.opaque_id)
        {
            self.poisoned = true;
            return Err(Error::IndeterminateLifecycle);
        }
        // Account for all resident model handles, not merely the new model.
        let total_after_load = self
            .models
            .values()
            .try_fold(0_u64, |total, loaded| {
                total.checked_add(loaded.handle.observed_memory_bytes)
            })
            .and_then(|total| total.checked_add(handle.observed_memory_bytes));
        if !matches!(total_after_load, Some(total) if total <= self.grant.maximum_memory_bytes) {
            if self.driver.unload(handle).is_err() {
                self.poisoned = true;
                return Err(Error::IndeterminateLifecycle);
            }
            return Err(Error::ModelCapacity);
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
        // The grant covers every resident model, not just the selected one.
        let other_model_resident_bytes = self.other_model_resident_bytes(model_id)?;
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
        let observed = match observed {
            Ok(observed) => observed,
            Err(_) => {
                // Execution may already have occurred before the driver
                // reported failure; never retry it in this generation.
                self.poisoned = true;
                return Err(Error::IndeterminateLifecycle);
            }
        };
        if !observed.terminal_observed {
            self.poisoned = true;
        }
        if observed.consumed_tokens > request.maximum_tokens
            || observed.consumed_tokens > request.reservation_maximum_tokens
        {
            self.poisoned = true;
            return Err(Error::TokenLimit);
        }
        // A later driver observation cannot lower the load-time resident floor.
        let selected_resident_bytes = observed
            .observed_memory_bytes
            .max(loaded.handle.observed_memory_bytes);
        let claimed_peak = selected_resident_bytes.checked_add(other_model_resident_bytes);
        if claimed_peak.is_none_or(|bytes| bytes > self.grant.maximum_memory_bytes) {
            self.poisoned = true;
            return Err(Error::ModelCapacity);
        }
        let (status, output_digest, terminal_observed) = if !observed.terminal_observed {
            (ExecutionStatus::Indeterminate, None, false)
        } else if observed.succeeded {
            let Some(output) = observed.output_digest.as_ref() else {
                self.poisoned = true;
                return Err(Error::MissingTerminalOutput);
            };
            if let Err(error) = validate_digest(output, "output") {
                self.poisoned = true;
                return Err(error);
            }
            (ExecutionStatus::Succeeded, observed.output_digest, true)
        } else {
            if let Some(output) = &observed.output_digest {
                if let Err(error) = validate_digest(output, "output") {
                    self.poisoned = true;
                    return Err(error);
                }
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
        let loaded = self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        if self.driver.unload(loaded.handle).is_err() {
            // Physical unload may have occurred despite the error. Forbid any
            // further use of this worker until its owner reconciles/restarts.
            self.poisoned = true;
            return Err(Error::IndeterminateLifecycle);
        }
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    fn other_model_resident_bytes(&self, excluded_model_id: &str) -> Result<u64, Error> {
        self.models
            .iter()
            .filter(|(model_id, _)| model_id.as_str() != excluded_model_id)
            .try_fold(0_u64, |total, (_, model)| {
                total
                    .checked_add(model.handle.observed_memory_bytes)
                    .ok_or(Error::ArithmeticOverflow)
            })
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        if self.poisoned {
            return Err(Error::IndeterminateLifecycle);
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
    pub encoder_digest: String,
    pub head_digest: String,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
}

/// Exact scoped Stem feature binding + terminal inference-control receipt.
/// The ref digest and all input identity data remain caller/host supplied and
/// are NOT an independent signature or external model-load attestation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundStemFeatureExecutionV1 {
    pub stem_feature_ref_digest: Digest32,
    /// The domain-separated Scope/Principal/Generation-bound input digest
    /// actually incorporated into the Worker payload and receipt.
    pub scoped_input_digest: Digest32,
    pub worker_receipt: NeuronFeatureReceiptV1,
    /// Hash witness for the exact signed final-use binding. This is NOT a
    /// signed execution receipt or an NDU acceptance decision.
    pub final_use_binding_digest: Option<Digest32>,
    pub authority: codex_hepta_types::AuthorityPosture,
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
    // Only unit-test the legacy owned path; production must enter via signed
    // final-use receipt dispatch rather than this unguarded internal helper.
    #[cfg(test)]
    pub(crate) fn run_neuron_features(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.run_neuron_features_borrowed(now_ms, model_id, &request)
    }

    /// Existing grant, token, payload and resource validation remains mandatory.
    fn run_neuron_features_borrowed(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: &NeuronFeatureRequest,
    ) -> Result<NeuronFeatureExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request.authorization)?;
        validate_neuron_feature_request(request)?;
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
        // Account for all other live models before borrowing the selected Head.
        let other_model_resident_bytes = self.other_model_resident_bytes(model_id)?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if request.authorization.model_digest != loaded.manifest.model_digest
            || request.authorization.reservation_model_digest != loaded.manifest.model_digest
            || request.weights_digest != loaded.manifest.weights_digest
        {
            return Err(Error::ModelMismatch);
        }
        // The Neuron feature path must obey the same admission envelope as
        // the ordinary model Driver. A valid payload digest alone does not
        // permit a request larger than the loaded model or reservation.
        if request.authorization.maximum_tokens > loaded.manifest.maximum_tokens
            || request.authorization.maximum_tokens
                > request.authorization.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        let payload_digest = canonical_neuron_feature_payload_digest(request);
        if request.authorization.payload_digest != payload_digest
            || request.authorization.lease_payload_digest != payload_digest
        {
            return Err(Error::PayloadMismatch);
        }
        if request.authorization.cancelled {
            return Ok(NeuronFeatureExecutionObservation {
                request_id: request.authorization.request_id.clone(),
                reservation_id: request.authorization.reservation_id.clone(),
                worker_generation: self.generation,
                manifest: loaded.manifest.clone(),
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                input_digest: request.input_digest.clone(),
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
        let observed = self.driver.run_neuron_features(&loaded.handle, request);
        self.active_requests
            .remove(&request.authorization.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = match observed {
            Ok(value) => value,
            Err(_) => {
                // The Head may have executed even though the driver failed.
                // Never reuse this generation until independent reconciliation.
                self.poisoned = true;
                return Err(Error::IndeterminateLifecycle);
            }
        };
        if !observed.terminal_observed {
            self.poisoned = true;
        }
        // Resident memory is generation-wide, not only this Head. A driver
        // cannot reduce the original load-time floor by underreporting.
        let selected_resident = observed
            .observed_memory_bytes
            .max(loaded.handle.observed_memory_bytes);
        let total_reported_bytes = selected_resident
            .checked_add(observed.transient_allocation_bytes)
            .and_then(|bytes| bytes.checked_add(other_model_resident_bytes));
        if total_reported_bytes.is_none_or(|bytes| bytes > self.grant.maximum_memory_bytes) {
            self.poisoned = true;
            return Err(Error::ModelCapacity);
        }
        let status = if !observed.terminal_observed {
            ExecutionStatus::Indeterminate
        } else if observed.succeeded {
            if let Err(error) = validate_neuron_feature_output(request, &observed) {
                self.poisoned = true;
                return Err(error);
            }
            ExecutionStatus::Succeeded
        } else {
            ExecutionStatus::Failed
        };
        Ok(NeuronFeatureExecutionObservation {
            request_id: request.authorization.request_id.clone(),
            reservation_id: request.authorization.reservation_id.clone(),
            worker_generation: self.generation,
            manifest: loaded.manifest.clone(),
            encoder_digest: observed.encoder_digest,
            head_digest: observed.head_digest,
            input_digest: request.input_digest.clone(),
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

/// Domain-separated raw-input + scoped feature reference digest.
///
/// This value (not the unscoped source input digest) is used in the existing
/// Worker payload hash. Thus an authorization for one Scope, Principal, lease
/// or Stem generation cannot be reused with another caller-declared binding.
/// Cryptographic authentication of the source and principal remains the
/// independent authority owner's responsibility.
fn scoped_stem_worker_input_digest_v1(bound: &BoundStemNeuronRequestV1) -> Digest32 {
    scoped_stem_worker_input_digest_parts_v1(
        bound.request.input_digest,
        bound.feature_ref_digest,
    )
}

/// Canonical input Scope binding shared by the legacy owned and the borrowed
/// non-authorizing Final-use preflight. It never grants dispatch authority.
fn scoped_stem_worker_input_digest_parts_v1(
    input_digest: Digest32,
    feature_ref_digest: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.infer-worker.scoped-stem-input.v1",
        input_digest.as_array(),
        feature_ref_digest.as_array(),
    ])
}

/// Incremental exact-byte V1 payload hashing on an immutable borrowed Q24
/// slice. This is the SAME wire hash as canonical_neuron_feature_payload_digest
/// and is not a model-execution, signature or current-access proof.
/// Unlike the legacy owned request it never clones the feature Vec.
fn borrowed_stem_worker_payload_digest_v1(
    authorization: &WorkerRequest,
    encoder_digest: Digest32,
    head_digest: Digest32,
    weights_digest: Digest32,
    scoped_input_digest: Digest32,
    features: &[i64],
    expected_output_width: usize,
) -> Digest32 {
    use sha2::Digest as _;
    use sha2::Sha256;

    let mut sha = Sha256::new();
    sha.update(b"hepta.infer-worker.neuron-feature-request.v1");
    sha.update(authorization.model_digest.as_bytes());
    sha.update(encoder_digest.to_string().as_bytes());
    sha.update(head_digest.to_string().as_bytes());
    sha.update(weights_digest.to_string().as_bytes());
    sha.update(scoped_input_digest.to_string().as_bytes());
    sha.update((features.len() as u64).to_be_bytes());
    for value in features {
        sha.update(value.to_be_bytes());
    }
    sha.update((expected_output_width as u64).to_be_bytes());
    Digest32::from_array(sha.finalize().into())
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Dispatch a previously authorized and still-current shared Stem feature
    /// through the real loaded Head driver and typed Neuron receipt boundary.
    ///
    /// This function never invents a lease, reservation, resource grant or
    /// payload digest. `authorization` must be supplied by the independent
    /// inference.control owner and must exactly bind the prepared payload.
    ///
    /// An externally authenticated Stem artifact load, principal/Scope
    /// identity, current generation and final-use authority are REQUIRED
    /// outside this boundary. `StemAccessContextV1` alone is not proof.
    pub(crate) fn run_bound_stem_feature_receipt_v1(
        &mut self,
        now_ms: u64,
        source: &StemFeatureRefV1,
        access: &StemAccessContextV1,
        selected_head: StemHeadBindingV1,
        feature_vector_q24: &[i64],
        authorization: WorkerRequest,
    ) -> Result<BoundStemFeatureExecutionV1, Error> {
        self.validate_current_grant(now_ms)?;
        if access.now_ms != now_ms
            || source.authority_epoch != self.grant.authority_epoch
            || access.authority_epoch != self.grant.authority_epoch
            || source.stem_generation.get() != self.generation
            || access.stem_generation.get() != self.generation
        {
            return Err(Error::InvalidGrant);
        }
        let bound: BoundStemNeuronRequestV1 =
            bind_stem_feature_request_v1(source, access, selected_head, feature_vector_q24)
                .map_err(|_| Error::FeatureContract)?;
        if bound.authority.grants_any() {
            return Err(Error::FeatureContract);
        }
        let model_id = bound.request.model_id.to_string();
        if authorization.request_id != bound.request.request_id.to_string() {
            return Err(Error::FeatureContract);
        }
        // Validate against the *loaded* Head artifact before admitting work,
        // rather than accepting caller-declared Head/manifest matches.
        let loaded = self.models.get(&model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.manifest.weights_digest != bound.request.weights_digest.to_string()
            || authorization.model_digest != loaded.manifest.model_digest
            || authorization.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        // The ordinary Worker request does not carry Scope/Principal fields.
        // Bind them into its existing input-digest slot before comparing the
        // independently issued lease payload. Otherwise a request authorized
        // for Scope A could be replayed under a caller-declared Scope B when
        // the raw input bytes happened to match.
        let scoped_input_digest = scoped_stem_worker_input_digest_v1(&bound);
        let request = NeuronFeatureRequest {
            authorization,
            encoder_digest: bound.request.encoder_digest.to_string(),
            head_digest: bound.request.head_digest.to_string(),
            weights_digest: bound.request.weights_digest.to_string(),
            input_digest: scoped_input_digest.to_string(),
            feature_vector_q24: bound.request.feature_vector_q24,
            expected_output_width: bound.request.expected_output_width,
        };
        validate_request(now_ms, &request.authorization)?;
        validate_neuron_feature_request(&request)?;
        // Do NOT recalculate, overwrite, forge or repair the supplied owner
        // authorization to make it match the request.
        let payload = canonical_neuron_feature_payload_digest(&request);
        if request.authorization.payload_digest != payload
            || request.authorization.lease_payload_digest != payload
        {
            return Err(Error::PayloadMismatch);
        }
        let receipt = self.run_neuron_features_receipt(now_ms, &model_id, request)?;
        if receipt.authority.grants_any() {
            return Err(Error::FeatureContract);
        }
        Ok(BoundStemFeatureExecutionV1 {
            stem_feature_ref_digest: bound.feature_ref_digest,
            scoped_input_digest,
            worker_receipt: receipt,
            final_use_binding_digest: None,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        })
    }
}

/// A complete caller-bound proposal consumed at a signed final-use effect
/// boundary. The caller cannot manufacture `VerifiedUseToken` merely by
/// populating this structure. Every field is revalidated against current
/// loaded Head/ResourceGrant state immediately before effect entry.
pub struct VerifiedStemFeatureDispatchV1<'a> {
    pub source: &'a StemFeatureRefV1,
    pub access: &'a StemAccessContextV1,
    /// Actual read-and-verified CAS bytes for the selected four-role Stem.
    /// Its private fields cannot be manufactured from unverified digests.
    pub verified_artifacts: &'a VerifiedStemCasArtifactsV1,
    /// The same host-owned CAS verifier that made the original byte proof.
    /// An old proof without this live filesystem owner cannot dispatch.
    pub cas_verifier: &'a StemArtifactCasVerifierV1,
    pub selected_head: StemHeadBindingV1,
    pub feature_vector_q24: &'a [i64],
    pub authorization: WorkerRequest,
}

/// Canonical exact source/request payload digest used by the existing Worker
/// path. A final-use issuer must sign the resulting expected binding, not
/// replace a missing or mismatched lease payload.
fn stem_final_use_request_digest_v1(
    authorization: &WorkerRequest,
    grant: &ResourceGrant,
    ref_digest: Digest32,
) -> Digest32 {
    let mut raw = b"hepta.infer-worker.stem-final-use-request.v1".to_vec();
    for field in [
        &authorization.request_id,
        &authorization.reservation_id,
        &authorization.model_digest,
        &authorization.payload_digest,
        &authorization.lease_payload_digest,
        &authorization.reservation_model_digest,
        &grant.grant_id,
        &grant.semantic_digest,
    ] {
        raw.extend_from_slice(&(field.len() as u32).to_be_bytes());
        raw.extend_from_slice(field.as_bytes());
    }
    for field in [
        authorization.maximum_tokens,
        authorization.reservation_maximum_tokens,
    ] {
        raw.extend_from_slice(&field.to_be_bytes());
    }
    for field in [
        authorization.deadline_ms,
        grant.authority_epoch,
        grant.generation,
        grant.expires_at_ms,
    ] {
        raw.extend_from_slice(&field.to_be_bytes());
    }
    raw.push(u8::from(authorization.cancelled));
    raw.extend_from_slice(ref_digest.as_array());
    Digest32::of_bytes(&raw)
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Create a proposal for an **independent** FinalUseAuthority issuer.
    ///
    /// This checks the current runtime grant and loaded Head and binds the
    /// full scoped Stem feature, request identity, reservation, lease bytes,
    /// deadline and exact Worker payload. A proposal grants no authority.
    /// Before effect the worker recomputes all fields from current state.
    pub fn expected_stem_final_use_binding_v1(
        &self,
        now_ms: u64,
        source: &StemFeatureRefV1,
        access: &StemAccessContextV1,
        selected_head: StemHeadBindingV1,
        feature_vector_q24: &[i64],
        authorization: &WorkerRequest,
    ) -> Result<FinalUseBinding, Error> {
        // Preserve the external owned-Head API and its exact V1 signature
        // semantics. Existing callers remain source and binary compatible.
        self.expected_stem_final_use_binding_borrowed_v1(
            now_ms,
            source,
            access,
            &selected_head,
            feature_vector_q24,
            authorization,
        )
    }

    /// Inner owner-only borrowed binding used by 32 bounded Cell Head
    /// proposals. The head's strings and identity never need to be cloned
    /// merely to validate or sign a non-authorizing batch plan.
    ///
    /// Every current Scope/Principal/Epoch/Generation/Lease/Head/Resource/
    /// CAS input check remains identical to the owned public entry.
    pub(crate) fn expected_stem_final_use_binding_borrowed_v1(
        &self,
        now_ms: u64,
        source: &StemFeatureRefV1,
        access: &StemAccessContextV1,
        selected_head: &StemHeadBindingV1,
        feature_vector_q24: &[i64],
        authorization: &WorkerRequest,
    ) -> Result<FinalUseBinding, Error> {
        self.validate_current_grant(now_ms)?;
        if access.now_ms != now_ms
            || source.authority_epoch != self.grant.authority_epoch
            || access.authority_epoch != self.grant.authority_epoch
            || source.stem_generation.get() != self.generation
            || access.stem_generation.get() != self.generation
        {
            return Err(Error::InvalidGrant);
        }
        // Borrow the exact same source/Head/lease-checked Q24 vector without
        // allocating a per-Cell Vec. The pure Stem contract still rehashes
        // arbitrary caller slices and rejects changed Q24 content.
        let bound = borrow_stem_feature_request_v1(
            source,
            access,
            selected_head,
            feature_vector_q24,
        )
        .map_err(|_| Error::FeatureContract)?;
        if bound.authority().grants_any()
            || authorization.request_id.as_str() != selected_head.request_id.as_str()
        {
            return Err(Error::FeatureContract);
        }
        let head_id = selected_head.head_model_id.as_str();
        let loaded = self.models.get(&head_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.manifest.weights_digest != selected_head.head_weights_digest.to_string()
            || authorization.model_digest != loaded.manifest.model_digest
            || authorization.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if authorization.maximum_tokens > loaded.manifest.maximum_tokens
            || authorization.maximum_tokens > authorization.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        validate_request(now_ms, authorization)?;
        if authorization.cancelled {
            return Err(Error::FinalUseDenied);
        }
        // The Stem borrow contract checked 1..=512 Q24 values, the same
        // +/-8Q24 limit, selected Head width and every frozen identity. Only
        // the legacy materialization is skipped; no approval is invented.
        let feature_ref_digest = bound.feature_ref_digest();
        let scoped_input_digest = scoped_stem_worker_input_digest_parts_v1(
            source.input_digest,
            feature_ref_digest,
        );
        let payload = borrowed_stem_worker_payload_digest_v1(
            authorization,
            selected_head.required_encoder_digest,
            selected_head.head_digest,
            selected_head.head_weights_digest,
            scoped_input_digest,
            bound.feature_vector_q24(),
            selected_head.expected_output_width,
        );
        let payload_hex = payload.to_string();
        if authorization.payload_digest != payload_hex
            || authorization.lease_payload_digest != payload_hex
        {
            return Err(Error::PayloadMismatch);
        }
        Ok(FinalUseBinding {
            subject_id: source.principal_id.to_string(),
            destination_id: format!("neuron.head:{head_id}"),
            request_sha256: stem_final_use_request_digest_v1(
                authorization,
                &self.grant,
                feature_ref_digest,
            )
            .into_array(),
            scope_sha256: feature_ref_digest.into_array(),
            payload_sha256: payload.into_array(),
        })
    }

    /// Single-use independently verified entry point for the shared Stem.
    ///
    /// The `trusted_authority` MUST come from a protected host/pinned
    /// issuer composition; passing an attacker-created authority is not
    /// authentication. `with_verified_effect` verifies token ownership
    /// (same authority instance), the exact binding, current revocation and
    /// expiry, and holds an active effect fence across the Worker call.
    /// No signing key or grant issuance exists in this Worker.
    pub fn run_verified_stem_feature_receipt_v1(
        &mut self,
        trusted_authority: &FinalUseAuthority,
        verified_use: VerifiedUseToken,
        now_ms: u64,
        proposed: VerifiedStemFeatureDispatchV1<'_>,
    ) -> Result<BoundStemFeatureExecutionV1, Error> {
        let VerifiedStemFeatureDispatchV1 {
            source,
            access,
            verified_artifacts,
            cas_verifier,
            selected_head,
            feature_vector_q24,
            authorization,
        } = proposed;
        // Fail closed before claiming the final-use effect: a signed digest
        // declaration without actual bytes in the protected host CAS is not
        // sufficient to dispatch even an otherwise valid Head request.
        if !verified_artifacts.matches_source(source)
            || verified_artifacts.authority().grants_any()
            || cas_verifier
                .verify_pinned_current(source, verified_artifacts)
                .is_err()
        {
            return Err(Error::FeatureContract);
        }
        let binding = self.expected_stem_final_use_binding_v1(
            now_ms,
            source,
            access,
            selected_head.clone(),
            feature_vector_q24,
            &authorization,
        )?;
        if verified_use.claimed_authority_epoch() != self.grant.authority_epoch {
            return Err(Error::FinalUseDenied);
        }
        let binding_digest =
            Digest32::of_bytes(&serde_json::to_vec(&binding).map_err(|_| Error::FinalUseDenied)?);
        let outcome = trusted_authority
            .with_verified_effect(verified_use, &binding, || {
                // Recheck the pinned four-role CAS tuple *inside* the real
                // one-use effect fence. This is metadata-only here because
                // verify_selected already hashed every CAS byte at admission.
                cas_verifier
                    .verify_pinned_current(source, verified_artifacts)
                    .map_err(|_| Error::FeatureContract)?;
                self.run_bound_stem_feature_receipt_v1(
                    now_ms,
                    source,
                    access,
                    selected_head,
                    feature_vector_q24,
                    authorization,
                )
            })
            .map_err(|_| Error::FinalUseDenied)?;
        let mut receipt = outcome?;
        receipt.final_use_binding_digest = Some(binding_digest);
        Ok(receipt)
    }
}

impl<D: ModelDriver + NeuronFeatureDriver> InferenceWorker<D> {
    /// Execute the worker path and project the observed result into the
    /// inference-control-owned typed receipt.
    pub(crate) fn run_neuron_features_receipt(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: NeuronFeatureRequest,
    ) -> Result<NeuronFeatureReceiptV1, Error> {
        // Borrow for execution, then move the original Q24 vector into V1 receipt.
        let observed = self.run_neuron_features_borrowed(now_ms, model_id, &request)?;
        let generation =
            Generation::new(observed.worker_generation).map_err(|_| Error::FeatureContract)?;
        let control_request = NeuronFeatureRequestV1 {
            request_id: StableId::new(request.authorization.request_id)
                .map_err(|_| Error::FeatureContract)?,
            generation,
            model_id: StableId::new(observed.manifest.model_id.clone())
                .map_err(|_| Error::FeatureContract)?,
            encoder_digest: parse_digest32(&request.encoder_digest)?,
            head_digest: parse_digest32(&request.head_digest)?,
            weights_digest: parse_digest32(&request.weights_digest)?,
            input_digest: parse_digest32(&request.input_digest)?,
            feature_vector_q24: request.feature_vector_q24,
            expected_output_width: request.expected_output_width,
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
        let receipt = build_neuron_feature_receipt_v1(
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
        .map_err(|_| Error::FeatureContract);
        if receipt.is_err() {
            // The driver may have physically executed before its terminal
            // envelope was rejected. Do not reuse the same generation.
            self.poisoned = true;
        }
        receipt
    }
}


/// Reuse the ORIGINAL registered FinalUse guarded-effect boundary for every
/// member of one proposed Stem batch. This stays in the original Worker
/// source path listed by CALLERS.toml; no alternate authority method exists.
///
/// Each independently claimed, uncloneable token must pass the original
/// signer-instance, binding, revocation, deadline and epoch checks. Existing
/// active-effect guards nest synchronously and deny concurrent revocation
/// changes until the innermost callback returns. Failure at any member means
/// the callback has never started; claimed nonce journal entries are retained.
#[cfg(test)]
fn with_verified_stem_batch_tokens_v1<'a, T>(
    authority: &'a FinalUseAuthority,
    signed_members: Vec<(VerifiedUseToken, FinalUseBinding)>,
    effect: Box<dyn FnOnce() -> Result<T, Error> + 'a>,
) -> Result<T, Error> {
    let mut fenced = effect;
    for (token, binding) in signed_members.into_iter().rev() {
        let next = fenced;
        fenced = Box::new(move || {
            authority
                .with_verified_effect(token, &binding, next)
                .map_err(|_| Error::FinalUseDenied)?
        });
    }
    fenced()
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

// Batch planning is non-authorizing and has no physical batch driver.
// Only the existing signed Final-use Worker may later perform an effect.
#[path = "model_worker_stem_batch.rs"]
mod stem_batch;
pub use stem_batch::NonAuthorizingStemBatchPlanV1;
pub use stem_batch::StemBatchMemberProposalV1;
pub use stem_batch::StemBatchProposalV1;

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
