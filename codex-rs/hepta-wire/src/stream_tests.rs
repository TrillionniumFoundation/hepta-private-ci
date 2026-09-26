use super::*;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FrameHeaderParseError;
use crate::FrameHeaderValidationError;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

fn is_magic(error: Option<&StreamDecodeError>) -> bool {
    matches!(
        error,
        Some(StreamDecodeError::HeaderParse(
            FrameHeaderParseError::Magic {
                byte_offset: 0,
                ..
            }
        ))
    )
}

#[test]
fn one_byte_chunks_do_not_dispatch_until_complete() -> Result<(), Box<dyn Error>> {
    let frame = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("runtime.codex")?,
        Generation::new(1)?,
        b"payload".to_vec(),
    )?
    .encode();

    let mut decoder = StreamingDecoder::new();
    for byte in &frame[..frame.len() - 1] {
        assert!(decoder.push(std::slice::from_ref(byte))?.is_empty());
    }
    let decoded = decoder.push(&frame[frame.len() - 1..])?;
    assert_eq!(decoded.len(), 1);
    assert_eq!(decoded[0].payload(), b"payload");
    assert_eq!(decoder.buffered_len(), 0);
    Ok(())
}

#[test]
fn consecutive_v1_and_v2_frames_decode_from_one_chunk() -> Result<(), Box<dyn Error>> {
    let v1 = WireEnvelope::new(
        stable("hepta.stream.v1")?,
        stable("producer")?,
        Generation::new(1)?,
        vec![1],
    )?
    .encode();
    let v2 = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("producer")?,
        Generation::new(2)?,
        vec![2],
    )?
    .encode();
    let mut bytes = v1;
    bytes.extend_from_slice(&v2);

    let mut decoder = StreamingDecoder::new();
    let decoded = decoder.push(&bytes)?;
    assert_eq!(decoded.len(), 2);
    assert_eq!(decoded[0].version(), WireVersion::V1);
    assert_eq!(decoded[1].version(), WireVersion::V2);
    Ok(())
}

#[test]
fn oversized_advertised_payload_rejects_at_header_boundary() -> Result<(), Box<dyn Error>> {
    let mut header =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    header[50..54].copy_from_slice(&((crate::MAX_WIRE_PAYLOAD_BYTES as u32) + 1).to_be_bytes());
    header.truncate(crate::WIRE_HEADER_BYTES);

    let mut decoder = StreamingDecoder::new();
    assert!(matches!(
        decoder.push(&header),
        Err(StreamDecodeError::HeaderValidation(
            FrameHeaderValidationError::PayloadLength {
                actual,
                maximum,
                byte_offset: 50,
                ..
            }
        )) if actual == crate::MAX_WIRE_PAYLOAD_BYTES + 1
            && maximum == crate::MAX_WIRE_PAYLOAD_BYTES
    ));
    Ok(())
}

#[test]
fn buffer_limit_rejects_before_copying_unbounded_chunk() {
    let mut decoder = StreamingDecoder::new();
    let oversized = vec![0_u8; crate::MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES + 1];
    assert!(matches!(
        decoder.push(&oversized),
        Err(StreamDecodeError::BufferLimit { .. })
    ));
    assert_eq!(decoder.buffered_len(), 0);
}

#[test]
fn blocking_reader_validates_header_before_reading_body() -> Result<(), Box<dyn Error>> {
    let mut oversized_header =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    oversized_header[50..54]
        .copy_from_slice(&((crate::MAX_WIRE_PAYLOAD_BYTES as u32) + 1).to_be_bytes());
    oversized_header.truncate(crate::WIRE_HEADER_BYTES);

    let mut cursor = std::io::Cursor::new(oversized_header);
    assert!(matches!(
        read_frame(&mut cursor),
        Err(ReadFrameError::Protocol(
            StreamDecodeError::HeaderValidation(
                FrameHeaderValidationError::PayloadLength {
                    byte_offset: 50,
                    ..
                }
            )
        ))
    ));
    assert_eq!(cursor.position(), crate::WIRE_HEADER_BYTES as u64);
    Ok(())
}

