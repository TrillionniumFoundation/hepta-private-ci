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
fn digest_parser_deterministic_fuzz_corpus_is_total_and_strict() {
    let mut state = 0xd1b5_4a32_d192_ed03_u64;
    for length in 0..=70 {
        for _ in 0..32 {
            let mut value = String::with_capacity(length);
            for _ in 0..length {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let byte = 0x20_u8 + u8::try_from(state % 95).unwrap_or(0);
                value.push(char::from(byte));
            }
            let accepted = value.len() == 64
                && value
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'));
            assert_eq!(
                value.parse::<Digest32>().is_ok(),
                accepted,
                "digest parser admission diverged for {value:?}"
            );
        }
    }
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
