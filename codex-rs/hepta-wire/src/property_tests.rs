use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::*;

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

    fn bytes(&mut self, length: usize) -> Vec<u8> {
        (0..length).map(|_| self.next() as u8).collect()
    }
}

#[test]
fn generated_valid_envelopes_round_trip_and_stream_exactly() {
    let mut random = XorShift64(0x4f7d_31b2_91ac_e055);
    for index in 1_u64..=512 {
        let payload_len =
            usize::try_from((random.next() % 2048) + 1).expect("bounded length");
        let payload = random.bytes(payload_len);
        let schema = StableId::new(format!("property.schema.{index}")).expect("schema");
        let producer =
            StableId::new(format!("property.producer.{index}")).expect("producer");
        let generation = Generation::new(index).expect("generation");

        let v1 = WireEnvelope::new(
            schema.clone(),
            producer.clone(),
            generation,
            payload.clone(),
        )
        .expect("v1 envelope");
        let v2 =
            WireEnvelopeV2::new(schema, producer, generation, payload).expect("v2 envelope");
        assert_eq!(WireEnvelope::decode(&v1.encode()), Ok(v1));
        assert_eq!(WireEnvelopeV2::decode(&v2.encode()), Ok(v2.clone()));

        let encoded = v2.encode();
        let split = usize::try_from(random.next()).unwrap_or(0) % encoded.len();
        let mut decoder = WireStreamDecoder::new();
        let first = decoder.push(&encoded[..split]).expect("first chunk");
        assert!(first.frame.is_none());
        let second = decoder.push(&encoded[split..]).expect("second chunk");
        assert_eq!(second.frame, Some(DecodedEnvelope::V2(v2)));
    }
}

#[test]
fn arbitrary_byte_inputs_never_panic_or_expand_stream_buffer_past_bound() {
    let mut random = XorShift64(0xd9ae_72c4_5518_0b33);
    for _ in 0..4096 {
        let length = usize::try_from(random.next() % 4096).expect("bounded length");
        let bytes = random.bytes(length);
        assert!(std::panic::catch_unwind(|| WireEnvelope::decode(&bytes)).is_ok());
        assert!(std::panic::catch_unwind(|| WireEnvelopeV2::decode(&bytes)).is_ok());

        let mut decoder = WireStreamDecoder::new();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            decoder.push(&bytes)
        }));
        assert!(result.is_ok());
        assert!(decoder.buffered_len() <= MAX_WIRE_FRAME_BYTES);
    }
}

#[test]
fn v2_metadata_mutation_is_detected_without_reinterpreting_v1() {
    let envelope = WireEnvelopeV2::new(
        StableId::new("property.v2").expect("schema"),
        StableId::new("producer.v2").expect("producer"),
        Generation::new(9).expect("generation"),
        vec![1, 2, 3, 4],
    )
    .expect("v2 envelope");
    let encoded = envelope.encode();
    let schema_offset = 54;
    let producer_offset = schema_offset + envelope.schema().as_str().len();
    for index in [schema_offset, producer_offset, 17, encoded.len() - 1] {
        let mut mutated = encoded.clone();
        mutated[index] ^= 1;
        assert!(matches!(
            WireEnvelopeV2::decode(&mutated),
            Err(WireV2Error::FrameDigestMismatch { .. })
        ));
    }

    let mut v1_tag = encoded;
    v1_tag[5] = 1;
    assert!(WireEnvelope::decode(&v1_tag).is_err());
    assert_eq!(
        WireEnvelopeV2::decode(&v1_tag),
        Err(WireV2Error::Version(1))
    );
}
