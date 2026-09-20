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
fn multipart_hash_matches_exact_concatenation() {
    let parts: [&[u8]; 4] = [b"he", b"p", b"", b"ta"];
    assert_eq!(Digest32::of_parts(&parts), Digest32::of_bytes(b"hepta"));
}
