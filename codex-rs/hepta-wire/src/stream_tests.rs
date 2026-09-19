use super::*;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
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
    let mut header = WireEnvelopeV2::new(
        stable("s")?,
        stable("p")?,
        Generation::new(1)?,
        vec![1],
    )?
    .encode();
    header[50..54].copy_from_slice(&((MAX_WIRE_PAYLOAD_BYTES as u32) + 1).to_be_bytes());
    header.truncate(WIRE_HEADER_BYTES);

    let mut decoder = StreamingDecoder::new();
    assert_eq!(decoder.push(&header), Err(StreamDecodeError::PayloadLength));
    Ok(())
}

#[test]
fn buffer_limit_rejects_before_copying_unbounded_chunk() {
    let mut decoder = StreamingDecoder::new();
    let oversized = vec![0_u8; MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES + 1];
    assert!(matches!(
        decoder.push(&oversized),
        Err(StreamDecodeError::BufferLimit { .. })
    ));
    assert_eq!(decoder.buffered_len(), 0);
}

#[test]
fn blocking_reader_validates_header_before_reading_body() -> Result<(), Box<dyn Error>> {
    let mut oversized_header = WireEnvelopeV2::new(
        stable("s")?,
        stable("p")?,
        Generation::new(1)?,
        vec![1],
    )?
    .encode();
    oversized_header[50..54]
        .copy_from_slice(&((MAX_WIRE_PAYLOAD_BYTES as u32) + 1).to_be_bytes());
    oversized_header.truncate(WIRE_HEADER_BYTES);

    let mut cursor = std::io::Cursor::new(oversized_header);
    assert!(matches!(
        read_frame(&mut cursor),
        Err(ReadFrameError::Protocol(StreamDecodeError::PayloadLength))
    ));
    assert_eq!(cursor.position(), WIRE_HEADER_BYTES as u64);
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
