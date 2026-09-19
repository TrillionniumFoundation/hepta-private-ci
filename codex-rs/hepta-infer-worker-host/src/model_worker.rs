#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use sha2::Digest;
use sha2::Sha256;

const MAX_MODELS: usize = 8;
const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_TOKENS: u32 = 1_000_000;
const MAX_INPUT_BYTES: usize = 1024 * 1024;

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

/// Raw grant fields are not an authenticated capability by themselves.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GrantVerification {
    /// Only valid when the caller and worker share the same trusted process
    /// boundary and the caller is the authority owner.
    TrustedInProcess,
    /// Evidence emitted by an external grant authority/verifier. The worker
    /// does not invent or upgrade this evidence.
    Authenticated {
        authority_id: String,
        evidence_digest: String,
        /// Exact worker subject authenticated by the verifier. The worker
        /// constructor must match this value before accepting the capability.
        worker_id: String,
    },
}

trait ResourceGrantVerifier {
    fn verify(
        &self,
        now_ms: u64,
        grant: &ResourceGrant,
    ) -> Result<GrantVerification, Error>;
}

/// Concrete production-capable verifier for creating one local worker
/// generation. It reuses the kernel final-use authority instead of defining a
/// second signing system. The signed capability binds the complete resource
/// grant and exact worker identity/generation. Verification consumes the
/// final-use nonce, so replay cannot create another worker generation.
///
/// This is an admission snapshot, not a live revocation feed. The product host
/// remains responsible for fencing the resulting worker generation when its
/// resource authority changes.
struct FinalUseResourceGrantVerifier<'a> {
    authority: &'a FinalUseAuthority,
    signed: &'a SignedFinalUseGrant,
    worker_id: String,
}

impl<'a> FinalUseResourceGrantVerifier<'a> {
    fn new(
        authority: &'a FinalUseAuthority,
        signed: &'a SignedFinalUseGrant,
        worker_id: String,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        Ok(Self {
            authority,
            signed,
            worker_id,
        })
    }
}

impl ResourceGrantVerifier for FinalUseResourceGrantVerifier<'_> {
    fn verify(
        &self,
        _now_ms: u64,
        grant: &ResourceGrant,
    ) -> Result<GrantVerification, Error> {
        if self.signed.grant.authority_epoch != grant.authority_epoch {
            return Err(Error::InvalidGrant);
        }
        let binding = resource_grant_final_use_binding(&self.worker_id, grant)?;
        let evidence = serde_json::to_vec(self.signed).map_err(|_| Error::InvalidGrant)?;
        let evidence_digest = sha256(&evidence);
        let authority_id = self.signed.grant.signer_id.clone();
        let token = self
            .authority
            .claim(self.signed, &binding)
            .map_err(map_final_use_error)?;
        self.authority
            .with_verified_use(token, &binding, || GrantVerification::Authenticated {
                authority_id,
                evidence_digest,
                worker_id: self.worker_id.clone(),
            })
            .map_err(map_final_use_error)
    }
}

