use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn generation() -> Generation {
    Generation::new(5).expect("test generation")
}

#[test]
fn decoder_accepts_one_byte_chunks_without_buffering_beyond_one_frame() {
    let envelope = WireEnvelopeV2::new(
        id("stream.v2"),
        id("producer"),
        generation(),
        vec![7; 257],
    )
    .expect("valid envelope");
    let encoded = envelope.encode();
    let mut decoder = WireStreamDecoder::new();
    let mut decoded = None;
    for byte in &encoded {
        let progress = decoder
            .push(std::slice::from_ref(byte))
            .expect("stream push");
        assert_eq!(progress.consumed, 1);
        assert!(decoder.buffered_len() <= MAX_WIRE_FRAME_BYTES);
        if progress.frame.is_some() {
            decoded = progress.frame;
        }
    }
    assert_eq!(decoded, Some(DecodedEnvelope::V2(envelope)));
    assert_eq!(decoder.buffered_len(), 0);
}

#[test]
fn decoder_stops_exactly_at_frame_boundary_and_leaves_next_frame_unconsumed() {
    let first = WireEnvelope::new(
        id("stream.v1"),
        id("p1"),
        generation(),
        vec![1, 2, 3],
    )
    .expect("v1 envelope")
    .encode();
    let second = WireEnvelopeV2::new(
        id("stream.v2"),
        id("p2"),
        generation(),
        vec![4, 5, 6],
    )
    .expect("v2 envelope")
    .encode();
    let mut joined = first.clone();
    joined.extend_from_slice(&second);

    let mut decoder = WireStreamDecoder::new();
    let first_progress = decoder.push(&joined).expect("first frame");
    assert_eq!(first_progress.consumed, first.len());
    assert!(matches!(
        first_progress.frame,
        Some(DecodedEnvelope::V1(_))
    ));

    let second_progress = decoder
        .push(&joined[first_progress.consumed..])
        .expect("second frame");
    assert_eq!(second_progress.consumed, second.len());
    assert!(matches!(
        second_progress.frame,
        Some(DecodedEnvelope::V2(_))
    ));
}

#[test]
fn oversized_header_rejects_before_body_allocation() {
    let mut header = vec![0_u8; 54];
    header[..4].copy_from_slice(b"HPTA");
    header[4..6].copy_from_slice(&2_u16.to_be_bytes());
    header[6..8].copy_from_slice(&1_u16.to_be_bytes());
    header[8..10].copy_from_slice(&1_u16.to_be_bytes());
    header[10..18].copy_from_slice(&1_u64.to_be_bytes());
    header[50..54].copy_from_slice(&u32::MAX.to_be_bytes());
    let mut decoder = WireStreamDecoder::new();
    assert_eq!(
        decoder.push(&header),
        Err(StreamDecodeError::PayloadLength)
    );
    assert_eq!(decoder.buffered_len(), 54);
}
