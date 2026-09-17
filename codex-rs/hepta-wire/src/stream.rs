use std::error::Error;
use std::fmt;

use crate::V2_WIRE_VERSION;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;

const MAGIC: [u8; 4] = *b"HPTA";
const V1_WIRE_VERSION: u16 = 1;
const HEADER_FIXED_BYTES: usize = 4 + 2 + 2 + 2 + 8 + 32 + 4;
const MAX_ID_BYTES: usize = 128;
pub const MAX_WIRE_FRAME_BYTES: usize =
    HEADER_FIXED_BYTES + MAX_ID_BYTES + MAX_ID_BYTES + crate::MAX_WIRE_PAYLOAD_BYTES;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecodedFrame {
    V1(WireEnvelope),
    V2(WireEnvelopeV2),
}

impl DecodedFrame {
    pub const fn version(&self) -> WireVersion {
        match self {
            Self::V1(_) => WireVersion::V1,
            Self::V2(_) => WireVersion::V2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodeProgress {
    pub consumed: usize,
    pub frame: Option<DecodedFrame>,
}

/// Incremental HPTA frame decoder.
///
/// One call consumes at most the bytes needed to finish one frame. If the input
/// also contains the start of the next frame, `consumed` is smaller than
/// `input.len()` and the caller feeds the remainder again. This prevents the
/// decoder from buffering an unbounded number of frames and lets it enforce the
/// declared payload bound before allocating the body.
#[derive(Clone, Debug)]
pub struct WireFrameDecoder {
    buffer: Vec<u8>,
    expected_len: Option<usize>,
}

impl Default for WireFrameDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl WireFrameDecoder {
    pub fn new() -> Self {
        Self {
            buffer: Vec::with_capacity(HEADER_FIXED_BYTES),
            expected_len: None,
        }
    }

    pub fn buffered_len(&self) -> usize {
        self.buffer.len()
    }

    pub fn reset(&mut self) {
        self.buffer.clear();
        self.expected_len = None;
    }

    pub fn push(&mut self, input: &[u8]) -> Result<DecodeProgress, FrameDecodeError> {
        let mut consumed = 0_usize;

        if self.buffer.len() < HEADER_FIXED_BYTES {
            let needed = HEADER_FIXED_BYTES - self.buffer.len();
            let take = needed.min(input.len());
            self.buffer.extend_from_slice(&input[..take]);
            consumed += take;
            if self.buffer.len() < HEADER_FIXED_BYTES {
                return Ok(DecodeProgress {
                    consumed,
                    frame: None,
                });
            }
            match inspect_header(&self.buffer) {
                Ok(expected_len) => self.expected_len = Some(expected_len),
                Err(error) => {
                    self.reset();
                    return Err(error);
                }
            }
        }

        let expected_len = self
            .expected_len
            .ok_or(FrameDecodeError::InternalState)?;
        if self.buffer.len() < expected_len && consumed < input.len() {
            let needed = expected_len - self.buffer.len();
            let remaining = &input[consumed..];
            let take = needed.min(remaining.len());
            self.buffer.extend_from_slice(&remaining[..take]);
            consumed += take;
        }
        if self.buffer.len() < expected_len {
            return Ok(DecodeProgress {
                consumed,
                frame: None,
            });
        }

        let encoded = std::mem::replace(
            &mut self.buffer,
            Vec::with_capacity(HEADER_FIXED_BYTES),
        );
        self.expected_len = None;
        let version = read_u16(&encoded, 4).map_err(|_| FrameDecodeError::TruncatedHeader)?;
        let frame = match version {
            V1_WIRE_VERSION => WireEnvelope::decode(&encoded)
                .map(DecodedFrame::V1)
                .map_err(FrameDecodeError::V1)?,
            V2_WIRE_VERSION => WireEnvelopeV2::decode(&encoded)
                .map(DecodedFrame::V2)
                .map_err(FrameDecodeError::V2)?,
            other => return Err(FrameDecodeError::UnsupportedVersion(other)),
        };
        Ok(DecodeProgress {
            consumed,
            frame: Some(frame),
        })
    }
}

fn inspect_header(header: &[u8]) -> Result<usize, FrameDecodeError> {
    if header.len() < HEADER_FIXED_BYTES {
        return Err(FrameDecodeError::TruncatedHeader);
    }
    if header[..4] != MAGIC {
        return Err(FrameDecodeError::Magic);
    }
    let version = read_u16(header, 4).map_err(|_| FrameDecodeError::TruncatedHeader)?;
    if version != V1_WIRE_VERSION && version != V2_WIRE_VERSION {
        return Err(FrameDecodeError::UnsupportedVersion(version));
    }
    let schema_length = usize::from(
        read_u16(header, 6).map_err(|_| FrameDecodeError::TruncatedHeader)?,
    );
    let producer_length = usize::from(
        read_u16(header, 8).map_err(|_| FrameDecodeError::TruncatedHeader)?,
    );
    if !(1..=MAX_ID_BYTES).contains(&schema_length)
        || !(1..=MAX_ID_BYTES).contains(&producer_length)
    {
        return Err(FrameDecodeError::IdentityLength);
    }
    let generation = read_u64(header, 10).map_err(|_| FrameDecodeError::TruncatedHeader)?;
    if generation == 0 {
        return Err(FrameDecodeError::Generation);
    }
    let payload_length = usize::try_from(
        read_u32(header, 50).map_err(|_| FrameDecodeError::TruncatedHeader)?,
    )
    .map_err(|_| FrameDecodeError::PayloadLength)?;
    if payload_length == 0 || payload_length > crate::MAX_WIRE_PAYLOAD_BYTES {
        return Err(FrameDecodeError::PayloadLength);
    }
    let expected_len = HEADER_FIXED_BYTES
        .checked_add(schema_length)
        .and_then(|value| value.checked_add(producer_length))
        .and_then(|value| value.checked_add(payload_length))
        .ok_or(FrameDecodeError::FrameLengthOverflow)?;
    if expected_len > MAX_WIRE_FRAME_BYTES {
        return Err(FrameDecodeError::FrameLengthOverflow);
    }
    Ok(expected_len)
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, ()> {
    let end = start.checked_add(2).ok_or(())?;
    let raw: [u8; 2] = bytes.get(start..end).ok_or(())?.try_into().map_err(|_| ())?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u32(bytes: &[u8], start: usize) -> Result<u32, ()> {
    let end = start.checked_add(4).ok_or(())?;
    let raw: [u8; 4] = bytes.get(start..end).ok_or(())?.try_into().map_err(|_| ())?;
    Ok(u32::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, ()> {
    let end = start.checked_add(8).ok_or(())?;
    let raw: [u8; 8] = bytes.get(start..end).ok_or(())?.try_into().map_err(|_| ())?;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrameDecodeError {
    TruncatedHeader,
    Magic,
    UnsupportedVersion(u16),
    IdentityLength,
    Generation,
    PayloadLength,
    FrameLengthOverflow,
    InternalState,
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for FrameDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TruncatedHeader => formatter.write_str("HPTA streaming header is truncated"),
            Self::Magic => formatter.write_str("HPTA streaming header magic mismatch"),
            Self::UnsupportedVersion(version) => {
                write!(formatter, "HPTA streaming decoder does not support version {version}")
            }
            Self::IdentityLength => formatter.write_str("HPTA streaming identity length is outside bounds"),
            Self::Generation => formatter.write_str("HPTA streaming generation must be non-zero"),
            Self::PayloadLength => formatter.write_str("HPTA streaming payload length is outside bounds"),
            Self::FrameLengthOverflow => formatter.write_str("HPTA streaming frame length overflow"),
            Self::InternalState => formatter.write_str("HPTA streaming decoder internal state error"),
            Self::V1(error) => write!(formatter, "HPTA V1 frame rejected: {error}"),
            Self::V2(error) => write!(formatter, "HPTA V2 frame rejected: {error}"),
        }
    }
}

impl Error for FrameDecodeError {}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use super::*;

    fn v2_frame() -> Vec<u8> {
        WireEnvelopeV2::new(
            StableId::new("stream.schema").expect("schema"),
            StableId::new("stream.producer").expect("producer"),
            Generation::new(1).expect("generation"),
            b"streamed-payload".to_vec(),
        )
        .expect("envelope")
        .encode()
    }

    #[test]
    fn decoder_admits_header_before_allocating_body_and_consumes_one_frame() {
        let frame = v2_frame();
        let mut decoder = WireFrameDecoder::new();
        for byte in &frame[..HEADER_FIXED_BYTES - 1] {
            let progress = decoder.push(std::slice::from_ref(byte)).expect("prefix");
            assert!(progress.frame.is_none());
            assert_eq!(progress.consumed, 1);
        }
        assert_eq!(decoder.buffered_len(), HEADER_FIXED_BYTES - 1);

        let mut two_frames = Vec::with_capacity(frame.len() * 2);
        two_frames.extend_from_slice(&frame[HEADER_FIXED_BYTES - 1..]);
        two_frames.extend_from_slice(&frame);
        let progress = decoder.push(&two_frames).expect("complete first frame");
        assert!(matches!(progress.frame, Some(DecodedFrame::V2(_))));
        assert!(progress.consumed < two_frames.len());
        assert_eq!(decoder.buffered_len(), 0);

        let remainder = &two_frames[progress.consumed..];
        let progress = decoder.push(remainder).expect("second frame");
        assert!(matches!(progress.frame, Some(DecodedFrame::V2(_))));
        assert_eq!(progress.consumed, remainder.len());
    }

    #[test]
    fn oversized_payload_is_rejected_from_header_without_body_buffering() {
        let mut frame = v2_frame();
        frame[50..54].copy_from_slice(&u32::MAX.to_be_bytes());
        let mut decoder = WireFrameDecoder::new();
        assert_eq!(
            decoder.push(&frame[..HEADER_FIXED_BYTES]),
            Err(FrameDecodeError::PayloadLength)
        );
        assert_eq!(decoder.buffered_len(), 0);
    }
}
