//! Versioned, authenticated cross-host contracts for memory federation.
//!
//! This crate is transport-neutral. It provides registered canonical encoding,
//! directional peer credentials, bounded replay protection, authenticated
//! frontier witnesses, and cancellation acknowledgement. A selected product
//! transport must still provide mutually authenticated TLS (or an equivalent
//! independently reviewed secure channel), peer routing, durable enrollment,
//! and target-host qualification.

#![forbid(unsafe_code)]

mod codec;
mod credential;
mod protocol;
mod replay;

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
pub use credential::PeerCredentialRegistryV1;
pub use credential::PeerCredentialV1;
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
pub use replay::MAX_FEDERATION_REPLAY_ENTRIES;
pub use replay::ReplayCacheV1;
pub use replay::ReplayError;

#[cfg(test)]
mod tests;
