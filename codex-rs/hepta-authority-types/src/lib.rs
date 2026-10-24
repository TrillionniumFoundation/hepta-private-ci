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