#[test]
fn blocking_reader_allocates_and_reads_only_after_admission() -> Result<(), Box<dyn Error>> {
    let frame = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("producer")?,
        Generation::new(3)?,
        b"body".to_vec(),
    )?
    .encode();
    let mut cursor = std::io::Cursor::new(frame.clone());
    let decoded = read_frame(&mut cursor)?;
    assert_eq!(decoded.version(), WireVersion::V2);
    assert_eq!(decoded.payload(), b"body");
    assert_eq!(cursor.position(), frame.len() as u64);
    Ok(())
}

#[test]
fn valid_prefix_and_terminal_error_are_reported_atomically() -> Result<(), Box<dyn Error>> {
    let valid = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("runtime.codex")?,
        Generation::new(4)?,
        b"valid-prefix".to_vec(),
    )?
    .encode();
    let mut invalid = valid.clone();
    invalid[0] = b'X';
    let mut chunk = valid.clone();
    chunk.extend_from_slice(&invalid);

    let mut decoder = StreamingDecoder::new();
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), 1);
    assert_eq!(batch.frames()[0].payload(), b"valid-prefix");
    assert!(is_magic(batch.terminal_error()));
    assert!(decoder.is_poisoned());
    assert_eq!(decoder.buffered_len(), 0);
    assert!(matches!(
        decoder.push(&valid),
        Err(StreamDecodeError::HeaderParse(
            FrameHeaderParseError::Magic { .. }
        ))
    ));

    decoder.clear();
    assert!(!decoder.is_poisoned());
    assert_eq!(decoder.push(&valid)?.len(), 1);
    Ok(())
}

#[test]
fn every_chunk_boundary_preserves_the_same_valid_prefix_and_terminal_error()
-> Result<(), Box<dyn Error>> {
    let valid = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("runtime.codex")?,
        Generation::new(5)?,
        b"same-prefix".to_vec(),
    )?
    .encode();
    let mut invalid = valid.clone();
    invalid[0] = b'X';

    let mut bytes = valid;
    bytes.extend_from_slice(&invalid);
    let mut coalesced = StreamingDecoder::new();
    let expected = coalesced.push_batch(&bytes);
    assert_eq!(expected.frames().len(), 1);
    assert!(is_magic(expected.terminal_error()));

    for split_at in 0..=bytes.len() {
        let mut decoder = StreamingDecoder::new();
        let first = decoder.push_batch(&bytes[..split_at]);
        let mut frames = first.frames().to_vec();
        let terminal_error = match first.terminal_error().cloned() {
            Some(error) => Some(error),
            None => {
                let second = decoder.push_batch(&bytes[split_at..]);
                frames.extend_from_slice(second.frames());
                second.terminal_error().cloned()
            }
        };

        assert_eq!(
            frames,
            expected.frames(),
            "valid prefix changed at chunk boundary {split_at}"
        );
        assert_eq!(
            terminal_error.as_ref(),
            expected.terminal_error(),
            "terminal error changed at chunk boundary {split_at}"
        );
    }
    Ok(())
}

#[test]
fn invalid_header_never_copies_the_advertised_body() -> Result<(), Box<dyn Error>> {
    let mut chunk =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    chunk[0] = b'X';
    chunk.resize(crate::MAX_WIRE_PAYLOAD_BYTES, 0);

    let mut decoder = StreamingDecoder::new();
    let batch = decoder.push_batch(&chunk);
    assert!(is_magic(batch.terminal_error()));
    assert_eq!(decoder.buffered_len(), 0);
    assert!(decoder.is_poisoned());
    Ok(())
}

#[test]
fn many_small_frames_stop_at_the_explicit_work_budget() -> Result<(), Box<dyn Error>> {
    let frame =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let chunk = frame.repeat(MAX_WIRE_FRAMES_PER_FEED + 1);
    let mut decoder = StreamingDecoder::new();
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), MAX_WIRE_FRAMES_PER_FEED);
    assert!(matches!(
        batch.terminal_error(),
        Some(StreamDecodeError::WorkFrameLimit {
            attempted,
            maximum,
            byte_offset,
        }) if *attempted == MAX_WIRE_FRAMES_PER_FEED + 1
            && *maximum == MAX_WIRE_FRAMES_PER_FEED
            && *byte_offset == frame.len() * MAX_WIRE_FRAMES_PER_FEED
    ));
    assert!(decoder.is_poisoned());
    assert_eq!(decoder.buffered_len(), 0);
    Ok(())
}

