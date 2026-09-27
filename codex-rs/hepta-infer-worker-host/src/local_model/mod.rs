//! Experimental local-model execution.
//!
//! The module is available only with `experimental-local-model`. It verifies
//! signed resource authority, consumes real input bytes, uses an independent
//! host resource observer, accounts aggregate resources, and reuses the
//! `DurableInferenceControl` journal for assign-before-effect/no-replay
//! semantics. It is not a production-activation claim.

mod grant;
mod resource;
mod worker;

pub use grant::*;
pub use resource::*;
pub use worker::*;

use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use sha2::{Digest, Sha256};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

pub(crate) const MAX_IDENTITY_BYTES: usize = 128;
pub(crate) const MAX_INPUT_BYTES: usize = 4 * 1024 * 1024;
pub(crate) const MAX_TOKENS: u32 = 1_000_000;
pub(crate) const MAX_DEADLINE_HORIZON_MS: u64 = 24 * 60 * 60 * 1_000;

pub type DriverFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, DriverError>> + Send + 'a>>;
pub type ObserverFuture<'a> =
    Pin<Box<dyn Future<Output = Result<HostResourceObservation, ObserverError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGrant(&'static str),
    InvalidManifest(&'static str),
    InvalidDeadline,
    Signature,
    PayloadMismatch,
    ModelNotLoaded,
    ModelAlreadyLoaded,
    ModelBusy,
    ResourceCapacity,
    GenerationFenced,
    RepairRequired,
    Driver(String),
    Observer(String),
    Control(String),
    LockPoisoned,
    ArithmeticOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

impl From<codex_hepta_infer_core::durable_control::Error> for Error {
    fn from(value: codex_hepta_infer_core::durable_control::Error) -> Self {
        Self::Control(value.to_string())
    }
}

impl From<DriverError> for Error {
    fn from(value: DriverError) -> Self {
        Self::Driver(value.message)
    }
}

impl From<ObserverError> for Error {
    fn from(value: ObserverError) -> Self {
        Self::Observer(value.message)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct OperationId(String);

impl OperationId {
    pub fn parse(value: String) -> Result<Self, Error> {
        validate_identity(&value, "operation")?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug)]
pub struct VerifiedInput {
    bytes: Arc<[u8]>,
    digest: String,
}

impl VerifiedInput {
    pub fn verify(bytes: Vec<u8>, expected_digest: &str) -> Result<Self, Error> {
        if bytes.is_empty() || bytes.len() > MAX_INPUT_BYTES {
            return Err(Error::PayloadMismatch);
        }
        validate_digest(expected_digest, "input")?;
        let observed = digest(&bytes);
        if observed != expected_digest {
            return Err(Error::PayloadMismatch);
        }
        Ok(Self {
            bytes: Arc::from(bytes),
            digest: observed,
        })
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn digest(&self) -> &str {
        &self.digest
    }
}

#[derive(Clone, Debug)]
pub struct TrustedDeadline {
    pub(crate) absolute_ms: u64,
    pub(crate) instant: Instant,
}

impl TrustedDeadline {
    pub fn absolute_ms(&self) -> u64 {
        self.absolute_ms
    }

    pub fn instant(&self) -> Instant {
        self.instant
    }
}

pub trait TrustedClock: Send + Sync {
    fn now_ms(&self) -> Result<u64, Error>;
    fn instant_for(&self, deadline_ms: u64) -> Result<Instant, Error>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SystemTrustedClock;

impl TrustedClock for SystemTrustedClock {
    fn now_ms(&self) -> Result<u64, Error> {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::InvalidDeadline)?
            .as_millis();
        u64::try_from(millis).map_err(|_| Error::ArithmeticOverflow)
    }

    fn instant_for(&self, deadline_ms: u64) -> Result<Instant, Error> {
        let now_ms = self.now_ms()?;
        let remaining = deadline_ms
            .checked_sub(now_ms)
            .ok_or(Error::InvalidDeadline)?;
        Ok(Instant::now() + Duration::from_millis(remaining))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverError {
    message: String,
}

impl DriverError {
    pub fn new(message: impl Into<String>) -> Self {
        let mut message = message.into();
        message.truncate(1_024);
        Self { message }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObserverError {
    message: String,
}

impl ObserverError {
    pub fn new(message: impl Into<String>) -> Self {
        let mut message = message.into();
        message.truncate(1_024);
        Self { message }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadEvidence {
    pub handle_id: String,
    pub model_digest: String,
    pub weights_digest: String,
    pub runtime_digest: String,
    pub device_id: String,
    pub device_digest: String,
    pub observed_weight_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DriverTerminalStatus {
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverRunEvidence {
    pub terminal_observed: bool,
    pub status: Option<DriverTerminalStatus>,
    pub output_digest: Option<String>,
    pub consumed_tokens: Option<u32>,
    pub observed_model_bytes: u64,
    pub observed_kv_memory_bytes: u64,
    pub transient_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverUnloadEvidence {
    pub terminal_observed: bool,
    pub released_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HostResourceObservation {
    pub present: bool,
    pub handle_id: String,
    pub worker_generation: u64,
    pub device_id: String,
    pub device_digest: String,
    pub model_memory_bytes: u64,
    pub kv_memory_bytes: u64,
    pub transient_memory_bytes: u64,
}

#[derive(Clone, Debug)]
pub struct AttestedModelHandle {
    pub(crate) handle_id: String,
    pub(crate) model_id: String,
    pub(crate) model_digest: String,
    pub(crate) weights_digest: String,
    pub(crate) runtime_digest: String,
    pub(crate) device_id: String,
    pub(crate) device_digest: String,
    pub(crate) observed_weight_bytes: u64,
}

impl AttestedModelHandle {
    pub fn handle_id(&self) -> &str {
        &self.handle_id
    }

    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    pub fn model_digest(&self) -> &str {
        &self.model_digest
    }

    pub fn device_id(&self) -> &str {
        &self.device_id
    }

    pub fn device_digest(&self) -> &str {
        &self.device_digest
    }
}

pub trait LocalModelDriver: Send + Sync {
    fn load<'a>(
        &'a self,
        manifest: &'a VerifiedModelManifest,
        grant: &'a VerifiedResourceGrant,
    ) -> DriverFuture<'a, DriverLoadEvidence>;

    fn run<'a>(
        &'a self,
        operation_id: &'a OperationId,
        handle: &'a AttestedModelHandle,
        input: &'a VerifiedInput,
        cancellation: &'a CancellationToken,
        deadline: &'a TrustedDeadline,
    ) -> DriverFuture<'a, DriverRunEvidence>;

    fn inspect<'a>(
        &'a self,
        operation_id: &'a OperationId,
    ) -> DriverFuture<'a, Option<DriverRunEvidence>>;

    fn unload<'a>(
        &'a self,
        handle: &'a AttestedModelHandle,
    ) -> DriverFuture<'a, DriverUnloadEvidence>;
}

pub trait TrustedResourceObserver: Send + Sync {
    fn observe<'a>(
        &'a self,
        handle_id: &'a str,
        operation_id: Option<&'a OperationId>,
    ) -> ObserverFuture<'a>;
}

pub(crate) fn validate_identity(
    value: &str,
    field: &'static str,
) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > MAX_IDENTITY_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

pub(crate) fn validate_digest(
    value: &str,
    field: &'static str,
) -> Result<(), Error> {
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

pub(crate) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
