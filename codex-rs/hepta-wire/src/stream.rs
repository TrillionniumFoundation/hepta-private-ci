use std::error::Error;
use std::fmt;
use std::io::Read;

use crate::DecodeFrameError;
use crate::DecodedEnvelope;
use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireVersion;
use crate::decode_frame;

pub const WIRE_HEADER_BYTES: usize = 54;
pub const MAX_WIRE_FRAME_BYTES: usize = WIRE_HEADER_BYTES + 128 + 128 + MAX_WIRE_PAYLOAD_BYTES;
pub const MAX_BUFFERED_WIRE_FRAMES: usize = 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct FrameHeader {
    frame_length: usize,
}

/// Bounded incremental decoder for byte-stream transports.
///
/// The decoder validates the fixed header before accepting the advertised body
/// size and never buffers more than two maximum-size frames. It is deliberately
/// transport-neutral: deadlines and disconnect handling remain the owning
/// transport's responsibility.
#[derive(Debug)]
pub struct StreamingDecoder {
    buffer: Vec<u8>,
    max_buffered_bytes: usize,
}

impl Default for StreamingDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl StreamingDecoder {
    pub fn new() -> Self {
        Self {
            buffer: Vec::new(),
            max_buffered_bytes: MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES,
        }
    }

    pub fn with_max_buffered_frames(frames: usize) -> Result<Self, StreamDecodeError> {
        if !(1..=MAX_BUFFERED_WIRE_FRAMES).contains(&frames) {
            return Err(StreamDecodeError::InvalidBufferFrameLimit(frames));
        }
        Ok(Self {
            buffer: Vec::new(),
            max_buffered_bytes: MAX_WIRE_FRAME_BYTES
                .checked_mul(frames)
                .ok_or(StreamDecodeError::LengthOverflow)?,
        })
    }

    pub fn buffered_len(&self) -> usize {
        self.buffer.len()
    }

    pub fn clear(&mut self) {
        self.buffer.clear();
    }

    /// Feed a transport chunk and return every complete frame now available.
    ///
    /// A chunk that would exceed the connection-local buffer bound rejects
    /// before it is copied into the decoder.
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<DecodedEnvelope>, StreamDecodeError> {
        let next_len = self
            .buffer
            .len()
            .checked_add(chunk.len())
            .ok_or(StreamDecodeError::LengthOverflow)?;
        if next_len > self.max_buffered_bytes {
            return Err(StreamDecodeError::BufferLimit {
                attempted: next_len,
                maximum: self.max_buffered_bytes,
            });
        }
        self.buffer.extend_from_slice(chunk);

        let mut decoded = Vec::new();
        loop {
            if self.buffer.len() < WIRE_HEADER_BYTES {
                break;
            }
            let header = inspect_header(&self.buffer[..WIRE_HEADER_BYTES])?;
            if self.buffer.len() < header.frame_length {
                break;
            }
            let envelope = decode_frame(&self.buffer[..header.frame_length])
                .map_err(StreamDecodeError::Frame)?;
            self.buffer.drain(..header.frame_length);
            decoded.push(envelope);
        }
        Ok(decoded)
    }
}

/// Read exactly one frame from a blocking byte stream.
///
/// Only the fixed 54-byte header is read before frame lengths and bounds are
/// validated. The owned frame allocation happens only after that admission,
/// so an attacker-controlled advertised length cannot trigger an unbounded
/// pre-validation allocation inside this API. `std::net::TcpStream`,
/// `std::os::unix::net::UnixStream`, files and pipes implement `Read`.
pub fn read_frame<R: Read>(reader: &mut R) -> Result<DecodedEnvelope, ReadFrameError> {
    let mut header = [0_u8; WIRE_HEADER_BYTES];
    reader
        .read_exact(&mut header)
        .map_err(ReadFrameError::Io)?;
    let inspected = inspect_header(&header).map_err(ReadFrameError::Protocol)?;
    let mut frame = Vec::with_capacity(inspected.frame_length);
    frame.extend_from_slice(&header);
    frame.resize(inspected.frame_length, 0);
    reader
        .read_exact(&mut frame[WIRE_HEADER_BYTES..])
        .map_err(ReadFrameError::Io)?;
    decode_frame(&frame).map_err(|error| ReadFrameError::Protocol(StreamDecodeError::Frame(error)))
}

