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
    version: WireVersion,
    frame_length: usize,
}

/// The completed prefix produced by one incremental feed, plus an optional
/// terminal protocol/resource error observed later in the same chunk.
///
/// A caller must process `frames` even when `terminal_error` is present. The
/// decoder becomes poisoned after a terminal error and accepts no more bytes
/// until `clear` is called for an explicitly new connection/session.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StreamDecodeBatch {
    frames: Vec<DecodedEnvelope>,
    terminal_error: Option<StreamDecodeError>,
}

impl StreamDecodeBatch {
    pub fn frames(&self) -> &[DecodedEnvelope] {
        &self.frames
    }

    pub fn terminal_error(&self) -> Option<&StreamDecodeError> {
        self.terminal_error.as_ref()
    }

    pub fn into_parts(self) -> (Vec<DecodedEnvelope>, Option<StreamDecodeError>) {
        (self.frames, self.terminal_error)
    }
}

/// Bounded incremental decoder for byte-stream transports.
///
/// Only enough bytes to complete the fixed header are copied before that
/// header is validated. A valid header authorizes buffering only the declared,
/// bounded frame body. Completed frames use ownership transfer rather than
/// front-draining a shared `Vec`, so a batch of small frames does not repeatedly
/// shift the unread suffix.
///
/// The decoder is deliberately transport-neutral: deadlines, authentication,
/// disconnect handling and connection limits remain the owning transport's
/// responsibility.
#[derive(Debug)]
pub struct StreamingDecoder {
    buffer: Vec<u8>,
    negotiated_version: Option<WireVersion>,
    expected_frame_length: Option<usize>,
    // Historical public configuration is expressed in maximum-frame units.
    // Header-first decoding retains at most one partial frame; this budget
    // additionally bounds the bytes exposed by one feed so the returned frame
    // batch and per-call work cannot grow without a transport-owned limit.
    max_feed_bytes: usize,
    terminal_error: Option<StreamDecodeError>,
}

impl Default for StreamingDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl StreamingDecoder {
    pub fn new() -> Self {
        Self {
            buffer: Vec::with_capacity(WIRE_HEADER_BYTES),
            negotiated_version: None,
            expected_frame_length: None,
            max_feed_bytes: MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES,
            terminal_error: None,
        }
    }

    /// Apply the session version before allocating or accepting any body bytes.
    pub(crate) fn for_negotiated_version(version: WireVersion) -> Self {
        Self {
            negotiated_version: Some(version),
            ..Self::new()
        }
    }

    /// Configure the per-feed budget in units of maximum-sized frames.
    ///
    /// The name is retained for API compatibility. Complete frames are moved
    /// out immediately, so this bounds a partial frame plus one borrowed feed,
    /// not long-lived retained buffer capacity.
    pub fn with_max_buffered_frames(frames: usize) -> Result<Self, StreamDecodeError> {
        if !(1..=MAX_BUFFERED_WIRE_FRAMES).contains(&frames) {
            return Err(StreamDecodeError::InvalidBufferFrameLimit(frames));
        }
        Ok(Self {
            buffer: Vec::with_capacity(WIRE_HEADER_BYTES),
            negotiated_version: None,
            expected_frame_length: None,
            max_feed_bytes: MAX_WIRE_FRAME_BYTES
                .checked_mul(frames)
                .ok_or(StreamDecodeError::LengthOverflow)?,
            terminal_error: None,
        })
    }

    pub fn buffered_len(&self) -> usize {
        self.buffer.len()
    }

    pub fn terminal_error(&self) -> Option<&StreamDecodeError> {
        self.terminal_error.as_ref()
    }

    pub const fn is_poisoned(&self) -> bool {
        self.terminal_error.is_some()
    }

    /// Reset connection-local state.
    ///
    /// Callers must use this only after the previous connection/session has
    /// been discarded. It is not recovery for a partially trusted byte stream.
    pub fn clear(&mut self) {
        self.buffer.clear();
        self.buffer.shrink_to(WIRE_HEADER_BYTES);
        self.expected_frame_length = None;
        self.terminal_error = None;
    }

