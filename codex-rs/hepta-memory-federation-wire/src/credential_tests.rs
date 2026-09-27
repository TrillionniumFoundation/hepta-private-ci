use codex_hepta_types::StableId;

use super::*;

const NOW: u64 = 5_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn credential(
    sender: &str,
    receiver: &str,
    key: &str,
    generation: u64,
    byte: u8,
) -> PeerCredentialV1 {
    PeerCredentialV1::new(
        id(sender),
        id(receiver),
        id(key),
        generation,
        NOW - 100,
        NOW + 100_000,
        [byte; FEDERATION_MAC_KEY_BYTES],
    )
    .expect("credential")
}

#[test]
fn rotation_and_revocation_keep_one_secret_and_a_monotone_tombstone() {
    let mut registry = PeerCredentialRegistryV1::with_limits(4, 2).expect("registry");
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 31))
        .expect("enroll");
    assert_eq!(registry.len(), 1);
    assert_eq!(registry.active_len(), 1);

    registry
        .rotate(credential("peer-a", "peer-b", "key-a-b", 2, 32))
        .expect("rotate");
    assert_eq!(registry.len(), 1);
    assert_eq!(registry.active_len(), 1);
    assert!(matches!(
        registry.require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1, NOW),
        Err(CredentialError::Revoked)
    ));
    registry
        .require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 2, NOW)
        .expect("generation two");

    registry
        .revoke(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 2)
        .expect("revoke");
    assert_eq!(registry.len(), 1);
    assert_eq!(registry.active_len(), 0);
    assert!(matches!(
        registry.require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 2, NOW),
        Err(CredentialError::Revoked)
    ));

    registry
        .rotate(credential("peer-a", "peer-b", "key-a-b", 3, 33))
        .expect("rekey after revoke");
    assert_eq!(registry.len(), 1);
    assert_eq!(registry.active_len(), 1);
    registry
        .require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 3, NOW)
        .expect("generation three");
}

#[test]
fn one_peer_pair_cannot_exhaust_shared_credential_capacity() {
    let mut registry = PeerCredentialRegistryV1::with_limits(3, 1).expect("registry");
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b-1", 1, 41))
        .expect("first pair key");
    assert!(matches!(
        registry.enroll(credential("peer-a", "peer-b", "key-a-b-2", 1, 42)),
        Err(CredentialError::PeerPairCapacityExhausted)
    ));

    registry
        .enroll(credential("peer-c", "peer-b", "key-c-b", 1, 43))
        .expect("independent sender retains capacity");
    registry
        .enroll(credential("peer-d", "peer-b", "key-d-b", 1, 44))
        .expect("third shared slot");
    assert!(matches!(
        registry.enroll(credential("peer-e", "peer-b", "key-e-b", 1, 45)),
        Err(CredentialError::CapacityExhausted)
    ));
    assert_eq!(registry.len(), 3);
    assert_eq!(registry.active_len(), 3);
}

#[test]
fn invalid_or_widened_registry_limits_are_rejected() {
    assert!(matches!(
        PeerCredentialRegistryV1::with_limits(0, 1),
        Err(CredentialError::InvalidCapacity)
    ));
    assert!(matches!(
        PeerCredentialRegistryV1::with_limits(1, 2),
        Err(CredentialError::InvalidCapacity)
    ));
    assert!(matches!(
        PeerCredentialRegistryV1::with_limits(MAX_FEDERATION_CREDENTIAL_KEYS + 1, 1),
        Err(CredentialError::InvalidCapacity)
    ));
}

#[test]
fn tombstoned_key_requires_explicit_strict_rotation() {
    let mut registry = PeerCredentialRegistryV1::with_limits(2, 2).expect("registry");
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 51))
        .expect("enroll");
    registry
        .revoke(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1)
        .expect("revoke");
    assert!(matches!(
        registry.enroll(credential("peer-a", "peer-b", "key-a-b", 2, 52)),
        Err(CredentialError::DuplicateCredential)
    ));
    assert!(matches!(
        registry.rotate(credential("peer-a", "peer-b", "key-a-b", 1, 53)),
        Err(CredentialError::NonIncreasingGeneration)
    ));
    registry
        .rotate(credential("peer-a", "peer-b", "key-a-b", 2, 54))
        .expect("explicit strict rotation");
}
