use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier rejected");
    };
    value
}

fn generation() -> Generation {
    let Ok(value) = Generation::new(5) else {
        panic!("test generation rejected");
    };
    value
}

fn v1(payload: Vec<u8>) -> WireEnvelope {
    let result = WireEnvelope::new(id("stream.v1"), id("p1"), generation(), payload);
    let Ok(value) = result else {
        panic!("valid v1 envelope rejected");
    };
    value
}

fn v2(payload: Vec<u8>) -> WireEnvelopeV2 {
    let result = WireEnvelopeV2::new(id("stream.v2"), id("p2"), generation(), payload);
    let Ok(value) = result else {
        panic!("valid v2 envelope rejected");
    };
    value
}

#[test]
fn decoder_accepts_one_byte_chunks_without_buffering_beyond_one_frame() {
    let envelope = v2(vec![7; 257]);
    let encoded = envelope.encode();
    let mut decoder = WireStreamDecoder::new();
    let mut decoded = None;
    for byte in &encoded {
        let result = decoder.push(std::slice::from_ref(byte));
        let Ok(progress) = result else {
            panic!("stream push rejected");
        };
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
    let first = v1(vec![1, 2, 3]).encode();
    let second = v2(vec![4, 5, 6]).encode();
    let mut joined = first.clone();
    joined.extend_from_slice(&second);

    let first_result = WireStreamDecoder::new().push(&joined);
    let Ok(first_progress) = first_result else {
        panic!("first frame rejected");
    };
    assert_eq!(first_progress.consumed, first.len());
    assert!(matches!(
        first_progress.frame,
        Some(DecodedEnvelope::V1(_))
    ));

    let mut decoder = WireStreamDecoder::new();
    let second_result = decoder.push(&joined[first_progress.consumed..]);
    let Ok(second_progress) = second_result else {
        panic!("second frame rejected");
    };
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

#[test]
fn negotiated_decoder_rejects_other_version_at_header_boundary() {
    let encoded = v1(vec![9]).encode();
    let mut decoder = WireStreamDecoder::for_version(WireVersion::V2);
    assert_eq!(
        decoder.push(&encoded[..54]),
        Err(StreamDecodeError::NegotiatedVersionMismatch {
            expected: WireVersion::V2,
            observed: WireVersion::V1,
        })
    );
    assert_eq!(decoder.negotiated_version(), Some(WireVersion::V2));
    assert_eq!(decoder.buffered_len(), 54);
}
