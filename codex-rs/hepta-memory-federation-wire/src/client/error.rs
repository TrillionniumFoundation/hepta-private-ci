use std::error::Error;
use std::fmt;

use crate::credential::CredentialError;
use crate::protocol::FederationProtocolError;
use crate::recovery::FederationRecoveryError;
use crate::replay::ReplayError;

#[derive(Debug)]
pub enum FederationClientError {
    Codec,
    OutboundFrameRejected,
    MissingOutboundCredential,
    PeerCapacityExhausted,
    TransportPeerMismatch,
    UnexpectedInboundMessage,
    UnknownAttempt,
    AttemptAlreadyTerminal,
    AttemptCancelled,
    UnknownCancellation,
    CancellationAckMismatch,
    FrontierOwnerMismatch,
    FrontierChainUnanchored,
    RemoteObservationClockInvalid,
    FrameExpired,
    SnapshotDecode,
    SnapshotEncode,
    SnapshotNotCanonical,
    SnapshotDigestMismatch,
    SnapshotIdentityMismatch,
    SnapshotStateInvalid,
    Credential(CredentialError),
    Protocol(FederationProtocolError),
    Replay(ReplayError),
    Recovery(FederationRecoveryError),
}

impl fmt::Display for FederationClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Codec => formatter.write_str("authenticated federation codec rejected the frame"),
            Self::OutboundFrameRejected => {
                formatter.write_str("outbound federation frame exceeds the product packet profile")
            }
            Self::MissingOutboundCredential => {
                formatter.write_str("outbound directional credential is not bound")
            }
            Self::PeerCapacityExhausted => {
                formatter.write_str("federation client peer capacity is exhausted")
            }
            Self::TransportPeerMismatch => {
                formatter.write_str("secure transport peer identity does not match frame sender")
            }
            Self::UnexpectedInboundMessage => {
                formatter.write_str("client boundary accepts only response and cancel-ack frames")
            }
            Self::UnknownAttempt => {
                formatter.write_str("outbound query attempt is not durably registered")
            }
            Self::AttemptAlreadyTerminal => {
                formatter.write_str("outbound query attempt is already terminal")
            }
            Self::AttemptCancelled => {
                formatter.write_str("outbound query attempt was durably cancelled")
            }
            Self::UnknownCancellation => {
                formatter.write_str("outbound cancellation is not durably registered")
            }
            Self::CancellationAckMismatch => formatter
                .write_str("cancellation acknowledgement does not match the durable request"),
            Self::FrontierOwnerMismatch => {
                formatter.write_str("owner-cut witness does not belong to the authenticated sender")
            }
            Self::FrontierChainUnanchored => {
                formatter.write_str("first owner-cut witness must use a zero parent digest")
            }
            Self::RemoteObservationClockInvalid => formatter
                .write_str("remote observation time exceeds authenticated frame issue time"),
            Self::FrameExpired => {
                formatter.write_str("outbound frame has no remaining authenticated lifetime")
            }
            Self::SnapshotDecode => {
                formatter.write_str("client recovery snapshot cannot be decoded")
            }
            Self::SnapshotEncode => {
                formatter.write_str("client recovery snapshot cannot be encoded")
            }
            Self::SnapshotNotCanonical => {
                formatter.write_str("client recovery snapshot is not canonical")
            }
            Self::SnapshotDigestMismatch => {
                formatter.write_str("client recovery snapshot digest mismatch")
            }
            Self::SnapshotIdentityMismatch => {
                formatter.write_str("client recovery snapshot identity mismatch")
            }
            Self::SnapshotStateInvalid => {
                formatter.write_str("client recovery snapshot state is invalid")
            }
            Self::Credential(error) => error.fmt(formatter),
            Self::Protocol(error) => error.fmt(formatter),
            Self::Replay(error) => error.fmt(formatter),
            Self::Recovery(error) => error.fmt(formatter),
        }
    }
}

impl Error for FederationClientError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Credential(error) => Some(error),
            Self::Protocol(error) => Some(error),
            Self::Replay(error) => Some(error),
            Self::Recovery(error) => Some(error),
            _ => None,
        }
    }
}

impl From<CredentialError> for FederationClientError {
    fn from(value: CredentialError) -> Self {
        Self::Credential(value)
    }
}

impl From<FederationProtocolError> for FederationClientError {
    fn from(value: FederationProtocolError) -> Self {
        Self::Protocol(value)
    }
}

impl From<ReplayError> for FederationClientError {
    fn from(value: ReplayError) -> Self {
        Self::Replay(value)
    }
}

impl From<FederationRecoveryError> for FederationClientError {
    fn from(value: FederationRecoveryError) -> Self {
        Self::Recovery(value)
    }
}
