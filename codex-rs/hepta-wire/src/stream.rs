use std::error::Error;
use std::fmt;
use std::io::ErrorKind;
use std::io::Read;
use std::io::Write;

use crate::HPTA_V1;
use crate::HPTA_V2;
use crate::HPTA_V2_HEADER_BYTES;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;

const MAGIC: [u8; 4] = *b"HPTA";
const V1_HEADER_BYTES: usize = 54;
const MAX_ID_BYTES: usize = 128;
pub const MAX_WIRE_FRAME_BYTES: usize =
    HPTA_V2_HEADER_BYTES + MAX_ID_BYTES + MAX_ID_BYTES + crate::MAX_WIRE_PAYLOAD_BYTES;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum VersionedEnvelope {
    V1(WireEnvelope),
    V2(WireEnvelopeV2),
}

pub struct FramedReader<R> {
    inner: R,
    max_frame_bytes: usize,
}

impl<R: Read> FramedReader<R> {
    pub fn new(inner: R) -> Self {
        Self {
            inner,
            max_frame_bytes: MAX_WIRE_FRAME_BYTES,
        }
    }

    pub fn with_max_frame_bytes(inner: R, max_frame_bytes: usize) -> Result<Self, StreamError> {
        if max_frame_bytes < V1_HEADER_BYTES || max_frame_bytes > MAX_WIRE_FRAME_BYTES {
            return Err(StreamError::FrameLimit);
        }
        Ok(Self {
            inner,
            max_frame_bytes,
        })
    }

    /// Read exactly one bounded HPTA frame.
    ///
    /// The fixed header is admitted before allocating the body, so an
    /// advertised oversize payload fails before a body-sized allocation.
    pub fn read_next(&mut self) -> Result<Option<VersionedEnvelope>, StreamError> {
        let mut prefix = [0_u8; 6];
        match self.inner.read(&mut prefix[..1]) {
            Ok(0) => return Ok(None),
            Ok(_) => {}
            Err(error) => return Err(StreamError::Io(error.kind())),
        }
        read_exact_bounded(&mut self.inner, &mut prefix[1..])?;
        if prefix[..4] != MAGIC {
            return Err(StreamError::Magic);
        }
        let version = u16::from_be_bytes([prefix[4], prefix[5]]);
        let (header_bytes, payload_offset) = match version {
            HPTA_V1 => (V1_HEADER_BYTES, 50_usize),
            HPTA_V2 => (HPTA_V2_HEADER_BYTES, 82_usize),
            other => return Err(StreamError::UnsupportedVersion(other)),
        };

        let mut header = vec![0_u8; header_bytes];
        header[..6].copy_from_slice(&prefix);
        read_exact_bounded(&mut self.inner, &mut header[6..])?;

        let schema_length = usize::from(u16::from_be_bytes([header[6], header[7]]));
        let producer_length = usize::from(u16::from_be_bytes([header[8], header[9]]));
        if !(1..=MAX_ID_BYTES).contains(&schema_length)
            || !(1..=MAX_ID_BYTES).contains(&producer_length)
        {
            return Err(StreamError::IdentityLength);
        }
        let payload_length = usize::try_from(u32::from_be_bytes([
            header[payload_offset],
            header[payload_offset + 1],
            header[payload_offset + 2],
            header[payload_offset + 3],
        ]))
        .map_err(|_| StreamError::PayloadLength)?;
        if payload_length == 0 || payload_length > crate::MAX_WIRE_PAYLOAD_BYTES {
            return Err(StreamError::PayloadLength);
        }

        let frame_length = header_bytes
            .checked_add(schema_length)
            .and_then(|length| length.checked_add(producer_length))
            .and_then(|length| length.checked_add(payload_length))
            .ok_or(StreamError::FrameLimit)?;
        if frame_length > self.max_frame_bytes || frame_length > MAX_WIRE_FRAME_BYTES {
            return Err(StreamError::FrameLimit);
        }

        let mut frame = vec![0_u8; frame_length];
        frame[..header_bytes].copy_from_slice(&header);
        read_exact_bounded(&mut self.inner, &mut frame[header_bytes..])?;

        match version {
            HPTA_V1 => WireEnvelope::decode(&frame)
                .map(VersionedEnvelope::V1)
                .map_err(StreamError::V1),
            HPTA_V2 => WireEnvelopeV2::decode(&frame)
                .map(VersionedEnvelope::V2)
                .map_err(StreamError::V2),
            _ => Err(StreamError::UnsupportedVersion(version)),
        }
        .map(Some)
    }

    pub fn into_inner(self) -> R {
        self.inner
    }
}

pub struct FramedWriter<W> {
    inner: W,
}

impl<W: Write> FramedWriter<W> {
    pub fn new(inner: W) -> Self {
        Self { inner }
    }

    pub fn write_v1(&mut self, envelope: &WireEnvelope) -> Result<(), StreamError> {
        self.inner
            .write_all(&envelope.encode())
            .map_err(|error| StreamError::Io(error.kind()))
    }

    pub fn write_v2(&mut self, envelope: &WireEnvelopeV2) -> Result<(), StreamError> {
        self.inner
            .write_all(&envelope.encode())
            .map_err(|error| StreamError::Io(error.kind()))
    }

    pub fn into_inner(self) -> W {
        self.inner
    }
}

fn read_exact_bounded(reader: &mut impl Read, target: &mut [u8]) -> Result<(), StreamError> {
    reader.read_exact(target).map_err(|error| {
        if error.kind() == ErrorKind::UnexpectedEof {
            StreamError::Truncated
        } else {
            StreamError::Io(error.kind())
        }
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamError {
    Truncated,
    Magic,
    UnsupportedVersion(u16),
    IdentityLength,
    PayloadLength,
    FrameLimit,
    Io(ErrorKind),
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for StreamError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for StreamError {}
