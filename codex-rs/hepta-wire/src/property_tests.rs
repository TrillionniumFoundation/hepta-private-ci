use std::panic::catch_unwind;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DecodedFrame;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireFrameDecoder;
use crate::WireV2Error;

struct XorShift64(u64);

impl XorShift64 {
    fn next(&mut self) -> u64 {
        let mut value = self.0;
        value ^= value << 13;
        value ^= value >> 7;
        value ^= value << 17;
        self.0 = value;
        value
    }

    fn fill(&mut self, bytes: &mut [u8]) {
        for byte in bytes {
            *byte = self.next() as u8;
        }
    }
}

fn schema() -> StableId {
    StableId::new("schema.test").expect("schema")
}

fn producer() -> StableId {
    StableId::new("property.producer").expect("producer")
}

#[test]
fn deterministic_property_round_trips_cover_many_payloads() {
    let mut rng = XorShift64(0x8a5c_37d2_f1e4_09b7);
    for iteration in 0..512_u64 {
        let length = usize::try_from((rng.next() % 4096) + 1).expect("bounded length");
        let mut payload = vec![0_u8; length];
        rng.fill(&mut payload);
        let generation = Generation::new(iteration + 1).expect("generation");

        let v1 = WireEnvelope::new(
            schema(),
            producer(),
            generation,
            payload.clone(),
        )
        .expect("V1 envelope");
        let v1_bytes = v1.encode();
        let v1_decoded = WireEnvelope::decode(&v1_bytes).expect("V1 decode");
        assert_eq!(v1_decoded, v1);
        assert_eq!(v1_decoded.encode(), v1_bytes);

        let v2 = WireEnvelopeV2::new(schema(), producer(), generation, payload)
            .expect("V2 envelope");
        let v2_bytes = v2.encode();
        let v2_decoded = WireEnvelopeV2::decode(&v2_bytes).expect("V2 decode");
        assert_eq!(v2_decoded, v2);
        assert_eq!(v2_decoded.encode(), v2_bytes);
    }
}

#[test]
fn arbitrary_bytes_never_panic_whole_frame_or_stream_decoders() {
    let mut rng = XorShift64(0x2d71_84ce_9b30_f165);
    for _ in 0..2_048 {
        let length = usize::try_from(rng.next() % 2048).expect("bounded length");
        let mut bytes = vec![0_u8; length];
        rng.fill(&mut bytes);
        let result = catch_unwind(|| {
            let _ = WireEnvelope::decode(&bytes);
            let _ = WireEnvelopeV2::decode(&bytes);
            let mut decoder = WireFrameDecoder::new();
            let midpoint = bytes.len() / 2;
            let _ = decoder.push(&bytes[..midpoint]);
            let _ = decoder.push(&bytes[midpoint..]);
        });
        assert!(result.is_ok());
    }
}

#[test]
fn v2_metadata_mutations_are_integrity_failures_not_silent_reinterpretations() {
    let envelope = WireEnvelopeV2::new(
        schema(),
        producer(),
        Generation::new(7).expect("generation"),
        b"metadata-bound".to_vec(),
    )
    .expect("V2 envelope");
    let encoded = envelope.encode();

    let mut schema_mutation = encoded.clone();
    schema_mutation[54] = b't';
    assert!(matches!(
        WireEnvelopeV2::decode(&schema_mutation),
        Err(WireV2Error::DigestMismatch { .. })
    ));

    let mut producer_mutation = encoded.clone();
    let producer_start = 54 + schema().as_str().len();
    producer_mutation[producer_start] = b'q';
    assert!(matches!(
        WireEnvelopeV2::decode(&producer_mutation),
        Err(WireV2Error::DigestMismatch { .. })
    ));

    let mut generation_mutation = encoded;
    generation_mutation[17] ^= 1;
    assert!(matches!(
        WireEnvelopeV2::decode(&generation_mutation),
        Err(WireV2Error::DigestMismatch { .. })
    ));
}

#[test]
fn streaming_property_handles_every_chunk_size() {
    let frame = WireEnvelopeV2::new(
        schema(),
        producer(),
        Generation::new(11).expect("generation"),
        vec![0xa5; 1024],
    )
    .expect("V2 envelope")
    .encode();

    for chunk_size in 1..=97 {
        let mut decoder = WireFrameDecoder::new();
        let mut offset = 0_usize;
        let mut decoded = None;
        while offset < frame.len() {
            let end = (offset + chunk_size).min(frame.len());
            let progress = decoder.push(&frame[offset..end]).expect("stream decode");
            assert_eq!(progress.consumed, end - offset);
            offset = end;
            if let Some(frame) = progress.frame {
                decoded = Some(frame);
            }
        }
        assert!(matches!(decoded, Some(DecodedFrame::V2(_))));
        assert_eq!(decoder.buffered_len(), 0);
    }
}
