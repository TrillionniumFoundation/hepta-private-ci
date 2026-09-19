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
    assert_eq!(Generation::new(u64::MAX).and_then(Generation::next), Err(IdentityError::Overflow));
}

#[test]
fn stable_id_ascii_alphabet_is_exhaustive() {
    for byte in 0_u8..=127 {
        let value = format!("x{}", char::from(byte));
        let accepted = StableId::new(value).is_ok();
        let expected =
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':');
        assert_eq!(accepted, expected, "unexpected classification for ASCII {byte}");
    }
}

#[test]
fn id_profiles_bind_namespace_and_local_grammar() {
    let execution = validate_id("execution:run-01", IdProfileV1::EXECUTION);
    let Ok(execution) = execution else {
        panic!("valid execution id rejected");
    };
    assert_eq!(execution.as_str(), "execution:run-01");
    assert_eq!(
        validate_id("schema:run-01", IdProfileV1::EXECUTION),
        Err(IdentityError::NamespaceMismatch)
    );
    assert_eq!(
        validate_id("execution:", IdProfileV1::EXECUTION),
        Err(IdentityError::MissingLocalPart)
    );
    assert_eq!(
        validate_id("execution:nested:part", IdProfileV1::EXECUTION),
        Err(IdentityError::InvalidCharacter)
    );
}

#[test]
fn qualification_authority_posture_is_unforgeable_from_granted_bits() {
    assert!(!AuthorityPosture::DENY_ALL.grants_any());
    assert_eq!(AuthorityPosture::DENY_ALL.encoded_bits(), 0);
    assert_eq!(
        AuthorityPosture::from_untrusted_bits(0),
        Ok(AuthorityPosture::DENY_ALL)
    );
    assert_eq!(
        AuthorityPosture::from_untrusted_bits(1),
        Err(AuthorityPostureError::GrantedBits(1))
    );
    assert_eq!(
        AuthorityPosture::from_untrusted_bits(u8::MAX),
        Err(AuthorityPostureError::GrantedBits(u8::MAX))
    );
}
