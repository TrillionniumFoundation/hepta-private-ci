//! Versioned, authenticated cross-host contracts for memory federation.
//!
//! This crate is transport-neutral. It provides registered canonical encoding,
//! directional peer credentials, bounded replay protection, authenticated
//! frontier witnesses, restart-surviving replay/attempt recovery, a two-stage
//! read-only host admission boundary, and cancellation acknowledgement. A
//! selected product transport must still provide mutually authenticated TLS (or
//! an equivalent independently reviewed secure channel), peer routing, secure
//! credential storage, and target-host qualification.

#![forbid(unsafe_code)]

mod attempt;
mod client;
mod codec;
mod credential;
mod host;
mod protocol;
mod recovery;
mod replay;

pub use attempt::AttemptRegistryError;
pub use attempt::FederationAttemptRegistryV1;
pub use attempt::MAX_FEDERATION_ATTEMPTS;
pub use client::FederationClientError;
pub use client::FederationWireClientV1;
pub use codec::AUTHENTICATED_FRAME_FORMAT_VERSION_V1;
pub use codec::AUTHENTICATED_FRAME_SCHEMA_V1;
pub use codec::AuthenticatedFrameCodecV1;
pub use codec::FederationCodecError;
pub use codec::MAX_AUTHENTICATED_FRAME_BYTES;
pub use codec::decode_registered_frame_v1;
pub use codec::encode_registered_frame_v1;
pub use codec::registered_codec_v1;
pub use credential::CredentialError;
pub use credential::FEDERATION_MAC_KEY_BYTES;
pub use credential::MAX_FEDERATION_CREDENTIAL_KEYS;
pub use credential::MAX_FEDERATION_CREDENTIAL_KEYS_PER_PEER_PAIR;
pub use credential::PeerCredentialRegistryV1;
pub use credential::PeerCredentialV1;
pub use host::AdmittedFederationQueryV1;
pub use host::FederationHostAdmissionV1;
pub use host::FederationHostError;
pub use host::FederationHostQueryResultV1;
pub use host::FederationOutboundCredentialV1;
pub use host::FederationWireHostV1;
pub use host::MAX_FEDERATION_HOST_PEERS;
pub use protocol::AuthenticatedFederationFrameV1;
pub use protocol::AuthenticatedFrontierV1;
pub use protocol::FEDERATION_MAC_BYTES;
pub use protocol::FEDERATION_NONCE_BYTES;
pub use protocol::FederationCancelAckMessageV1;
pub use protocol::FederationCancelMessageV1;
pub use protocol::FederationCancellationDispositionV1;
pub use protocol::FederationCancellationReasonV1;
pub use protocol::FederationNonceV1;
pub use protocol::FederationProtocolError;
pub use protocol::FederationQueryMessageV1;
pub use protocol::FederationResponseMessageV1;
pub use protocol::FederationWireMessageV1;
pub use protocol::MAX_AUTHENTICATED_FRAME_LIFETIME_MS;
pub use protocol::VerifiedFederationFrameV1;
pub use recovery::DurableFederationStateV1;
pub use recovery::FederationRecoveryError;
pub use recovery::FederationRecoveryLimitsV1;
pub use recovery::FederationRecoveryStoreV1;
pub use recovery::InMemoryFederationRecoveryStoreV1;
pub use replay::MAX_FEDERATION_REPLAY_ENTRIES;
pub use replay::MAX_FEDERATION_REPLAY_ENTRIES_PER_CREDENTIAL;
pub use replay::ReplayCacheV1;
pub use replay::ReplayError;

#[cfg(test)]
mod attempt_tests;
#[cfg(test)]
mod client_tests;
#[cfg(test)]
mod credential_tests;
#[cfg(test)]
mod host_tests;
#[cfg(test)]
mod tests;
