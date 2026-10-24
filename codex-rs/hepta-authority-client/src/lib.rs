//! The original authenticated RootSession and proof verification implementation.
//! This client owns no issuer, registry, SQLite store or replacement consumer.

#![cfg(target_os = "linux")]

mod root_authority_session;
mod root_observation_cache;
mod root_observation_stream;
mod root_writer_proof;

pub use root_authority_session::AgentdRootAuthoritySession;
pub use root_observation_stream::AgentdRootAuthorityPeer;
pub use root_writer_proof::AgentdRootAuthorityError;
pub use root_writer_proof::AgentdRootWriterTrust;
pub use root_writer_proof::VerifiedRootWriterProof;

pub(crate) use codex_hepta_authority_types::HOST_AUTHORITY_OBSERVATION_V2;
pub(crate) use codex_hepta_authority_types::HOST_WRITER_AUTHORIZATION_V1;
pub(crate) use codex_hepta_authority_types::HostAuthorityObservationRequestV2;
pub(crate) use codex_hepta_authority_types::HostAuthorityObservationResponseV2;
pub(crate) use codex_hepta_authority_types::HostAuthorityWriterObservationV2;
pub(crate) use codex_hepta_authority_types::HostSignedWriterAuthorizationV1;
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationClaimsV1;
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationReadRequestV1;
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationReadResponseV1;
