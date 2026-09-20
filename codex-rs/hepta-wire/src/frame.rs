use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecodedEnvelope {
    V1(WireEnvelope),
    V2(WireEnvelopeV2),
}

impl DecodedEnvelope {
    pub const fn version(&self) -> WireVersion {
        match self {
            Self::V1(_) => WireVersion::V1,
            Self::V2(_) => WireVersion::V2,
        }
    }

    pub fn schema(&self) -> &StableId {
        match self {
            Self::V1(envelope) => envelope.schema(),
            Self::V2(envelope) => envelope.schema(),
        }
    }

    pub fn producer(&self) -> &StableId {
        match self {
            Self::V1(envelope) => envelope.producer(),
            Self::V2(envelope) => envelope.producer(),
        }
    }

    pub const fn generation(&self) -> Generation {
        match self {
            Self::V1(envelope) => envelope.generation(),
            Self::V2(envelope) => envelope.generation(),
        }
    }

    pub fn payload(&self) -> &[u8] {
        match self {
            Self::V1(envelope) => envelope.payload(),
            Self::V2(envelope) => envelope.payload(),
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::V1(envelope) => envelope.encode(),
            Self::V2(envelope) => envelope.encode(),
        }
    }
}

pub fn decode_frame(encoded: &[u8]) -> Result<DecodedEnvelope, DecodeFrameError> {
    if encoded.len() < 6 {
        return Err(DecodeFrameError::Truncated);
    }
    if encoded[..4] != *b"HPTA" {
        return Err(DecodeFrameError::Magic);
    }
    let version = u16::from_be_bytes([encoded[4], encoded[5]]);
    match version {
        1 => WireEnvelope::decode(encoded)
            .map(DecodedEnvelope::V1)
            .map_err(DecodeFrameError::V1),
        2 => WireEnvelopeV2::decode(encoded)
            .map(DecodedEnvelope::V2)
            .map_err(DecodeFrameError::V2),
        other => Err(DecodeFrameError::Version(other)),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecodeFrameError {
    Truncated,
    Magic,
    Version(u16),
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for DecodeFrameError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire frame is truncated before version"),
            Self::Magic => formatter.write_str("wire frame magic mismatch"),
            Self::Version(version) => write!(formatter, "unsupported wire version {version}"),
            Self::V1(error) => error.fmt(formatter),
            Self::V2(error) => error.fmt(formatter),
        }
    }
}

impl Error for DecodeFrameError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::V1(error) => Some(error),
            Self::V2(error) => Some(error),
            _ => None,
        }
    }
}