    /// Feed a transport chunk and preserve both a valid decoded prefix and a
    /// later terminal error from the same chunk.
    ///
    /// The owning transport must split reads so the partial frame plus this
    /// feed fits the configured byte budget. A feed that exceeds the budget is
    /// rejected before any byte from that feed is consumed; accepted feeds are
    /// invariant across every internal chunk boundary.
    pub fn push_batch(&mut self, chunk: &[u8]) -> StreamDecodeBatch {
        if let Some(error) = self.terminal_error.clone() {
            return StreamDecodeBatch {
                frames: Vec::new(),
                terminal_error: Some(error),
            };
        }

        let attempted = match self.buffer.len().checked_add(chunk.len()) {
            Some(value) => value,
            None => {
                return self.fail(Vec::new(), StreamDecodeError::LengthOverflow);
            }
        };
        if attempted > self.max_feed_bytes {
            return self.fail(
                Vec::new(),
                StreamDecodeError::BufferLimit {
                    attempted,
                    maximum: self.max_feed_bytes,
                },
            );
        }

        let mut decoded = Vec::new();
        let mut offset = 0;
        while offset < chunk.len() {
            if self.expected_frame_length.is_none() {
                let header_remaining = WIRE_HEADER_BYTES.saturating_sub(self.buffer.len());
                if header_remaining > 0 {
                    let copied = header_remaining.min(chunk.len() - offset);
                    self.buffer
                        .extend_from_slice(&chunk[offset..offset + copied]);
                    offset += copied;
                }
                if self.buffer.len() < WIRE_HEADER_BYTES {
                    break;
                }

                let header = match inspect_header(&self.buffer) {
                    Ok(header) => header,
                    Err(error) => return self.fail(decoded, error),
                };
                if let Some(negotiated) = self.negotiated_version
                    && header.version != negotiated
                {
                    return self.fail(
                        decoded,
                        StreamDecodeError::NegotiatedVersionMismatch {
                            negotiated,
                            observed: header.version,
                        },
                    );
                }
                self.buffer
                    .reserve_exact(header.frame_length.saturating_sub(self.buffer.len()));
                self.expected_frame_length = Some(header.frame_length);
            }

            let Some(expected) = self.expected_frame_length else {
                continue;
            };
            let body_remaining = expected.saturating_sub(self.buffer.len());
            if body_remaining > 0 {
                let copied = body_remaining.min(chunk.len() - offset);
                self.buffer
                    .extend_from_slice(&chunk[offset..offset + copied]);
                offset += copied;
            }
            if self.buffer.len() < expected {
                break;
            }

            let frame = std::mem::replace(&mut self.buffer, Vec::with_capacity(WIRE_HEADER_BYTES));
            self.expected_frame_length = None;
            match decode_frame(&frame).map_err(StreamDecodeError::Frame) {
                Ok(envelope) => decoded.push(envelope),
                Err(error) => return self.fail(decoded, error),
            }
        }

        StreamDecodeBatch {
            frames: decoded,
            terminal_error: None,
        }
    }

    /// Compatibility wrapper for callers that consume only complete batches.
    ///
    /// If a chunk contains valid frames followed by a terminal error, this
    /// method returns the valid prefix and records the error in the decoder.
    /// The next call returns that terminal error. New code should use
    /// `push_batch` so both facts are observed atomically.
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<DecodedEnvelope>, StreamDecodeError> {
        let batch = self.push_batch(chunk);
        let (frames, terminal_error) = batch.into_parts();
        if frames.is_empty()
            && let Some(error) = terminal_error
        {
            return Err(error);
        }
        Ok(frames)
    }

    fn fail(
        &mut self,
        frames: Vec<DecodedEnvelope>,
        error: StreamDecodeError,
    ) -> StreamDecodeBatch {
        self.buffer.clear();
        self.buffer.shrink_to(WIRE_HEADER_BYTES);
        self.expected_frame_length = None;
        self.terminal_error = Some(error.clone());
        StreamDecodeBatch {
            frames,
            terminal_error: Some(error),
        }
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
    reader.read_exact(&mut header).map_err(ReadFrameError::Io)?;
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
    let version = match raw_version {
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
    Ok(FrameHeader {
        version,
        frame_length,
    })
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
    BufferLimit {
        attempted: usize,
        maximum: usize,
    },
    TruncatedHeader,
    Magic,
    Version(u16),
    NegotiatedVersionMismatch {
        negotiated: WireVersion,
        observed: WireVersion,
    },
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
                write!(
                    formatter,
                    "wire stream frame buffer limit must be 1..=2, found {frames}"
                )
            }
            Self::BufferLimit { attempted, maximum } => write!(
                formatter,
                "wire stream buffer would grow to {attempted} bytes, maximum is {maximum}"
            ),
            Self::TruncatedHeader => formatter.write_str("wire stream header is truncated"),
            Self::Magic => formatter.write_str("wire stream magic mismatch"),
            Self::Version(version) => {
                write!(formatter, "unsupported wire stream version {version}")
            }
            Self::NegotiatedVersionMismatch {
                negotiated,
                observed,
            } => write!(
                formatter,
                "wire header version {} does not match negotiated version {}",
                observed.as_u16(),
                negotiated.as_u16()
            ),
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
