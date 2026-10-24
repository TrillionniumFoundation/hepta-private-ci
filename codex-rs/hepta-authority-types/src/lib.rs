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

mod identity;
pub use identity::AgentdIdentity;
pub use identity::HostAuthorityRegisteredIdentity;

mod cognitive_values;
pub use cognitive_values::CognitiveCheckpointTransport;
pub use cognitive_values::CognitiveRecoveryAnchor;
pub use cognitive_values::ObjectiveSenderCheckpoint;
pub use cognitive_values::ObjectiveSenderCheckpointError;
pub use cognitive_values::ObjectiveSenderWriterFence;

mod cognitive_checkpoint_wire;
pub use cognitive_checkpoint_wire::COGNITIVE_CHECKPOINT_FRAME_LIMIT;
pub use cognitive_checkpoint_wire::CognitiveCheckpointCommand;
pub use cognitive_checkpoint_wire::CognitiveCheckpointHead;
pub use cognitive_checkpoint_wire::CognitiveCheckpointPeerLifetime;
pub use cognitive_checkpoint_wire::CognitiveCheckpointPhase;
pub use cognitive_checkpoint_wire::CognitiveCheckpointProposal;
pub use cognitive_checkpoint_wire::CognitiveCheckpointReason;
pub use cognitive_checkpoint_wire::CognitiveCheckpointReceipt;
pub use cognitive_checkpoint_wire::CognitiveCheckpointRequest;
pub use cognitive_checkpoint_wire::CognitiveCheckpointResponse;
pub use cognitive_checkpoint_wire::CognitiveCheckpointRetainedProposal;
pub use cognitive_checkpoint_wire::CognitiveCheckpointRetainedRequest;
pub use cognitive_checkpoint_wire::CognitiveCheckpointStatus;
pub use cognitive_checkpoint_wire::CognitiveCheckpointToken;
pub use cognitive_checkpoint_wire::CognitiveCheckpointWriterBinding;
