//! Canonical externally supplied writer-authority values and original errors.
//! These types perform shape/digest checks; they create no issuer or execution grant.

#![forbid(unsafe_code)]

mod authority;
mod error;

pub use authority::ProductionAuthorityLease;
pub use authority::ProductionAuthorityToken;
pub use authority::ProductionAuthorityVerifier;
pub use error::CognitiveStoreError;
pub use error::LocalLeaseOutboxError;
pub use error::ProductionWriterError;

mod authority_host_wire;
pub use authority_host_wire::HOST_AUTHORITY_OBSERVATION_V2;
pub use authority_host_wire::HOST_WRITER_AUTHORIZATION_V1;
pub use authority_host_wire::HostAuthorityObservationRequestV2;
pub use authority_host_wire::HostAuthorityObservationResponseV2;
pub use authority_host_wire::HostAuthorityWriterObservationV2;
pub use authority_host_wire::HostConsumerFrontierRequestV1;
pub use authority_host_wire::HostConsumerFrontierResponseV1;
pub use authority_host_wire::HostConsumerFrontierStatusV1;
pub use authority_host_wire::HostSignedWriterAuthorizationV1;
pub use authority_host_wire::HostWriterAuthorizationClaimsV1;
pub use authority_host_wire::HostWriterAuthorizationReadRequestV1;
pub use authority_host_wire::HostWriterAuthorizationReadResponseV1;
