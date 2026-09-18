use super::*;

#[test]
fn stable_id_and_generation_are_strict() {
    let id = StableId::new("learning.ledger:episode-1");
    let Ok(id) = id else {
        panic!("valid stable id rejected");
    };
    assert_eq!(id.as_str(), "learning.ledger:episode-1");
    assert_eq!(
        StableId::new("bad/path"),
        Err(IdentityError::InvalidCharacter)
    );
    assert_eq!(Generation::new(0), Err(IdentityError::Zero));
    assert_eq!(
        Generation::new(u64::MAX).and_then(Generation::next),
        Err(IdentityError::Overflow)
    );
}

#[test]
fn id_profiles_enforce_namespaces_without_normalizing() {
    for (profile, value) in [
        (IdProfileV1::Execution, "execution:run-1"),
        (IdProfileV1::Schema, "schema:numeric-signal"),
        (IdProfileV1::Receipt, "receipt:conversion-1"),
        (IdProfileV1::Artifact, "artifact:model-1"),
        (IdProfileV1::Normalization, "normalization:unit-scale"),
    ] {
        assert_eq!(validate_id(value, profile).map(|id| id.to_string()), Ok(value.to_string()));
    }
    assert_eq!(
        validate_id("receipt:wrong", IdProfileV1::Schema),
        Err(IdentityError::NamespaceMismatch)
    );
    assert_eq!(
        validate_id("schema:", IdProfileV1::Schema),
        Err(IdentityError::NamespaceMismatch)
    );
}

#[test]
fn stable_id_ascii_alphabet_is_exhaustively_checked() {
    for byte in 1_u8..=127 {
        let value = char::from(byte).to_string();
        let expected = byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':');
        assert_eq!(StableId::parse(&value).is_ok(), expected, "byte={byte}");
    }
    assert_eq!(StableId::parse("é"), Err(IdentityError::InvalidCharacter));
}

#[test]
fn qualification_authority_posture_is_all_negative() {
    assert!(!AuthorityPosture::DENY_ALL.grants_any());
}
