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
}

#[test]
fn id_profiles_and_namespaces_are_explicit_and_canonical() {
    assert!(validate_id("platform.types", IdProfileV1::Module).is_ok());
    assert_eq!(
        validate_id("Platform.Types", IdProfileV1::Module),
        Err(IdentityError::InvalidCharacter)
    );
    assert!(validate_id("platform.types:receipt-1", IdProfileV1::Namespaced).is_ok());
    assert_eq!(
        validate_id("platform.types::receipt", IdProfileV1::Namespaced),
        Err(IdentityError::NonCanonical)
    );
    assert_eq!(
        IdProfileV1::from_id("future-v2"),
        Err(IdentityError::UnknownProfile)
    );

    let namespace = IdNamespaceV1::new("platform.types");
    let Ok(namespace) = namespace else {
        panic!("module namespace fixture should be valid");
    };
    let qualified = namespace.qualify("receipt-1");
    let Ok(qualified) = qualified else {
        panic!("namespaced fixture should be valid");
    };
    assert_eq!(qualified.as_str(), "platform.types:receipt-1");
    assert!(namespace.qualify("Receipt-1").is_err());
}

#[test]
fn stable_profile_exhaustively_matches_the_v1_ascii_alphabet() {
    for byte in 1_u8..=127 {
        let value = String::from(char::from(byte));
        let expected = byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':');
        assert_eq!(
            StableId::new(value).is_ok(),
            expected,
            "unexpected StableId result for ASCII byte {byte}"
        );
    }
}

#[test]
fn identity_bounds_and_monotonic_overflow_fail_closed() {
    assert!(StableId::new("a".repeat(128)).is_ok());
    assert_eq!(
        StableId::new("a".repeat(129)),
        Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: 129,
            maximum: 128,
        }))
    );
    assert_eq!(
        Generation::new(u64::MAX).and_then(Generation::next),
        Err(IdentityError::Overflow)
    );
    assert_eq!(
        Revision::new(u64::MAX).and_then(Revision::next),
        Err(IdentityError::Overflow)
    );
    assert_eq!(
        LogicalSequence::new(u64::MAX).and_then(LogicalSequence::next),
        Err(IdentityError::Overflow)
    );
}

#[test]
fn authority_posture_cannot_represent_a_grant() {
    assert!(!AuthorityPosture::DENY_ALL.grants_any());
    assert_eq!(
        AuthorityPosture::try_from_flags(AuthorityFlagsV1::default()),
        Ok(AuthorityPosture::DENY_ALL)
    );
    assert_eq!(
        AuthorityPosture::try_from_flags(AuthorityFlagsV1 {
            runtime: true,
            ..AuthorityFlagsV1::default()
        }),
        Err(AuthorityPostureError::GrantRequested)
    );
    assert!(!AuthorityPosture::DENY_ALL.flags().grants_any());
}
