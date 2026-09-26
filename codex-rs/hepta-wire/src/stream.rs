use std::error::Error;
use std::fmt;
use std::io::Read;

use crate::DecodeFrameError;
use crate::DecodedEnvelope;
use crate::FrameHeader;
use crate::FrameHeaderParseError;
use crate::FrameHeaderValidationError;
use crate::MAX_WIRE_FRAME_BYTES;
use crate::WIRE_HEADER_BYTES;
use crate::WireVersion;
use crate::decode_frame;

pub const MAX_BUFFERED_WIRE_FRAMES: usize = 2;
pub const MAX_WIRE_FRAMES_PER_FEED: usize = 1_024;

/// The completed prefix produced by one incremental feed, plus an optional
/// terminal protocol/resource error observed later in the same chunk.
///
/// A caller must process `frames` even when `terminal_error` is present. The
/// decoder becomes poisoned after a terminal error and accepts no more bytes
/// until `clear` is called for an explicitly new connection/session.
#[must_use = "consume the completed prefix and inspect the terminal error"]
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
/// Only enough bytes to complete the canonical fixed header are copied before
/// that header is validated. A valid header authorizes buffering only the
/// declared, bounded frame body. Completed frames use ownership transfer rather
/// than front-draining a shared `Vec`.
///
/// Two independent budgets apply to every feed: retained/borrowed bytes and
/// completed frame work. The latter prevents a coalesced chunk of tiny frames
/// from turning a byte-safe decoder into an unbounded CPU and allocation loop.
#[derive(Debug)]
pub struct StreamingDecoder {
    buffer: Vec<u8>,
    negotiated_version: Option<WireVersion>,
    expected_frame_length: Option<usize>,
    max_feed_bytes: usize,
    max_frames_per_feed: usize,
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
            max_frames_per_feed: MAX_WIRE_FRAMES_PER_FEED,
            terminal_error: None,
        }
    }

    /// Apply the session version before allocating or accepting body bytes.
    pub(crate) fn for_negotiated_version(version: WireVersion) -> Self {
        Self {
            negotiated_version: Some(version),
            ..Self::new()
        }
    }

    /// Configure the per-feed byte budget in maximum-frame units while using
    /// the production frame-work ceiling.
    pub fn with_max_buffered_frames(frames: usize) -> Result<Self, StreamDecodeError> {
        Self::with_limits(frames, MAX_WIRE_FRAMES_PER_FEED)
    }

    /// Configure both independent per-feed resource ceilings.
    pub fn with_limits(
        buffered_frames: usize,
        frames_per_feed: usize,
    ) -> Result<Self, StreamDecodeError> {
        if !(1..=MAX_BUFFERED_WIRE_FRAMES).contains(&buffered_frames) {
            return Err(StreamDecodeError::InvalidBufferFrameLimit {
                actual: buffered_frames,
                minimum: 1,
                maximum: MAX_BUFFERED_WIRE_FRAMES,
            });
        }
        if !(1..=MAX_WIRE_FRAMES_PER_FEED).contains(&frames_per_feed) {
            return Err(StreamDecodeError::InvalidWorkFrameLimit {
                actual: frames_per_feed,
                minimum: 1,
                maximum: MAX_WIRE_FRAMES_PER_FEED,
            });
        }
        Ok(Self {
            buffer: Vec::with_capacity(WIRE_HEADER_BYTES),
            negotiated_version: None,
            expected_frame_length: None,
            max_feed_bytes: MAX_WIRE_FRAME_BYTES
                .checked_mul(buffered_frames)
                .ok_or(StreamDecodeError::LengthOverflow { byte_offset: 0 })?,
            max_frames_per_feed: frames_per_feed,
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

    /// Reset connection-local state only after discarding the old session.
    pub fn clear(&mut self) {
        self.buffer.clear();
        self.buffer.shrink_to(WIRE_HEADER_BYTES);
        self.expected_frame_length = None;
        self.terminal_error = None;
    }

    /// Feed a transport chunk and preserve both a valid decoded prefix and a
    /// later terminal error from the same chunk.
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
                return self.fail(
                    Vec::new(),
                    StreamDecodeError::LengthOverflow {
                        byte_offset: self.buffer.len(),
                    },
                );
            }
        };
        if attempted > self.max_feed_bytes {
            return self.fail(
                Vec::new(),
                StreamDecodeError::BufferLimit {
                    attempted,
                    maximum: self.max_feed_bytes,
                    byte_offset: 0,
                },
            );
        }

        let mut decoded = Vec::new();
        let mut offset = 0;
        while offset < chunk.len() {
            if decoded.len() >= self.max_frames_per_feed {
                return self.fail(
                    decoded,
                    StreamDecodeError::WorkFrameLimit {
                        attempted: self.max_frames_per_feed.saturating_add(1),
                        maximum: self.max_frames_per_feed,
                        byte_offset: offset,
                    },
                );
            }

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

                let parsed = match FrameHeader::parse(&self.buffer) {
                    Ok(header) => header,
                    Err(error) => {
                        return self.fail(decoded, StreamDecodeError::HeaderParse(error));
                    }
                };
                let header = match parsed.validate() {
                    Ok(header) => header,
                    Err(error) => {
                        return self.fail(decoded, StreamDecodeError::HeaderValidation(error));
                    }
                };
                if let Some(negotiated) = self.negotiated_version
                    && header.version() != negotiated
                {
                    return self.fail(
                        decoded,
                        StreamDecodeError::NegotiatedVersionMismatch {
                            negotiated,
                            observed: header.version(),
                            byte_offset: 4,
                        },
                    );
                }
                self.buffer
                    .reserve_exact(header.frame_length().saturating_sub(self.buffer.len()));
                self.expected_frame_length = Some(header.frame_length());
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

/// Read exactly one frame from a blocking byte stream after canonical header
/// parsing and structural validation.
pub fn read_frame<R: Read>(reader: &mut R) -> Result<DecodedEnvelope, ReadFrameError> {
    let mut header_bytes = [0_u8; WIRE_HEADER_BYTES];
    reader
        .read_exact(&mut header_bytes)
        .map_err(ReadFrameError::Io)?;
    let parsed = FrameHeader::parse(&header_bytes)
        .map_err(|error| ReadFrameError::Protocol(StreamDecodeError::HeaderParse(error)))?;
    let header = parsed
        .validate()
        .map_err(|error| ReadFrameError::Protocol(StreamDecodeError::HeaderValidation(error)))?;
    let mut frame = Vec::with_capacity(header.frame_length());
    frame.extend_from_slice(&header_bytes);
    frame.resize(header.frame_length(), 0);
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamDecodeError {
    InvalidBufferFrameLimit {
        actual: usize,
        minimum: usize,
        maximum: usize,
    },
    InvalidWorkFrameLimit {
        actual: usize,
        minimum: usize,
        maximum: usize,
    },
    BufferLimit {
        attempted: usize,
        maximum: usize,
        byte_offset: usize,
    },
    WorkFrameLimit {
        attempted: usize,
        maximum: usize,
        byte_offset: usize,
    },
    HeaderParse(FrameHeaderParseError),
    HeaderValidation(FrameHeaderValidationError),
    NegotiatedVersionMismatch {
        negotiated: WireVersion,
        observed: WireVersion,
        byte_offset: usize,
    },
    LengthOverflow {
        byte_offset: usize,
    },
    Frame(DecodeFrameError),
}

impl StreamDecodeError {
    pub const fn byte_offset(&self) -> Option<usize> {
        match self {
            Self::BufferLimit { byte_offset, .. }
            | Self::WorkFrameLimit { byte_offset, .. }
            | Self::NegotiatedVersionMismatch { byte_offset, .. }
            | Self::LengthOverflow { byte_offset } => Some(*byte_offset),
            Self::HeaderParse(error) => Some(error.byte_offset()),
            Self::HeaderValidation(error) => Some(error.byte_offset()),
            Self::InvalidBufferFrameLimit { .. }
            | Self::InvalidWorkFrameLimit { .. }
            | Self::Frame(_) => None,
        }
    }
}

impl fmt::Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBufferFrameLimit {
                actual,
                minimum,
                maximum,
            } => write!(
                formatter,
                "wire stream byte-frame limit is {actual}, expected {minimum}..={maximum}"
            ),
            Self::InvalidWorkFrameLimit {
                actual,
                minimum,
                maximum,
            } => write!(
                formatter,
                "wire stream work-frame limit is {actual}, expected {minimum}..={maximum}"
            ),
            Self::BufferLimit {
                attempted,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire stream feed at byte {byte_offset} would expose {attempted} bytes, maximum is {maximum}"
            ),
            Self::WorkFrameLimit {
                attempted,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "wire stream feed at byte {byte_offset} would decode frame {attempted}, maximum is {maximum}"
            ),
            Self::HeaderParse(error) => error.fmt(formatter),
            Self::HeaderValidation(error) => error.fmt(formatter),
            Self::NegotiatedVersionMismatch {
                negotiated,
                observed,
                byte_offset,
            } => write!(
                formatter,
                "wire header version at byte {byte_offset} is {}, negotiated version is {}",
                observed.as_u16(),
                negotiated.as_u16()
            ),
            Self::LengthOverflow { byte_offset } => {
                write!(formatter, "wire stream length overflow at byte {byte_offset}")
            }
            Self::Frame(error) => error.fmt(formatter),
        }
    }
}

impl Error for StreamDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::HeaderParse(error) => Some(error),
            Self::HeaderValidation(error) => Some(error),
            Self::Frame(error) => Some(error),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "stream_tests.rs"]
mod tests;
