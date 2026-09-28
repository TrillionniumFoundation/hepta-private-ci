//! Experimental local-model execution boundary.
//!
//! This module is available only with `local-model-experimental`. It is built
//! around non-constructible verified inputs, aggregate resource accounting and
//! the existing `inference.control` journal. It does not itself establish real
//! hardware, artifact, issuer or target-host qualification.

mod authority;
mod coordinator;
mod driver;
mod resources;

pub use authority::ArtifactVerification;
pub use authority::AuthorityVerification;
pub use authority::GrantVerifier;
pub use authority::InputEnvelope;
pub use authority::InputVerifier;
pub use authority::ManifestVerifier;
pub use authority::ModelArtifactAuthority;
pub use authority::ModelManifestClaims;
pub use authority::ResourceGrantAuthority;
pub use authority::ResourceGrantClaims;
pub use authority::SignedResourceGrant;
pub use authority::SystemTrustedClock;
pub use authority::TrustedClock;
pub use authority::TrustedDeadline;
pub use authority::VerifiedInput;
pub use authority::VerifiedModelManifest;
pub use authority::VerifiedResourceGrant;
pub use authority::grant_semantic_digest;
pub use authority::input_semantic_digest;
pub use authority::manifest_semantic_digest;
pub use coordinator::LocalInferenceRuntime;
pub use coordinator::LocalRunOutcome;
pub use driver::AttestedModelHandle;
pub use driver::DeviceVerification;
pub use driver::DriverFuture;
pub use driver::DriverLoadedModel;
pub use driver::DriverReconciliation;
pub use driver::DriverRunObservation;
pub use driver::DriverTerminalStatus;
pub use driver::LocalModelDriver;
pub use driver::TokenUsage;
pub use driver::TrustedDeviceAuthority;
pub use driver::TrustedMemoryObservation;
pub use driver::UnloadObservation;
pub use resources::ResourceLimits;
pub use resources::ResourceManager;
pub use resources::ResourceSnapshot;

use std::error::Error as StdError;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalRuntimeError {
    InvalidGrant(&'static str),
    InvalidManifest(&'static str),
    InvalidInput(&'static str),
    Authority(String),
    Artifact(String),
    Clock(String),
    Expired,
    Revoked,
    Capacity,
    Fenced(String),
    Conflict,
    ActiveRequests,
    Driver(String),
    Device(String),
    Control(String),
    ReconciliationRequired(String),
    ArithmeticOverflow,
    LockPoisoned,
}

impl fmt::Display for LocalRuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LocalRuntimeError {}

impl From<codex_hepta_infer_core::durable_control::Error> for LocalRuntimeError {
    fn from(value: codex_hepta_infer_core::durable_control::Error) -> Self {
        Self::Control(value.to_string())
    }
}

#[cfg(test)]
mod tests;
