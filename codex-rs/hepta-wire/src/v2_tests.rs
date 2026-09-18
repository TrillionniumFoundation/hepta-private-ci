use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier rejected");
    };
    value
}

fn generation_value(value: u64) -> Generation {
    let Ok(value) = Generation::new(value) else {
        panic!("test generation rejected");
    };
    value
}

fn generation() -> Generation {
    generation_value(7)
}

#[test]
fn v2_round_trip_is_exact_and_binds_all_semantic_fields() {
    let result = WireEnvelopeV2::new(
        id("hepta.test.v2"),
        id("platform.wire"),
        generation(),
        b"bounded-payload".to_vec(),
    );
    let Ok(envelope) = result else {
        panic!("valid v2 envelope rejected");
    };
    let encoded = envelope.encode();
    assert_eq!(WireEnvelopeV2::decode(&encoded), Ok(envelope.clone()));

    let schema_offset = HEADER_FIXED_BYTES;
    let producer_offset = schema_offset + envelope.schema().as_str().len();
    let payload_offset = producer_offset + envelope.producer().as_str().len();
    for index in [schema_offset, producer_offset, 17, payload_offset] {
        let mut tampered = encoded.clone();
        tampered[index] ^= 1;
        assert!(matches!(
            WireEnvelopeV2::decode(&tampered),
            Err(WireV2Error::FrameDigestMismatch { .. })
        ));
    }
}

#[test]
fn v2_matches_independent_frozen_vector() {
    let golden: [u8; 59] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x01, 0x24, 0xc2, 0x25, 0xcf, 0x24, 0x2f, 0xbe, 0xf3, 0xf1, 0x42,
        0x8a, 0xf4, 0x82, 0x70, 0x91, 0x79, 0x3d, 0x13, 0xc0, 0x51, 0xc4, 0xf0, 0x19, 0x79,
        0xa4, 0x76, 0x33, 0xf0, 0x72, 0x9f, 0x1d, 0x5e, 0x00, 0x00, 0x00, 0x03, b's', b'p', 0x01,
        0x02, 0x03,
    ];
    let result = WireEnvelopeV2::new(
        id("s"),
        id("p"),
        generation_value(1),
        vec![1, 2, 3],
    );
    let Ok(expected) = result else {
        panic!("valid v2 envelope rejected");
    };
    assert_eq!(expected.encode(), golden);
    assert_eq!(WireEnvelopeV2::decode(&golden), Ok(expected));
}

#[test]
fn v2_rejects_v1_version_and_payload_bounds() {
    let result = WireEnvelopeV2::new(id("s"), id("p"), generation(), vec![1]);
    let Ok(envelope) = result else {
        panic!("valid v2 envelope rejected");
    };
    let mut version = envelope.encode();
    version[5] = 1;
    assert_eq!(
        WireEnvelopeV2::decode(&version),
        Err(WireV2Error::Version(1))
    );
    assert_eq!(
        WireEnvelopeV2::new(id("s"), id("p"), generation(), Vec::new()),
        Err(WireV2Error::PayloadLength)
    );
}
