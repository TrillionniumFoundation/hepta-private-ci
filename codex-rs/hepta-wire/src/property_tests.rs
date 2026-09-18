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

fn id(value: String) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("generated identifier rejected");
    };
    value
}

fn generation(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("generated generation rejected");
    };
    value
}

#[test]
fn generated_valid_envelopes_round_trip_and_stream_exactly() {
    let mut random = XorShift64(0x4f7d_31b2_91ac_e055);
    for index in 1_u64..=512 {
        let payload_len = usize::try_from((random.next() % 2048) + 1).unwrap_or(1);
        let payload = random.bytes(payload_len);
        let schema = id(format!("property.schema.{index}"));
        let producer = id(format!("property.producer.{index}"));
        let generation = generation(index);

        let v1_result = WireEnvelope::new(
            schema.clone(),
            producer.clone(),
            generation,
            payload.clone(),
        );
        let Ok(v1) = v1_result else {
            panic!("generated v1 envelope rejected");
        };
        let v2_result = WireEnvelopeV2::new(schema, producer, generation, payload);
        let Ok(v2) = v2_result else {
            panic!("generated v2 envelope rejected");
        };
        assert_eq!(WireEnvelope::decode(&v1.encode()), Ok(v1));
        assert_eq!(WireEnvelopeV2::decode(&v2.encode()), Ok(v2.clone()));

        let encoded = v2.encode();
        let split = usize::try_from(random.next()).unwrap_or(0) % encoded.len();
        let mut decoder = WireStreamDecoder::new();
        let first_result = decoder.push(&encoded[..split]);
        let Ok(first) = first_result else {
            panic!("generated first stream chunk rejected");
        };
        assert!(first.frame.is_none());
        let second_result = decoder.push(&encoded[split..]);
        let Ok(second) = second_result else {
            panic!("generated second stream chunk rejected");
        };
        assert_eq!(second.frame, Some(DecodedEnvelope::V2(v2)));
    }
}

#[test]
fn arbitrary_byte_inputs_never_panic_or_expand_stream_buffer_past_bound() {
    let mut random = XorShift64(0xd9ae_72c4_5518_0b33);
    for _ in 0..4096 {
        let length = usize::try_from(random.next() % 4096).unwrap_or(0);
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
    let v2_result = WireEnvelopeV2::new(
        id("property.v2".to_string()),
        id("producer.v2".to_string()),
        generation(9),
        vec![1, 2, 3, 4],
    );
    let Ok(envelope) = v2_result else {
        panic!("valid v2 envelope rejected");
    };
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