#[test]
fn configurable_work_budget_preserves_the_valid_prefix() -> Result<(), Box<dyn Error>> {
    let frame =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let chunk = frame.repeat(3);
    let mut decoder = StreamingDecoder::with_limits(1, 2)?;
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), 2);
    assert!(matches!(
        batch.terminal_error(),
        Some(StreamDecodeError::WorkFrameLimit {
            attempted: 3,
            maximum: 2,
            ..
        })
    ));
    Ok(())
}

#[test]
fn compatibility_push_returns_valid_prefix_before_latched_error() -> Result<(), Box<dyn Error>> {
    let valid = WireEnvelopeV2::new(
        stable("hepta.stream.v2")?,
        stable("runtime.codex")?,
        Generation::new(6)?,
        b"compat-prefix".to_vec(),
    )?
    .encode();
    let mut invalid = valid.clone();
    invalid[0] = b'X';
    let mut chunk = valid.clone();
    chunk.extend_from_slice(&invalid);

    let mut decoder = StreamingDecoder::new();
    let frames = decoder.push(&chunk)?;
    assert_eq!(frames.len(), 1);
    assert_eq!(frames[0].payload(), b"compat-prefix");
    assert!(is_magic(decoder.terminal_error()));
    assert!(matches!(
        decoder.push(&valid),
        Err(StreamDecodeError::HeaderParse(
            FrameHeaderParseError::Magic { .. }
        ))
    ));
    Ok(())
}

#[test]
fn digest_error_preserves_multiple_prefix_frames_at_every_split() -> Result<(), Box<dyn Error>> {
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?;
    let v2 = WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(2)?, vec![2])?;
    let mut bad = v2.encode();
    *bad.last_mut().ok_or("empty frame")? ^= 1;
    let mut bytes = v1.encode();
    bytes.extend_from_slice(&v2.encode());
    bytes.extend_from_slice(&bad);
    let expected = vec![DecodedEnvelope::V1(v1), DecodedEnvelope::V2(v2)];
    for split in 0..=bytes.len() {
        let mut decoder = StreamingDecoder::new();
        let (mut frames, first_error) = decoder.push_batch(&bytes[..split]).into_parts();
        let (tail, last_error) = decoder.push_batch(&bytes[split..]).into_parts();
        frames.extend(tail);
        assert_eq!(frames, expected, "split {split}");
        assert!(matches!(
            first_error.or(last_error),
            Some(StreamDecodeError::Frame(DecodeFrameError::V2(
                crate::WireV2Error::DigestMismatch { .. }
            )))
        ));
        assert!(decoder.is_poisoned());
        assert_eq!(decoder.buffered_len(), 0);
    }
    Ok(())
}

#[test]
fn maximum_v2_frame_round_trips_across_header_and_body_boundaries() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        stable(&"s".repeat(128))?,
        stable(&"p".repeat(128))?,
        Generation::new(u64::MAX)?,
        vec![0xa5; crate::MAX_WIRE_PAYLOAD_BYTES],
    )?;
    let frame = envelope.encode();
    assert_eq!(frame.len(), crate::MAX_WIRE_FRAME_BYTES);
    for chunk_size in [53, 54, 55, 4096, frame.len() - 1, frame.len()] {
        let mut decoder = StreamingDecoder::with_max_buffered_frames(1)?;
        let mut frames = Vec::new();
        for chunk in frame.chunks(chunk_size) {
            let (complete, error) = decoder.push_batch(chunk).into_parts();
            assert!(error.is_none(), "chunk size {chunk_size}: {error:?}");
            frames.extend(complete);
        }
        assert_eq!(frames, vec![DecodedEnvelope::V2(envelope.clone())]);
        assert_eq!(decoder.buffered_len(), 0);
    }
    Ok(())
}
