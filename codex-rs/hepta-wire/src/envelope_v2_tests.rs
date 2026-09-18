use super::*;

fn envelope() -> Result<WireEnvelopeV2, Box<dyn Error>> {
    Ok(WireEnvelopeV2::new(
        StableId::new("hepta.test.v2")?,
        StableId::new("platform.wire")?,
        Generation::new(7)?,
        b"metadata-bound-payload".to_vec(),
    )?)
}

#[test]
fn v2_round_trip_is_exact() -> Result<(), Box<dyn Error>> {
    let envelope = envelope()?;
    assert_eq!(WireEnvelopeV2::decode(&envelope.encode())?, envelope);
    Ok(())
}

#[test]
fn metadata_and_payload_mutations_fail_digest_validation() -> Result<(), Box<dyn Error>> {
    let encoded = envelope()?.encode();
    for index in [54_usize, 54 + "hepta.test.v2".len(), encoded.len() - 1] {
        let mut tampered = encoded.clone();
        tampered[index] = match tampered[index] {
            b'a' => b'b',
            _ => b'a',
        };
        assert!(matches!(
            WireEnvelopeV2::decode(&tampered),
            Err(WireV2Error::FrameDigestMismatch { .. })
                | Err(WireV2Error::IdentityEncoding)
        ));
    }

    let mut generation = encoded;
    generation[17] ^= 1;
    assert!(matches!(
        WireEnvelopeV2::decode(&generation),
        Err(WireV2Error::FrameDigestMismatch { .. })
    ));
    Ok(())
}

#[test]
fn v2_matches_independent_frozen_vector() -> Result<(), Box<dyn Error>> {
    let golden: [u8; 59] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x01, 0x42, 0x0c, 0xba, 0xa9, 0xb4, 0x71, 0x7b, 0x30, 0x99, 0xa3, 0xac, 0x45,
        0xa1, 0x54, 0x5b, 0x41, 0x36, 0x3a, 0x35, 0x11, 0xeb, 0x58, 0x2a, 0xfa, 0x20, 0xf6, 0x10,
        0x7e, 0x91, 0x6c, 0x4d, 0x2d, 0x00, 0x00, 0x00, 0x03, b's', b'p', 0x01, 0x02, 0x03,
    ];
    let expected = WireEnvelopeV2::new(
        StableId::new("s")?,
        StableId::new("p")?,
        Generation::new(1)?,
        vec![1, 2, 3],
    )?;
    assert_eq!(expected.encode(), golden);
    assert_eq!(WireEnvelopeV2::decode(&golden)?, expected);
    Ok(())
}
