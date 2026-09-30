//! Experimental local-model execution boundary.
//!
//! This module is compiled only with `experimental-local-model`. It provides a
//! signed-grant verifier, a live monotonic authority port, verified model/input
//! types, aggregate resource accounting and a durable run adapter over the
//! existing inference.control native journal. It does not establish a real
//! hardware driver or production qualification by itself.

use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;

#[path = "experimental_local/authority.rs"]
mod authority;
#[path = "experimental_local/driver.rs"]
mod driver;
#[path = "experimental_local/durable.rs"]
mod durable;
#[path = "experimental_local/hardened.rs"]
mod hardened;
#[path = "experimental_local/live_authority.rs"]
mod live_authority;
#[path = "experimental_local/resources.rs"]
mod resources;

pub use authority::LocalModelManifest;
pub use authority::ResourceGrantClaims;
pub use authority::ResourceGrantVerifier;
pub use authority::SignedResourceGrant;
pub use authority::SystemTrustedClock;
pub use authority::TrustedClock;
pub use authority::TrustedDeadline;
pub use authority::TrustedRevocationFrontier;
pub use authority::VerifiedInput;
pub use authority::VerifiedModelManifest;
pub use authority::VerifiedResourceGrant;
pub use driver::AttestedModelHandle;
pub use driver::DriverInterruptReason;
pub use driver::DriverLoadObservation;
pub use driver::DriverReconciliation;
pub use driver::DriverRunObservation;
pub use driver::DriverTerminalStatus;
pub use driver::DriverUnloadObservation;
pub use driver::LocalModelDriver;
pub use driver::TrustedReleaseObservation;
pub use driver::TrustedResourceObservation;
pub use driver::TrustedResourceObserver;
pub use durable::LocalRunAdmission;
pub use durable::LocalRunResult;
pub use durable::LocalRunStatus;
pub use hardened::DurableLocalModelWorker;
pub use live_authority::AUTHORITY_SNAPSHOT_SCHEMA_VERSION;
pub use live_authority::DEFAULT_AUTHORITY_MAX_AGE_MS;
pub use live_authority::TrustedAuthorityProvider;
pub use live_authority::TrustedAuthoritySnapshot;
pub use resources::ModelLifecycle;
pub use resources::ResourceManager;
pub use resources::ResourceSnapshot;

pub type LocalFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, LocalWorkerError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalWorkerError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidGrant(&'static str),
    InvalidManifest(&'static str),
    InvalidInput(&'static str),
    InvalidObservation(&'static str),
    InvalidTransition(&'static str),
    GrantExpired,
    GrantNotYetValid,
    GrantRevoked,
    StaleAuthorityFrontier,
    InvalidSignature,
    DeadlineExpired,
    CapacityExceeded,
    GenerationFenced(String),
    ResourceStatePoisoned,
    ArithmeticOverflow,
    Driver(String),
    Observer(String),
    Authority(String),
    Control(String),
}

impl fmt::Display for LocalWorkerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LocalWorkerError {}

pub(super) fn validate_identity(
    value: &str,
    field: &'static str,
) -> Result<(), LocalWorkerError> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(LocalWorkerError::InvalidIdentity(field));
    }
    Ok(())
}

pub(super) fn validate_digest(
    value: &str,
    field: &'static str,
) -> Result<(), LocalWorkerError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(LocalWorkerError::InvalidDigest(field));
    }
    Ok(())
}

#[must_use]
pub(super) fn digest(bytes: &[u8]) -> String {
    use sha2::Digest;
    format!("{:x}", sha2::Sha256::digest(bytes))
}

#[cfg(test)]
#[path = "experimental_local_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "experimental_local_hardening_tests.rs"]
mod hardening_tests;