/// Canonical kernel final-use binding for local resource-grant admission.
pub fn resource_grant_final_use_binding(
    worker_id: &str,
    grant: &ResourceGrant,
) -> Result<FinalUseBinding, Error> {
    validate_identity(worker_id, "worker")?;
    validate_identity(&grant.grant_id, "grant")?;
    validate_digest(&grant.semantic_digest, "grant semantic")?;
    if grant.revoked
        || grant.authority_epoch == 0
        || grant.generation == 0
        || grant.expires_at_ms == 0
        || grant.maximum_models == 0
        || grant.maximum_active_requests == 0
        || grant.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidGrant);
    }
    let payload = serde_json::to_vec(&(
        "hepta.local-resource-grant.v1",
        &grant.grant_id,
        grant.authority_epoch,
        grant.generation,
        grant.expires_at_ms,
        grant.revoked,
        grant.maximum_models,
        grant.maximum_active_requests,
        grant.maximum_memory_bytes,
        &grant.semantic_digest,
    ))
    .map_err(|_| Error::InvalidGrant)?;
    let payload_sha256 = sha256_array(&payload);
    let request_sha256 = sha256_array(
        &serde_json::to_vec(&(
            "hepta.local-resource-grant.request.v1",
            worker_id,
            grant.generation,
            payload_sha256,
        ))
        .map_err(|_| Error::InvalidGrant)?,
    );
    let scope_sha256 = sha256_array(
        &serde_json::to_vec(&(
            "hepta.local-resource-grant.scope.v1",
            worker_id,
            grant.generation,
            &grant.semantic_digest,
        ))
        .map_err(|_| Error::InvalidGrant)?,
    );
    Ok(FinalUseBinding {
        subject_id: worker_id.to_string(),
        destination_id: "resource:local-model-worker".to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

/// Move-only verified capability. A successful authority claim may construct
/// at most one worker generation; callers cannot clone the post-claim proof
/// into a second worker instance.
#[derive(Debug, Eq, PartialEq)]
pub struct VerifiedResourceGrant {
    grant: ResourceGrant,
    verification: GrantVerification,
}

impl VerifiedResourceGrant {
    pub(crate) fn trusted_in_process(now_ms: u64, grant: ResourceGrant) -> Result<Self, Error> {
        validate_grant(now_ms, &grant)?;
        Ok(Self {
            grant,
            verification: GrantVerification::TrustedInProcess,
        })
    }

    fn verify_with<V: ResourceGrantVerifier>(
        now_ms: u64,
        grant: ResourceGrant,
        verifier: &V,
    ) -> Result<Self, Error> {
        validate_grant(now_ms, &grant)?;
        let verification = verifier.verify(now_ms, &grant)?;
        match &verification {
            GrantVerification::Authenticated {
                authority_id,
                evidence_digest,
                worker_id,
            } => {
                validate_identity(authority_id, "grant authority")?;
                validate_digest(evidence_digest, "grant evidence")?;
                validate_identity(worker_id, "grant worker")?;
            }
            GrantVerification::TrustedInProcess => {
                return Err(Error::InvalidGrant);
            }
        }
        Ok(Self {
            grant,
            verification,
        })
    }

    /// Authenticate one exact local worker generation through the kernel
    /// final-use authority. This is the only public external verification path;
    /// callers cannot supply an arbitrary verifier implementation.
    pub fn verify_final_use(
        now_ms: u64,
        grant: ResourceGrant,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        worker_id: String,
    ) -> Result<Self, Error> {
        let verifier = FinalUseResourceGrantVerifier::new(authority, signed, worker_id)?;
        Self::verify_with(now_ms, grant, &verifier)
    }

    pub fn grant(&self) -> &ResourceGrant {
        &self.grant
    }

    pub fn verification(&self) -> &GrantVerification {
        &self.verification
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerRequest {
    pub request_id: String,
    pub reservation_id: String,
    pub model_digest: String,
    /// Exact UTF-8 model input presented to the local runtime.
    pub input: String,
    /// SHA-256 of `input`; this is also the lease-bound payload digest.
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
    /// Memory the runtime actually reserved before declaring the model loaded.
    pub reserved_memory_bytes: u64,
    /// Resident/device memory observed at the completed load boundary.
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub output_digest: Option<String>,
    /// None means usage was not durably observed; it must never be coerced to zero.
    pub consumed_tokens: Option<u32>,
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
    /// None means provider/runtime usage is still unknown.
    pub consumed_tokens: Option<u32>,
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
    GrantAuthorityUnavailable,
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
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub trait ModelDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
        maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error>;
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
        response_timeout: Duration,
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
    grant_verification: GrantVerification,
    driver: D,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
}

impl<D: ModelDriver> InferenceWorker<D> {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        generation: u64,
        grant: VerifiedResourceGrant,
        driver: D,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        validate_grant(now_ms, grant.grant())?;
        if generation == 0 || generation != grant.grant().generation {
            return Err(Error::InvalidGrant);
        }
        if let GrantVerification::Authenticated {
            worker_id: authenticated_worker,
            ..
        } = grant.verification()
        {
            if authenticated_worker != &worker_id {
                return Err(Error::InvalidGrant);
            }
        }
        let VerifiedResourceGrant {
            grant,
            verification: grant_verification,
        } = grant;
        Ok(Self {
            worker_id,
            generation,
            grant,
            grant_verification,
            driver,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
        })
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    pub fn grant_verification(&self) -> &GrantVerification {
        &self.grant_verification
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
        let reserved_before_load = self.models.values().try_fold(0_u64, |total, loaded| {
            total
                .checked_add(loaded.handle.reserved_memory_bytes)
                .ok_or(Error::ArithmeticOverflow)
        })?;
        let remaining_memory_bytes = self
            .grant
            .maximum_memory_bytes
            .checked_sub(reserved_before_load)
            .ok_or(Error::ModelCapacity)?;
        if remaining_memory_bytes == 0 {
            return Err(Error::ModelCapacity);
        }
        let handle = self
            .driver
            .load(&manifest, &self.grant, remaining_memory_bytes)?;
        validate_identity(&handle.opaque_id, "model handle")?;
        if handle.reserved_memory_bytes == 0
            || handle.reserved_memory_bytes > remaining_memory_bytes
            || handle.observed_memory_bytes > handle.reserved_memory_bytes
        {
            self.driver.unload(handle)?;
            return Err(Error::ModelCapacity);
        }
        let reserved_after_load = reserved_before_load
            .checked_add(handle.reserved_memory_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        if reserved_after_load > self.grant.maximum_memory_bytes {
            self.driver.unload(handle)?;
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
                consumed_tokens: Some(0),
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
        let response_timeout = Duration::from_millis(
            request
                .deadline_ms
                .checked_sub(now_ms)
                .ok_or(Error::DeadlineExpired)?,
        );
        let observed = self
            .driver
            .run(&loaded.handle, &request, response_timeout);
        self.active_requests.remove(&request.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        let observed = observed?;
        if observed.consumed_tokens.is_some_and(|tokens| {
            tokens > request.maximum_tokens || tokens > request.reservation_maximum_tokens
        }) {
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
        let loaded = self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        self.driver.unload(loaded.handle)?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
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
    if value.input.is_empty() || value.input.len() > MAX_INPUT_BYTES {
        return Err(Error::PayloadMismatch);
    }
    if sha256(value.input.as_bytes()) != value.payload_digest {
        return Err(Error::PayloadMismatch);
    }
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

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn sha256_array(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

fn map_final_use_error(error: FinalUseError) -> Error {
    match error {
        FinalUseError::Unavailable
        | FinalUseError::UnsafeStateDirectory
        | FinalUseError::StateLocked => Error::GrantAuthorityUnavailable,
        _ => Error::InvalidGrant,
    }
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

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
