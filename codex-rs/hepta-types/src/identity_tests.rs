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
    assert!(validate_id("execution:run-1", IdProfileV1::Execution).is_ok());
    assert!(validate_id("schema:numeric-signal", IdProfileV1::Schema).is_ok());
    assert!(validate_id("normalization:identity", IdProfileV1::Normalization).is_ok());
    assert!(validate_id("receipt:conversion-1", IdProfileV1::Receipt).is_ok());
    assert!(validate_id("artifact:model-1", IdProfileV1::Artifact).is_ok());
    assert_eq!(
        validate_id("normalization:numeric-signal", IdProfileV1::Schema),
        Err(IdentityError::NonCanonical)
    );
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
fn stable_profile_deterministic_fuzz_corpus_matches_borrowed_validation() {
    let mut state = 0x9e37_79b9_7f4a_7c15_u64;
    for length in 0..=140 {
        for _ in 0..32 {
            let mut value = String::with_capacity(length);
            for _ in 0..length {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let byte = 0x20_u8 + u8::try_from(state % 95).unwrap_or(0);
                value.push(char::from(byte));
            }
            assert_eq!(
                StableId::new(value.as_str()),
                validate_id(&value, IdProfileV1::Stable),
                "owned and borrowed stable-ID admission diverged for {value:?}"
            );
        }
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
fn authority_posture_rejects_grants_at_raw_wire_ingress() {
    assert!(!AuthorityPosture::DENY_ALL.grants_any());
    assert_eq!(
        AuthorityPosture::try_from_wire_bytes(&[0]),
        Ok(AuthorityPosture::DENY_ALL)
    );
    for bit in 0..8 {
        assert_eq!(
            AuthorityPosture::try_from_wire_bytes(&[1 << bit]),
            Err(AuthorityPostureError::GrantRequested),
            "authority bit {bit} must fail before trusted posture construction"
        );
    }
    assert_eq!(
        AuthorityPosture::try_from_wire_bytes(&[]),
        Err(AuthorityPostureError::InvalidWireLength(0))
    );
    assert_eq!(
        AuthorityPosture::try_from_wire_bytes(&[0, 0]),
        Err(AuthorityPostureError::InvalidWireLength(2))
    );
}

#[test]
fn authority_flags_round_trip_only_as_untrusted_wire_bits() {
    let flags = AuthorityFlagsV1 {
        runtime: true,
        provider_dispatch: true,
        selection: true,
        release: true,
        ..AuthorityFlagsV1::default()
    };
    assert_eq!(AuthorityFlagsV1::from_wire_mask(flags.wire_mask()), flags);
    assert!(flags.grants_any());
    assert_eq!(
        AuthorityPosture::try_from_flags(flags),
        Err(AuthorityPostureError::GrantRequested)
    );
}

#[test]
fn non_authorizing_posture_is_structurally_deny_only() {
    let proof = NonAuthorizingPosture::DENY_ALL;
    assert!(!proof.grants_any());
    assert_eq!(proof.as_legacy(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        NonAuthorizingPosture::from(AuthorityPosture::DENY_ALL),
        NonAuthorizingPosture::DENY_ALL
    );
}
