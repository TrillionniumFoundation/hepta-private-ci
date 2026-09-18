use super::*;

fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

#[test]
fn v2_round_trip_and_frozen_bytes_are_exact() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        id("s")?,
        id("p")?,
        Generation::new(1)?,
        vec![1, 2, 3],
    )?;
    let golden: [u8; 59] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x01, 0x24, 0xc2, 0x25, 0xcf, 0x24, 0x2f, 0xbe, 0xf3, 0xf1, 0x42,
        0x8a, 0xf4, 0x82, 0x70, 0x91, 0x79, 0x3d, 0x13, 0xc0, 0x51, 0xc4, 0xf0, 0x19, 0x79,
        0xa4, 0x76, 0x33, 0xf0, 0x72, 0x9f, 0x1d, 0x5e, 0x00, 0x00, 0x00, 0x03, b's', b'p',
        0x01, 0x02, 0x03,
    ];
    assert_eq!(envelope.encode(), golden);
    assert_eq!(WireEnvelopeV2::decode(&golden)?, envelope);
    Ok(())
}

#[test]
fn metadata_mutation_is_bound_by_v2_digest() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        id("schema.a")?,
        id("producer.a")?,
        Generation::new(7)?,
        b"payload".to_vec(),
    )?;
    let encoded = envelope.encode();

    let mut schema_changed = encoded.clone();
    schema_changed[54 + "schema.".len()] = b'b';
    assert!(matches!(
        WireEnvelopeV2::decode(&schema_changed),
        Err(WireV2Error::DigestMismatch { .. })
    ));

    let producer_offset = 54 + "schema.a".len();
    let mut producer_changed = encoded.clone();
    producer_changed[producer_offset + "producer.".len()] = b'b';
    assert!(matches!(
        WireEnvelopeV2::decode(&producer_changed),
        Err(WireV2Error::DigestMismatch { .. })
    ));

    let mut generation_changed = encoded;
    generation_changed[17] ^= 1;
    assert!(matches!(
        WireEnvelopeV2::decode(&generation_changed),
        Err(WireV2Error::DigestMismatch { .. })
    ));
    Ok(())
}

#[test]
fn v2_digest_is_not_only_a_payload_digest() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        id("hepta.test.v2")?,
        id("platform.wire")?,
        Generation::new(2)?,
        b"same-payload".to_vec(),
    )?;
    assert_ne!(
        envelope.frame_digest(),
        Digest32::of_bytes(envelope.payload())
    );
    Ok(())
}

#[test]
fn every_v2_truncation_rejects() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        id("hepta.test.v2")?,
        id("platform.wire")?,
        Generation::new(u64::MAX)?,
        b"bounded".to_vec(),
    )?;
    let encoded = envelope.encode();
    for length in 0..encoded.len() {
        assert!(WireEnvelopeV2::decode(&encoded[..length]).is_err());
    }
    assert_eq!(WireEnvelopeV2::decode(&encoded)?, envelope);
    Ok(())
}
