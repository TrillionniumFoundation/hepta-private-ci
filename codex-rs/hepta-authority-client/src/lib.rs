//! The original authenticated RootSession and proof verification implementation.
//! This client owns no issuer, registry, SQLite store or replacement consumer.

#[cfg(target_os = "linux")]
mod root_authority_session;
#[cfg(target_os = "linux")]
mod root_observation_cache;
#[cfg(target_os = "linux")]
mod root_observation_stream;
#[cfg(target_os = "linux")]
mod root_writer_proof;

#[cfg(target_os = "linux")]
pub use root_authority_session::AgentdRootAuthoritySession;
#[cfg(target_os = "linux")]
pub use root_observation_stream::AgentdRootAuthorityPeer;
#[cfg(target_os = "linux")]
pub use root_writer_proof::AgentdRootAuthorityError;
#[cfg(target_os = "linux")]
pub use root_writer_proof::AgentdRootWriterTrust;
#[cfg(target_os = "linux")]
pub use root_writer_proof::VerifiedRootWriterProof;

#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HOST_AUTHORITY_OBSERVATION_V2;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HOST_WRITER_AUTHORIZATION_V1;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostAuthorityObservationRequestV2;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostAuthorityObservationResponseV2;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostAuthorityWriterObservationV2;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostSignedWriterAuthorizationV1;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationClaimsV1;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationReadRequestV1;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::HostWriterAuthorizationReadResponseV1;

#[cfg(target_os = "linux")]
mod final_use_issuer;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::AuthBusObjectiveBody;
#[cfg(target_os = "linux")]
pub(crate) use codex_hepta_authority_types::AuthBusObjectiveIngress;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerError;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdFinalUseIssuerPeer;
#[cfg(target_os = "linux")]
pub use final_use_issuer::AgentdUnixFinalUseGrantProvider;

mod objective_claims;
pub use objective_claims::ObjectiveClaimsError;
pub use objective_claims::authbus_objective_claims;
pub use objective_claims::objective_payload;
pub use objective_claims::objective_scope;
pub use objective_claims::parse_objective_digest;

/// Read the same Linux suspend-aware clock used by the bounded RootSession.
/// This observation neither renews a lease nor changes an authority frontier.
#[cfg(target_os = "linux")]
pub use root_observation_cache::boottime_ns;