#[derive(Debug)]
pub enum ReadFrameError {
    Io(std::io::Error),
    Protocol(StreamDecodeError),
}

impl fmt::Display for ReadFrameError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "wire stream I/O failed: {error}"),
            Self::Protocol(error) => error.fmt(formatter),
        }
    }
}

impl Error for ReadFrameError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Protocol(error) => Some(error),
        }
    }
}

fn inspect_header(header: &[u8]) -> Result<FrameHeader, StreamDecodeError> {
    if header.len() < WIRE_HEADER_BYTES {
        return Err(StreamDecodeError::TruncatedHeader);
    }
    if header[..4] != *b"HPTA" {
        return Err(StreamDecodeError::Magic);
    }
    let raw_version = read_u16(header, 4)?;
    let _version = match raw_version {
        1 => WireVersion::V1,
        2 => WireVersion::V2,
        other => return Err(StreamDecodeError::Version(other)),
    };
    let schema_length = usize::from(read_u16(header, 6)?);
    let producer_length = usize::from(read_u16(header, 8)?);
    if !(1..=128).contains(&schema_length) || !(1..=128).contains(&producer_length) {
        return Err(StreamDecodeError::IdentityLength);
    }
    if read_u64(header, 10)? == 0 {
        return Err(StreamDecodeError::Generation);
    }
    let payload_length =
        usize::try_from(read_u32(header, 50)?).map_err(|_| StreamDecodeError::PayloadLength)?;
    if payload_length == 0 || payload_length > MAX_WIRE_PAYLOAD_BYTES {
        return Err(StreamDecodeError::PayloadLength);
    }
    let frame_length = WIRE_HEADER_BYTES
        .checked_add(schema_length)
        .and_then(|value| value.checked_add(producer_length))
        .and_then(|value| value.checked_add(payload_length))
        .ok_or(StreamDecodeError::LengthOverflow)?;
    if frame_length > MAX_WIRE_FRAME_BYTES {
        return Err(StreamDecodeError::PayloadLength);
    }
    Ok(FrameHeader { frame_length })
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
    InvalidBufferFrameLimit(usize),
    BufferLimit { attempted: usize, maximum: usize },
    TruncatedHeader,
    Magic,
    Version(u16),
    IdentityLength,
    Generation,
    PayloadLength,
    LengthOverflow,
    Frame(DecodeFrameError),
}

impl fmt::Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBufferFrameLimit(frames) => {
                write!(formatter, "wire stream frame buffer limit must be 1..=2, found {frames}")
            }
            Self::BufferLimit { attempted, maximum } => write!(
                formatter,
                "wire stream buffer would grow to {attempted} bytes, maximum is {maximum}"
            ),
            Self::TruncatedHeader => formatter.write_str("wire stream header is truncated"),
            Self::Magic => formatter.write_str("wire stream magic mismatch"),
            Self::Version(version) => write!(formatter, "unsupported wire stream version {version}"),
            Self::IdentityLength => {
                formatter.write_str("wire stream identity length is outside bounds")
            }
            Self::Generation => formatter.write_str("wire stream generation must be non-zero"),
            Self::PayloadLength => {
                formatter.write_str("wire stream payload length is outside bounds")
            }
            Self::LengthOverflow => formatter.write_str("wire stream length overflow"),
            Self::Frame(error) => error.fmt(formatter),
        }
    }
}

impl Error for StreamDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Frame(error) => Some(error),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "stream_tests.rs"]
mod tests;
