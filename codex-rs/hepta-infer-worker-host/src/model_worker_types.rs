//! Unverified policy and observation types for the experimental local driver.
//! These values do not grant model, device, quota, or final-use authority.

use std::error::Error as StdError;
use std::fmt;

pub(super) const MAX_MODELS: usize = 8;
pub(super) const MAX_ACTIVE_REQUESTS: usize = 256;
const MAX_TOKENS: u32 = 1_000_000;

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
    /// Resident upper bound reserved before calling the physical loader.
    pub maximum_resident_bytes: u64,
}

/// Unverified experimental policy, not a signature-verified resource grant.
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
    pub maximum_kv_bytes: u64,
    pub maximum_transient_bytes: u64,
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
    /// None is unknown, not an observation of zero consumption.
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
    ResourceAccounting,
    GenerationFenced,
    CleanupRequired,
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

pub(super) fn validate_manifest(value: &ModelManifest) -> Result<(), Error> {
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
    if value.maximum_tokens == 0
        || value.maximum_tokens > MAX_TOKENS
        || value.maximum_resident_bytes == 0
    {
        return Err(Error::InvalidManifest);
    }
    Ok(())
}

pub(super) fn validate_grant(now_ms: u64, value: &ResourceGrant) -> Result<(), Error> {
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

pub(super) fn validate_request(now_ms: u64, value: &WorkerRequest) -> Result<(), Error> {
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

pub(super) fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
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

pub(super) fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
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
