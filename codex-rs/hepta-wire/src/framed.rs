use std::error::Error;
use std::fmt;
use std::io;
use std::io::Read;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;

const MAGIC: [u8; 4] = *b"HPTA";
pub const WIRE_HEADER_BYTES: usize = 54;
pub const MAX_WIRE_ID_BYTES: usize = 128;
pub const MAX_WIRE_FRAME_BYTES: usize =
    WIRE_HEADER_BYTES + MAX_WIRE_ID_BYTES * 2 + MAX_WIRE_PAYLOAD_BYTES;

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

pub fn decode_envelope(encoded: &[u8]) -> Result<DecodedEnvelope, EnvelopeDecodeError> {
    if encoded.len() < 6 {
        return Err(EnvelopeDecodeError::Truncated);
    }
    if encoded[..4] != MAGIC {
        return Err(EnvelopeDecodeError::Magic);
    }
    let version = u16::from_be_bytes([encoded[4], encoded[5]]);
    match version {
        1 => WireEnvelope::decode(encoded)
            .map(DecodedEnvelope::V1)
            .map_err(EnvelopeDecodeError::V1),
        2 => WireEnvelopeV2::decode(encoded)
            .map(DecodedEnvelope::V2)
            .map_err(EnvelopeDecodeError::V2),
        value => Err(EnvelopeDecodeError::UnsupportedVersion(value)),
    }
}

/// Reads exactly one bounded HPTA frame from a blocking byte stream.
///
/// The fixed header is validated before the body allocation. A second frame may
/// immediately follow the first and remains unread for the next call.
pub fn read_envelope(reader: &mut impl Read) -> Result<DecodedEnvelope, StreamDecodeError> {
    let mut header = [0_u8; WIRE_HEADER_BYTES];
    read_exact(reader, &mut header)?;
    validate_header_before_allocation(&header)?;

    let schema_length = usize::from(u16::from_be_bytes([header[6], header[7]]));
    let producer_length = usize::from(u16::from_be_bytes([header[8], header[9]]));
    let payload_length = usize::try_from(u32::from_be_bytes([
        header[50], header[51], header[52], header[53],
    ]))
    .map_err(|_| StreamDecodeError::PayloadLength)?;
    let body_length = schema_length
        .checked_add(producer_length)
        .and_then(|length| length.checked_add(payload_length))
        .ok_or(StreamDecodeError::FrameLength)?;
    let frame_length = WIRE_HEADER_BYTES
        .checked_add(body_length)
        .ok_or(StreamDecodeError::FrameLength)?;
    if frame_length > MAX_WIRE_FRAME_BYTES {
        return Err(StreamDecodeError::FrameLength);
    }

    let mut encoded = Vec::with_capacity(frame_length);
    encoded.extend_from_slice(&header);
    encoded.resize(frame_length, 0);
    read_exact(reader, &mut encoded[WIRE_HEADER_BYTES..])?;
    decode_envelope(&encoded).map_err(StreamDecodeError::Decode)
}

fn validate_header_before_allocation(header: &[u8; WIRE_HEADER_BYTES]) -> Result<(), StreamDecodeError> {
    if header[..4] != MAGIC {
        return Err(StreamDecodeError::Magic);
    }
    let version = u16::from_be_bytes([header[4], header[5]]);
    if !matches!(version, 1 | 2) {
        return Err(StreamDecodeError::UnsupportedVersion(version));
    }
    let schema_length = usize::from(u16::from_be_bytes([header[6], header[7]]));
    let producer_length = usize::from(u16::from_be_bytes([header[8], header[9]]));
    if !(1..=MAX_WIRE_ID_BYTES).contains(&schema_length)
        || !(1..=MAX_WIRE_ID_BYTES).contains(&producer_length)
    {
        return Err(StreamDecodeError::IdentityLength);
    }
    let generation = u64::from_be_bytes([
        header[10], header[11], header[12], header[13], header[14], header[15], header[16],
        header[17],
    ]);
    if generation == 0 {
        return Err(StreamDecodeError::Generation);
    }
    let payload_length = usize::try_from(u32::from_be_bytes([
        header[50], header[51], header[52], header[53],
    ]))
    .map_err(|_| StreamDecodeError::PayloadLength)?;
    if payload_length == 0 || payload_length > MAX_WIRE_PAYLOAD_BYTES {
        return Err(StreamDecodeError::PayloadLength);
    }
    Ok(())
}

fn read_exact(reader: &mut impl Read, target: &mut [u8]) -> Result<(), StreamDecodeError> {
    match reader.read_exact(target) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => Err(StreamDecodeError::Truncated),
        Err(error) => Err(StreamDecodeError::Io(error)),
    }
}

#[derive(Debug)]
pub enum StreamDecodeError {
    Truncated,
    Magic,
    UnsupportedVersion(u16),
    IdentityLength,
    Generation,
    PayloadLength,
    FrameLength,
    Decode(EnvelopeDecodeError),
    Io(io::Error),
}

impl fmt::Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire stream ended before one complete frame"),
            Self::Magic => formatter.write_str("wire stream magic mismatch"),
            Self::UnsupportedVersion(version) => {
                write!(formatter, "unsupported wire stream version {version}")
            }
            Self::IdentityLength => formatter.write_str("wire stream identity length is outside bounds"),
            Self::Generation => formatter.write_str("wire stream generation must be non-zero"),
            Self::PayloadLength => formatter.write_str("wire stream payload length is outside bounds"),
            Self::FrameLength => formatter.write_str("wire stream frame length overflowed its bound"),
            Self::Decode(error) => fmt::Display::fmt(error, formatter),
            Self::Io(error) => fmt::Display::fmt(error, formatter),
        }
    }
}

impl Error for StreamDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Decode(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::Truncated
            | Self::Magic
            | Self::UnsupportedVersion(_)
            | Self::IdentityLength
            | Self::Generation
            | Self::PayloadLength
            | Self::FrameLength => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EnvelopeDecodeError {
    Truncated,
    Magic,
    UnsupportedVersion(u16),
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for EnvelopeDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire envelope is truncated before version"),
            Self::Magic => formatter.write_str("wire envelope magic mismatch"),
            Self::UnsupportedVersion(version) => write!(formatter, "unsupported wire version {version}"),
            Self::V1(error) => fmt::Display::fmt(error, formatter),
            Self::V2(error) => fmt::Display::fmt(error, formatter),
        }
    }
}

impl Error for EnvelopeDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::V1(error) => Some(error),
            Self::V2(error) => Some(error),
            Self::Truncated | Self::Magic | Self::UnsupportedVersion(_) => None,
        }
    }
}

#[cfg(test)]
#[path = "framed_tests.rs"]
mod tests;
