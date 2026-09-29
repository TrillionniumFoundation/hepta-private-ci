use std::error::Error;
use std::fmt;

use codex_hepta_memory_federation::FederationV2Error;

use crate::FederationClientError;
use crate::FederationHostError;

#[derive(Debug)]
pub enum FederationProductErrorV1 {
    InvalidProfile,
    InvalidTransportContext,
    TransportPeerMismatch,
    TransportProfileMismatch,
    TransportContextExpired,
    PacketOversize,
    PacketMagic,
    PacketVersion,
    PacketTruncated,
    TrailingBytes,
    MissingBody,
    UnexpectedBody,
    BodyOversize,
    BodyCodec,
    BodySchemaMismatch,
    BodyDigestMismatch,
    QueryBindingMismatch,
    QueryBeyondAuthenticatedHorizon,
    ResponseBeyondAuthenticatedHorizon,
    ResponseBindingMismatch,
    ResponseDigestMismatch,
    FrontierResponseMismatch,
    UnexpectedWireMessage,
    InvalidIdentity,
    InvalidRevision,
    InvalidCompleteness,
    ClientStatePoisoned,
    ClockUnavailable,
    WireCodec,
    Host(FederationHostError),
    Client(FederationClientError),
    V2(FederationV2Error),
}

impl fmt::Display for FederationProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidProfile => formatter.write_str("federation product profile is invalid"),
            Self::InvalidTransportContext => {
                formatter.write_str("authenticated transport context is invalid")
            }
            Self::TransportPeerMismatch => {
                formatter.write_str("authenticated transport peer does not match")
            }
            Self::TransportProfileMismatch => {
                formatter.write_str("authenticated transport profile does not match")
            }
            Self::TransportContextExpired => {
                formatter.write_str("authenticated transport context is not current")
            }
            Self::PacketOversize => formatter.write_str("federation product packet is oversized"),
            Self::PacketMagic => formatter.write_str("federation product packet magic is invalid"),
            Self::PacketVersion => {
                formatter.write_str("federation product packet version is unsupported")
            }
            Self::PacketTruncated => formatter.write_str("federation product packet is truncated"),
            Self::TrailingBytes => {
                formatter.write_str("federation product packet has trailing bytes")
            }
            Self::MissingBody => formatter.write_str("federation product packet body is missing"),
            Self::UnexpectedBody => formatter.write_str("federation control packet has a body"),
            Self::BodyOversize => formatter.write_str("federation product body is oversized"),
            Self::BodyCodec => formatter.write_str("federation product body codec rejected input"),
            Self::BodySchemaMismatch => {
                formatter.write_str("federation product body schema or version differs")
            }
            Self::BodyDigestMismatch => {
                formatter.write_str("federation product body digest differs")
            }
            Self::QueryBindingMismatch => formatter.write_str("canonical V2 query binding differs"),
            Self::QueryBeyondAuthenticatedHorizon => {
                formatter.write_str("canonical query deadline exceeds authenticated frame horizon")
            }
            Self::ResponseBeyondAuthenticatedHorizon => formatter
                .write_str("canonical response expiry exceeds authenticated channel horizon"),
            Self::ResponseBindingMismatch => {
                formatter.write_str("canonical V2 response binding differs")
            }
            Self::ResponseDigestMismatch => {
                formatter.write_str("canonical V2 response digest differs")
            }
            Self::FrontierResponseMismatch => {
                formatter.write_str("owner frontier and canonical response differ")
            }
            Self::UnexpectedWireMessage => {
                formatter.write_str("unexpected authenticated federation wire message")
            }
            Self::InvalidIdentity => formatter.write_str("federation product identity is invalid"),
            Self::InvalidRevision => formatter.write_str("federation product revision is invalid"),
            Self::InvalidCompleteness => {
                formatter.write_str("federation product completeness is invalid")
            }
            Self::ClientStatePoisoned => {
                formatter.write_str("federation product client state lock is poisoned")
            }
            Self::ClockUnavailable => {
                formatter.write_str("federation product clock is unavailable")
            }
            Self::WireCodec => {
                formatter.write_str("federation wire frame codec rejected the packet")
            }
            Self::Host(error) => error.fmt(formatter),
            Self::Client(error) => error.fmt(formatter),
            Self::V2(error) => error.fmt(formatter),
        }
    }
}

impl Error for FederationProductErrorV1 {}

impl From<FederationHostError> for FederationProductErrorV1 {
    fn from(value: FederationHostError) -> Self {
        Self::Host(value)
    }
}

impl From<FederationClientError> for FederationProductErrorV1 {
    fn from(value: FederationClientError) -> Self {
        Self::Client(value)
    }
}

impl From<FederationV2Error> for FederationProductErrorV1 {
    fn from(value: FederationV2Error) -> Self {
        Self::V2(value)
    }
}
