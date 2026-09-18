use std::error::Error;
use std::fmt;

use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;

const MAGIC: [u8; 4] = *b"HPTA";
const HEADER_FIXED_BYTES: usize = 54;
const MAX_ID_BYTES: usize = 128;
pub const MAX_WIRE_FRAME_BYTES: usize =
    HEADER_FIXED_BYTES + (MAX_ID_BYTES * 2) + MAX_WIRE_PAYLOAD_BYTES;

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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StreamProgress {
    pub consumed: usize,
    pub frame: Option<DecodedEnvelope>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct WireStreamDecoder {
    buffer: Vec<u8>,
    expected_len: Option<usize>,
    expected_version: Option<WireVersion>,
}

impl WireStreamDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn for_version(version: WireVersion) -> Self {
        Self {
            buffer: Vec::new(),
            expected_len: None,
            expected_version: Some(version),
        }
    }

    pub const fn negotiated_version(&self) -> Option<WireVersion> {
        self.expected_version
    }

    pub fn buffered_len(&self) -> usize {
        self.buffer.len()
    }

    pub const fn expected_len(&self) -> Option<usize> {
        self.expected_len
    }

    pub fn reset(&mut self) {
        self.buffer.clear();
        self.expected_len = None;
    }

    /// Consumes at most one complete frame from input.
    ///
    /// consumed tells the transport owner how many bytes were accepted. Bytes
    /// belonging to a following frame are deliberately left unconsumed so a
    /// caller can feed them again without unbounded internal buffering.
    pub fn push(&mut self, input: &[u8]) -> Result<StreamProgress, StreamDecodeError> {
        let mut consumed = 0;

        while consumed < input.len() {
            if self.expected_len.is_none() {
                let header_remaining = HEADER_FIXED_BYTES.saturating_sub(self.buffer.len());
                let take = header_remaining.min(input.len() - consumed);
                self.buffer
                    .extend_from_slice(&input[consumed..consumed + take]);
                consumed += take;

                if self.buffer.len() < HEADER_FIXED_BYTES {
                    return Ok(StreamProgress {
                        consumed,
                        frame: None,
                    });
                }

                let expected = expected_frame_len(&self.buffer, self.expected_version)?;
                self.buffer.reserve(expected - self.buffer.len());
                self.expected_len = Some(expected);
            }

            let expected = self
                .expected_len
                .ok_or(StreamDecodeError::LengthOverflow)?;
            let frame_remaining = expected.saturating_sub(self.buffer.len());
            let take = frame_remaining.min(input.len() - consumed);
            self.buffer
                .extend_from_slice(&input[consumed..consumed + take]);
            consumed += take;

            if self.buffer.len() == expected {
                let frame = decode_complete(&self.buffer)?;
                self.reset();
                return Ok(StreamProgress {
                    consumed,
                    frame: Some(frame),
                });
            }
        }

        Ok(StreamProgress {
            consumed,
            frame: None,
        })
    }
}

fn expected_frame_len(
    header: &[u8],
    expected_version: Option<WireVersion>,
) -> Result<usize, StreamDecodeError> {
    if header.len() < HEADER_FIXED_BYTES {
        return Err(StreamDecodeError::TruncatedHeader);
    }
    if header[..4] != MAGIC {
        return Err(StreamDecodeError::Magic);
    }
    let version = read_u16(header, 4)?;
    let observed =
        WireVersion::try_from(version).map_err(|_| StreamDecodeError::Version(version))?;
    if let Some(expected) = expected_version {
        if observed != expected {
            return Err(StreamDecodeError::NegotiatedVersionMismatch {
                expected,
                observed,
            });
        }
    }
    let schema_length = usize::from(read_u16(header, 6)?);
    let producer_length = usize::from(read_u16(header, 8)?);
    if !(1..=MAX_ID_BYTES).contains(&schema_length)
        || !(1..=MAX_ID_BYTES).contains(&producer_length)
    {
        return Err(StreamDecodeError::IdentityLength);
    }
    if read_u64(header, 10)? == 0 {
        return Err(StreamDecodeError::Generation);
    }
    let payload_length = usize::try_from(read_u32(header, 50)?)
        .map_err(|_| StreamDecodeError::PayloadLength)?;
    if payload_length == 0 || payload_length > MAX_WIRE_PAYLOAD_BYTES {
        return Err(StreamDecodeError::PayloadLength);
    }
    let expected = HEADER_FIXED_BYTES
        .checked_add(schema_length)
        .and_then(|value| value.checked_add(producer_length))
        .and_then(|value| value.checked_add(payload_length))
        .ok_or(StreamDecodeError::LengthOverflow)?;
    if expected > MAX_WIRE_FRAME_BYTES {
        return Err(StreamDecodeError::FrameTooLarge);
    }
    Ok(expected)
}

fn decode_complete(frame: &[u8]) -> Result<DecodedEnvelope, StreamDecodeError> {
    let version = read_u16(frame, 4)?;
    match WireVersion::try_from(version).map_err(|_| StreamDecodeError::Version(version))? {
        WireVersion::V1 => WireEnvelope::decode(frame)
            .map(DecodedEnvelope::V1)
            .map_err(StreamDecodeError::V1),
        WireVersion::V2 => WireEnvelopeV2::decode(frame)
            .map(DecodedEnvelope::V2)
            .map_err(StreamDecodeError::V2),
    }
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, StreamDecodeError> {
    let end = start
        .checked_add(2)
        .ok_or(StreamDecodeError::TruncatedHeader)?;
    let raw: [u8; 2] = bytes
        .get(start..end)
        .ok_or(StreamDecodeError::TruncatedHeader)?
        .try_into()
        .map_err(|_| StreamDecodeError::TruncatedHeader)?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u32(bytes: &[u8], start: usize) -> Result<u32, StreamDecodeError> {
    let end = start
        .checked_add(4)
        .ok_or(StreamDecodeError::TruncatedHeader)?;
    let raw: [u8; 4] = bytes
        .get(start..end)
        .ok_or(StreamDecodeError::TruncatedHeader)?
        .try_into()
        .map_err(|_| StreamDecodeError::TruncatedHeader)?;
    Ok(u32::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, StreamDecodeError> {
    let end = start
        .checked_add(8)
        .ok_or(StreamDecodeError::TruncatedHeader)?;
    let raw: [u8; 8] = bytes
        .get(start..end)
        .ok_or(StreamDecodeError::TruncatedHeader)?
        .try_into()
        .map_err(|_| StreamDecodeError::TruncatedHeader)?;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamDecodeError {
    TruncatedHeader,
    Magic,
    Version(u16),
    NegotiatedVersionMismatch {
        expected: WireVersion,
        observed: WireVersion,
    },
    IdentityLength,
    Generation,
    PayloadLength,
    LengthOverflow,
    FrameTooLarge,
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for StreamDecodeError {}

#[cfg(test)]
#[path = "stream_tests.rs"]
mod tests;
