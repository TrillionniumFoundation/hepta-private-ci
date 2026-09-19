use super::*;

#[test]
fn sha256_round_trip_is_canonical() {
    let digest = Digest32::of_bytes(b"hepta");
    let encoded = digest.to_string();
    let parsed = encoded.parse::<Digest32>();
    let Ok(parsed) = parsed else {
        panic!("canonical digest did not parse");
    };
    assert_eq!(parsed, digest);
    assert_eq!(encoded.len(), 64);
}

#[test]
fn uppercase_and_wrong_length_fail_closed() {
    assert_eq!("00".parse::<Digest32>(), Err(DigestParseError::Length(2)));
    let uppercase = "A".repeat(64);
    assert_eq!(
        uppercase.parse::<Digest32>(),
        Err(DigestParseError::Character(0))
    );
}

#[test]
fn lowercase_hex_boundaries_and_invalid_nibbles_are_exhaustive() {
    let zero = "0".repeat(64).parse::<Digest32>();
    assert_eq!(zero, Ok(Digest32::ZERO));

    let ff = "f".repeat(64).parse::<Digest32>();
    assert!(ff.is_ok());

    for invalid in [b'G', b'Z', b'g', b'z', b'/', b':'] {
        let mut value = vec![b'0'; 64];
        value[31] = invalid;
        let value = String::from_utf8(value).expect("ASCII test vector");
        assert_eq!(
            value.parse::<Digest32>(),
            Err(DigestParseError::Character(31))
        );
    }
    assert_eq!(
        "0".repeat(63).parse::<Digest32>(),
        Err(DigestParseError::Length(63))
    );
    assert_eq!(
        "0".repeat(65).parse::<Digest32>(),
        Err(DigestParseError::Length(65))
    );
}

#[test]
fn byte_hash_is_deterministic_and_input_sensitive() {
    assert_eq!(Digest32::of_bytes(b"same"), Digest32::of_bytes(b"same"));
    assert_ne!(Digest32::of_bytes(b"same"), Digest32::of_bytes(b"same\0"));
}
