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
fn uppercase_wrong_length_and_non_hex_fail_closed() {
    assert_eq!("00".parse::<Digest32>(), Err(DigestParseError::Length(2)));
    let uppercase = "A".repeat(64);
    assert_eq!(
        uppercase.parse::<Digest32>(),
        Err(DigestParseError::Character(0))
    );
    let mut invalid = "0".repeat(64);
    invalid.replace_range(31..32, "g");
    assert_eq!(
        invalid.parse::<Digest32>(),
        Err(DigestParseError::Character(31))
    );
}

#[test]
fn zero_and_all_lowercase_nibbles_round_trip() {
    let zero = "0".repeat(64);
    assert_eq!(zero.parse::<Digest32>(), Ok(Digest32::ZERO));

    let source = "0123456789abcdef".repeat(4);
    let parsed = source.parse::<Digest32>();
    let Ok(parsed) = parsed else {
        panic!("lowercase digest alphabet rejected");
    };
    assert_eq!(parsed.to_string(), source);
}
