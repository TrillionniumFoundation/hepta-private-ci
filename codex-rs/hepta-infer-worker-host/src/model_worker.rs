#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const MAX_MODELS: usize = 8;
const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_TOKENS: u32 = 1_000_000;
const MAX_PROMPT_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelManifest {
    pub model_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    /// Digest of the launcher/sandbox evidence consumed by the local runtime.
    /// It is deliberately distinct from device identity so a GPU identity can
    /// never be misreported as proof of OS/process isolation.
    pub isolation_digest: String,
    pub maximum_tokens: u32,
}

/// Capacity policy proposed by the authority owner. This value is serializable
/// for transport/storage, but it is not itself authority and cannot construct an
/// `InferenceWorker` until a kernel `FinalUseAuthority` verifies a signed,
/// single-use binding for the exact worker and grant semantics.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
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

/// Non-serializable proof that the raw resource grant crossed the kernel-owned
/// final-use verifier. Keeping the constructor private prevents a future IPC
/// adapter from accidentally treating parsed JSON as an admitted capability.
#[derive(Clone, Debug)]
pub struct VerifiedResourceGrant {
    grant: ResourceGrant,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRequest {
    pub request_id: String,
    pub reservation_id: String,
    pub model_digest: String,
    pub payload_digest: String,
    /// Exact local-model input. `payload_digest` is the SHA-256 of these UTF-8
    /// bytes; a digest-only request can never reach the physical runtime.
    pub prompt: String,
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
    GrantAuthorityInvalid,
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
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Physical local-model boundary. The exact verified resource grant is supplied
/// before load and run so a runtime can reserve device/memory resources before
/// touching weights or dispatching kernels rather than reporting an overrun only
/// after the fact.
pub trait ModelDriver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error>;
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
        grant: &ResourceGrant,
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
}

/// Canonical kernel final-use binding for one local resource grant. The signed
/// scope commits to every capacity/lifetime field; the semantic digest is bound
/// as payload bytes and cannot be swapped after signature verification.
pub fn resource_grant_binding(
    worker_id: &str,
    grant: &ResourceGrant,
) -> Result<FinalUseBinding, Error> {
    validate_identity(worker_id, "worker")?;
    validate_identity(&grant.grant_id, "grant")?;
    validate_digest(&grant.semantic_digest, "grant semantic")?;
    let semantic = parse_digest32(&grant.semantic_digest, "grant semantic")?;
    let request_sha256 = sha256_bytes(grant.grant_id.as_bytes());
    let mut scope = Sha256::new();
    scope.update(b"hepta.inference.worker.resource-grant.v1\0");
    scope.update(grant.grant_id.as_bytes());
    scope.update([0]);
    scope.update(grant.authority_epoch.to_le_bytes());
    scope.update(grant.generation.to_le_bytes());
    scope.update(grant.expires_at_ms.to_le_bytes());
    scope.update([u8::from(grant.revoked)]);
    scope.update((grant.maximum_models as u64).to_le_bytes());
    scope.update((grant.maximum_active_requests as u64).to_le_bytes());
    scope.update(grant.maximum_memory_bytes.to_le_bytes());
    scope.update(semantic);
    Ok(FinalUseBinding {
        subject_id: worker_id.to_string(),
        destination_id: "inference.worker/local-model".to_string(),
        request_sha256,
        scope_sha256: scope.finalize().into(),
        payload_sha256: semantic,
    })
}

/// Verify a serialized resource grant through the existing kernel authority and
/// return a non-serializable capability accepted by `InferenceWorker::new`.
pub fn verify_resource_grant(
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    now_ms: u64,
    worker_id: &str,
    grant: ResourceGrant,
) -> Result<VerifiedResourceGrant, Error> {
    validate_grant(now_ms, &grant)?;
    if signed.grant.authority_epoch != grant.authority_epoch
        || signed.grant.grant_id != grant.grant_id
    {
        return Err(Error::GrantAuthorityInvalid);
    }
    let binding = resource_grant_binding(worker_id, &grant)?;
    let token = authority
        .claim(signed, &binding)
        .map_err(|_| Error::GrantAuthorityInvalid)?;
    authority
        .with_verified_use(token, &binding, || VerifiedResourceGrant { grant })
        .map_err(|_| Error::GrantAuthorityInvalid)
}

impl<D: ModelDriver> InferenceWorker<D> {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        generation: u64,
        verified_grant: VerifiedResourceGrant,
        driver: D,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        let grant = verified_grant.grant;
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
        let handle = self.driver.load(&manifest, &self.grant)?;
        validate_identity(&handle.opaque_id, "model handle")?;
        if handle.observed_memory_bytes > self.grant.maximum_memory_bytes {
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
        if request.payload_digest != request.lease_payload_digest
            || request.payload_digest != sha256_hex(request.prompt.as_bytes())
        {
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
        let observed = self.driver.run(&loaded.handle, &request, &self.grant);
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

    /// Resource cleanup is intentionally permitted after expiry or revocation.
    /// A stale authority may never start work, but losing authority must not pin
    /// accelerator memory indefinitely.
    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
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
        (&value.isolation_digest, "isolation"),
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
    if value.prompt.is_empty() || value.prompt.len() > MAX_PROMPT_BYTES {
        return Err(Error::PayloadMismatch);
    }
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

fn parse_digest32(value: &str, field: &'static str) -> Result<[u8; 32], Error> {
    validate_digest(value, field)?;
    let mut result = [0_u8; 32];
    for (index, chunk) in value.as_bytes().chunks_exact(2).enumerate() {
        result[index] = (hex_nibble(chunk[0]).ok_or(Error::InvalidDigest(field))? << 4)
            | hex_nibble(chunk[1]).ok_or(Error::InvalidDigest(field))?;
    }
    Ok(result)
}

fn hex_nibble(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

fn sha256_bytes(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = sha256_bytes(bytes);
    let mut encoded = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}

#[cfg(test)]
impl VerifiedResourceGrant {
    fn test_only(now_ms: u64, grant: ResourceGrant) -> Result<Self, Error> {
        validate_grant(now_ms, &grant)?;
        Ok(Self { grant })
    }
}

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
