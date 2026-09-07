use super::*;

fn frame(payload: Vec<u8>) -> Result<WireEnvelope, Box<dyn Error>> {
    Ok(WireEnvelope::new(
        StableId::new("w0.message.v1")?,
        StableId::new("w0.producer")?,
        Generation::new(u64::MAX)?,
        payload,
    )?)
}

#[test]
fn every_truncation_rejects_without_reconstructing_an_envelope() -> Result<(), Box<dyn Error>> {
    let envelope = frame(b"frozen-contract-fixture".to_vec())?;
    let encoded = envelope.encode();
    for length in 0..encoded.len() {
        assert!(
            WireEnvelope::decode(&encoded[..length]).is_err(),
            "prefix {length}"
        );
    }
    let decoded = WireEnvelope::decode(&encoded)?;
    assert!(decoded == envelope);
    assert!(decoded.encode() == encoded);
    Ok(())
}

#[test]
fn maximum_payload_and_u64_generation_round_trip_exactly() -> Result<(), Box<dyn Error>> {
    let envelope = WireEnvelope::new(
        StableId::new("s".repeat(128))?,
        StableId::new("p".repeat(128))?,
        Generation::new(u64::MAX)?,
        vec![0xa5; MAX_WIRE_PAYLOAD_BYTES],
    )?;
    let decoded = WireEnvelope::decode(&envelope.encode())?;
    assert!(decoded == envelope);
    assert!(decoded.generation().get() == u64::MAX);
    assert!(frame(vec![0; MAX_WIRE_PAYLOAD_BYTES + 1]).is_err());
    Ok(())
}

#[test]
fn v1_frame_matches_frozen_bytes_not_only_its_own_encoder() -> Result<(), Box<dyn Error>> {
    // HPTA, V1, two one-byte IDs, generation 1, SHA-256([1, 2, 3]),
    // three payload bytes, then schema/producer/payload. This vector is not
    // produced by the implementation under test.
    let golden: [u8; 59] = [
        0x48, 0x50, 0x54, 0x41, 0x00, 0x01, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x01, 0x03, 0x90, 0x58, 0xc6, 0xf2, 0xc0, 0xcb, 0x49, 0x2c, 0x53, 0x3b, 0x0a,
        0x4d, 0x14, 0xef, 0x77, 0xcc, 0x0f, 0x78, 0xab, 0xcc, 0xce, 0xd5, 0x28, 0x7d, 0x84, 0xa1,
        0xa2, 0x01, 0x1c, 0xfb, 0x81, 0x00, 0x00, 0x00, 0x03, b's', b'p', 0x01, 0x02, 0x03,
    ];
    let expected = WireEnvelope::new(
        StableId::new("s")?,
        StableId::new("p")?,
        Generation::new(1)?,
        vec![1, 2, 3],
    )?;
    assert!(expected.encode() == golden);
    assert!(WireEnvelope::decode(&golden)? == expected);
    Ok(())
}

#[test]
fn invalid_header_bounds_and_generation_reject() -> Result<(), Box<dyn Error>> {
    let encoded = frame(vec![7])?.encode();
    for start in [6, 8] {
        for length in [0_u16, 129, u16::MAX] {
            let mut invalid = encoded.clone();
            invalid[start..start + 2].copy_from_slice(&length.to_be_bytes());
            assert!(matches!(
                WireEnvelope::decode(&invalid),
                Err(WireError::IdentityLength)
            ));
        }
    }
    let mut zero_generation = encoded.clone();
    zero_generation[10..18].fill(0);
    assert!(matches!(
        WireEnvelope::decode(&zero_generation),
        Err(WireError::Generation)
    ));
    for length in [0_u32, MAX_WIRE_PAYLOAD_BYTES as u32 + 1, u32::MAX] {
        let mut invalid = encoded.clone();
        invalid[50..54].copy_from_slice(&length.to_be_bytes());
        assert!(matches!(
            WireEnvelope::decode(&invalid),
            Err(WireError::PayloadLength)
        ));
    }
    Ok(())
}

#[test]
fn identities_remain_exact_not_normalized_and_corrupt_payloads_reject() -> Result<(), Box<dyn Error>>
{
    let encoded = frame(vec![0; MAX_WIRE_PAYLOAD_BYTES])?.encode();
    for replacement in [b' ', b'/', b'\n', 0xff] {
        let mut invalid = encoded.clone();
        invalid[HEADER_FIXED_BYTES] = replacement;
        assert!(matches!(
            WireEnvelope::decode(&invalid),
            Err(WireError::IdentityEncoding)
        ));
    }
    let mut corrupt = encoded;
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    assert!(matches!(
        WireEnvelope::decode(&corrupt),
        Err(WireError::DigestMismatch { .. })
    ));
    Ok(())
}
