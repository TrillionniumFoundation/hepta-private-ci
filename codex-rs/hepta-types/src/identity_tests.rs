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
fn id_profiles_bind_namespace_without_normalization() {
    let execution = validate_id("execution:run-1", IdProfileV1::Execution);
    let Ok(execution) = execution else {
        panic!("execution profile rejected a valid identifier");
    };
    assert_eq!(execution.as_str(), "execution:run-1");
    assert_eq!(
        validate_id("artifact:run-1", IdProfileV1::Execution),
        Err(IdentityError::ProfileMismatch(IdProfileV1::Execution))
    );
    assert_eq!(
        validate_id("a:b:c", IdProfileV1::Namespaced),
        Err(IdentityError::ProfileMismatch(IdProfileV1::Namespaced))
    );
    assert!(validate_id("schema:signal-v1", IdProfileV1::Schema).is_ok());
    assert!(validate_id("normalization:unit-range-v1", IdProfileV1::Normalization).is_ok());
    assert!(validate_id("receipt:conversion-1", IdProfileV1::Receipt).is_ok());
    assert!(validate_id("artifact:model-1", IdProfileV1::Artifact).is_ok());
    assert_eq!(
        IdProfileV1::from_id("execution-id-v0"),
        Err(IdentityError::UnknownProfile)
    );
}

#[test]
fn stable_id_boundaries_and_alphabet_are_exhaustive() {
    let exact = "a".repeat(STABLE_ID_MAX_BYTES);
    assert!(validate_id(&exact, IdProfileV1::Stable).is_ok());
    let too_large = "a".repeat(STABLE_ID_MAX_BYTES + 1);
    assert_eq!(
        validate_id(&too_large, IdProfileV1::Stable),
        Err(IdentityError::Bounded(BoundedValueError::TooLarge {
            actual: STABLE_ID_MAX_BYTES + 1,
            maximum: STABLE_ID_MAX_BYTES,
        }))
    );

    for byte in 0_u8..=127 {
        let allowed =
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':');
        let value = format!("a{}z", char::from(byte));
        if allowed {
            assert!(validate_id(&value, IdProfileV1::Stable).is_ok());
        } else {
            assert_eq!(
                validate_id(&value, IdProfileV1::Stable),
                Err(IdentityError::InvalidCharacter)
            );
        }
    }
    assert_eq!(
        validate_id("é", IdProfileV1::Stable),
        Err(IdentityError::InvalidCharacter)
    );
}

#[test]
fn monotonic_values_reject_overflow() {
    let generation = Generation::new(u64::MAX);
    let Ok(generation) = generation else {
        panic!("maximum nonzero generation rejected");
    };
    assert_eq!(generation.next(), Err(IdentityError::Overflow));
    let revision = Revision::new(1);
    let Ok(revision) = revision else {
        panic!("valid revision rejected");
    };
    assert_eq!(revision.next().map(Revision::get), Ok(2));
}

#[test]
fn qualification_authority_posture_is_type_locked() {
    assert!(!AuthorityPosture::DENY_ALL.grants_any());
    let proof = NonAuthorizingPosture::try_from(AuthorityPosture::DENY_ALL);
    assert_eq!(proof, Ok(NonAuthorizingPosture::DENY_ALL));

    let mut tampered = AuthorityPosture::DENY_ALL;
    tampered.runtime = true;
    assert_eq!(
        NonAuthorizingPosture::try_from(tampered),
        Err(NonAuthorizingPostureError::AuthorityGranted)
    );
    assert!(!NonAuthorizingPosture::DENY_ALL.grants_any());
    assert_eq!(
        NonAuthorizingPosture::DENY_ALL.as_legacy(),
        AuthorityPosture::DENY_ALL
    );
}
