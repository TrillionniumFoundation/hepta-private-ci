use std::error::Error;
use std::fmt;
use std::io;
use std::io::Read;

use crate::WIRE_VERSION_V1;
use crate::WIRE_VERSION_V2;
use crate::WireError;
use crate::WireFrame;
use crate::envelope::HEADER_FIXED_BYTES;
use crate::envelope::MAX_ID_BYTES;
use crate::envelope::parse_frame_header;

pub const MAX_WIRE_FRAME_BYTES: usize =
    HEADER_FIXED_BYTES + (MAX_ID_BYTES * 2) + crate::MAX_WIRE_PAYLOAD_BYTES;
pub const MAX_STREAM_BUFFER_BYTES: usize = MAX_WIRE_FRAME_BYTES * 2;

/// Read one bounded HPTA frame from a blocking byte stream.
///
/// Only the fixed 54-byte header is read before version and advertised lengths
/// are validated. The body allocation is therefore bounded by protocol limits
/// rather than by untrusted transport buffering.
pub fn read_frame<R: Read>(reader: &mut R) -> Result<WireFrame, WireReadError> {
    let mut header_bytes = [0_u8; HEADER_FIXED_BYTES];
    reader
        .read_exact(&mut header_bytes)
        .map_err(WireReadError::Io)?;
    let header = parse_frame_header(&header_bytes).map_err(WireReadError::Wire)?;
    ensure_supported_version(header.version).map_err(WireReadError::Wire)?;

    let mut frame = Vec::with_capacity(header.total_length);
    frame.extend_from_slice(&header_bytes);
    frame.resize(header.total_length, 0);
    reader
        .read_exact(&mut frame[HEADER_FIXED_BYTES..])
        .map_err(WireReadError::Io)?;
    WireFrame::decode(&frame).map_err(WireReadError::Wire)
}

/// Incremental decoder for transports that deliver arbitrary chunks.
///
/// Buffering is capped at two maximum-size frames. Any malformed header,
/// unsupported version, frame failure, or overflow clears connection-local
/// decoder state so callers fail closed.
#[derive(Default)]
pub struct WireStreamDecoder {
    buffer: Vec<u8>,
}

impl WireStreamDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn buffered_bytes(&self) -> usize {
        self.buffer.len()
    }

    pub fn reset(&mut self) {
        self.buffer.clear();
    }

    pub fn feed(&mut self, bytes: &[u8]) -> Result<(), StreamDecodeError> {
        if self.buffer.len().saturating_add(bytes.len()) > MAX_STREAM_BUFFER_BYTES {
            self.buffer.clear();
            return Err(StreamDecodeError::BufferLimit);
        }
        self.buffer.extend_from_slice(bytes);
        Ok(())
    }

    pub fn next_frame(&mut self) -> Result<Option<WireFrame>, StreamDecodeError> {
        if self.buffer.len() < HEADER_FIXED_BYTES {
            return Ok(None);
        }

        let header = match parse_frame_header(&self.buffer[..HEADER_FIXED_BYTES]) {
            Ok(header) => header,
            Err(error) => {
                self.buffer.clear();
                return Err(StreamDecodeError::Wire(error));
            }
        };
        if let Err(error) = ensure_supported_version(header.version) {
            self.buffer.clear();
            return Err(StreamDecodeError::Wire(error));
        }
        if self.buffer.len() < header.total_length {
            return Ok(None);
        }

        let frame = match WireFrame::decode(&self.buffer[..header.total_length]) {
            Ok(frame) => frame,
            Err(error) => {
                self.buffer.clear();
                return Err(StreamDecodeError::Wire(error));
            }
        };
        self.buffer.drain(..header.total_length);
        Ok(Some(frame))
    }
}

fn ensure_supported_version(version: u16) -> Result<(), WireError> {
    if matches!(version, WIRE_VERSION_V1 | WIRE_VERSION_V2) {
        Ok(())
    } else {
        Err(WireError::Version(version))
    }
}

#[derive(Debug)]
pub enum WireReadError {
    Io(io::Error),
    Wire(WireError),
}

impl fmt::Display for WireReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "wire transport read failed: {error}"),
            Self::Wire(error) => error.fmt(formatter),
        }
    }
}

impl Error for WireReadError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Wire(error) => Some(error),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamDecodeError {
    BufferLimit,
    Wire(WireError),
}

impl fmt::Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::BufferLimit => formatter.write_str("wire stream buffer limit exceeded"),
            Self::Wire(error) => error.fmt(formatter),
        }
    }
}

impl Error for StreamDecodeError {}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use crate::WireEnvelope;
    use crate::WireEnvelopeV2;

    use super::*;

    fn v1() -> WireFrame {
        WireFrame::V1(
            WireEnvelope::new(
                StableId::new("stream.v1").expect("schema"),
                StableId::new("producer").expect("producer"),
                Generation::new(1).expect("generation"),
                vec![1, 2, 3],
            )
            .expect("v1"),
        )
    }

    fn v2() -> WireFrame {
        WireFrame::V2(
            WireEnvelopeV2::new(
                StableId::new("stream.v2").expect("schema"),
                StableId::new("producer").expect("producer"),
                Generation::new(2).expect("generation"),
                vec![4, 5, 6],
            )
            .expect("v2"),
        )
    }

    #[test]
    fn bounded_reader_reads_header_before_body() {
        let expected = v2();
        let bytes = expected.encode();
        let mut cursor = Cursor::new(bytes);
        assert_eq!(read_frame(&mut cursor).expect("read"), expected);
    }

    #[test]
    fn incremental_decoder_handles_arbitrary_chunks_and_multiple_frames() {
        let first = v1();
        let second = v2();
        let mut bytes = first.encode();
        bytes.extend_from_slice(&second.encode());

        let mut decoder = WireStreamDecoder::new();
        let mut decoded = Vec::new();
        for chunk in bytes.chunks(7) {
            decoder.feed(chunk).expect("feed");
            while let Some(frame) = decoder.next_frame().expect("next") {
                decoded.push(frame);
            }
        }
        assert_eq!(decoded, vec![first, second]);
        assert_eq!(decoder.buffered_bytes(), 0);
    }

    #[test]
    fn over_buffer_and_unknown_version_fail_closed() {
        let mut decoder = WireStreamDecoder::new();
        assert_eq!(
            decoder.feed(&vec![0; MAX_STREAM_BUFFER_BYTES + 1]),
            Err(StreamDecodeError::BufferLimit)
        );
        assert_eq!(decoder.buffered_bytes(), 0);

        let mut bytes = v1().encode();
        bytes[4..6].copy_from_slice(&99_u16.to_be_bytes());
        decoder.feed(&bytes).expect("feed");
        assert!(matches!(
            decoder.next_frame(),
            Err(StreamDecodeError::Wire(WireError::Version(99)))
        ));
        assert_eq!(decoder.buffered_bytes(), 0);
    }
}
