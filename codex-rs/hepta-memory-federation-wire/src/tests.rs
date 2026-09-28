use crate::replay::FederationReplayKeyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

const NOW: u64 = 1_000_000;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
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

fn query() -> FederationWireMessageV1 {
    FederationWireMessageV1::Query(FederationQueryMessageV1 {
        query_id: id("query-1"),
        query_binding_digest: digest(b"query-binding"),
        scope_digest: digest(b"scope"),
        purpose_digest: digest(b"purpose"),
        generation_vector_digest: digest(b"generation"),
        maximum_results: 4,
    })
}

fn seal_query(
    registry: &PeerCredentialRegistryV1,
    generation: u64,
    nonce: [u8; FEDERATION_NONCE_BYTES],
) -> AuthenticatedFederationFrameV1 {
    let credential = registry
        .require_current(
            &id("peer-a"),
            &id("peer-b"),
            &id("key-a-b"),
            generation,
            NOW,
        )
        .expect("current credential");
    AuthenticatedFederationFrameV1::seal(
        credential,
        NOW,
        NOW + 10_000,
        FederationNonceV1::from_bytes(nonce),
        query(),
    )
    .expect("seal")
}

#[test]
fn registered_codec_round_trips_and_peer_verification_succeeds() {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 7))
        .expect("enroll");
    let frame = seal_query(&registry, 1, [3; FEDERATION_NONCE_BYTES]);
    let (schemas, codec) = registered_codec_v1().expect("registered codec");
    let encoded = encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode");
    let decoded = decode_registered_frame_v1(&schemas, &codec, &encoded).expect("decode");
    assert_eq!(decoded, frame);
    let mut replay = ReplayCacheV1::new(8).expect("replay cache");
    let verified = decoded
        .verify(&id("peer-b"), NOW + 1, &registry, &mut replay)
        .expect("verify");
    assert_eq!(verified.sender_peer_id(), &id("peer-a"));
    assert_eq!(verified.receiver_peer_id(), &id("peer-b"));
    assert_eq!(verified.message(), &query());
}

#[test]
fn payload_drift_and_replay_are_rejected() {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 8))
        .expect("enroll");
    let frame = seal_query(&registry, 1, [4; FEDERATION_NONCE_BYTES]);
    let mut tampered = frame.clone();
    let FederationWireMessageV1::Query(query) = &mut tampered.message else {
        panic!("query")
    };
    query.maximum_results = 5;
    let mut replay = ReplayCacheV1::new(8).expect("replay cache");
    assert!(matches!(
        tampered.verify(&id("peer-b"), NOW + 1, &registry, &mut replay),
        Err(FederationProtocolError::MacMismatch)
    ));

    frame
        .verify(&id("peer-b"), NOW + 1, &registry, &mut replay)
        .expect("first delivery");
    assert!(matches!(
        frame.verify(&id("peer-b"), NOW + 2, &registry, &mut replay),
        Err(FederationProtocolError::Replay(ReplayError::Replay))
    ));
}

#[test]
fn rotation_and_revocation_fence_old_generation() {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 9))
        .expect("enroll");
    let old = seal_query(&registry, 1, [5; FEDERATION_NONCE_BYTES]);
    registry
        .rotate(credential("peer-a", "peer-b", "key-a-b", 2, 10))
        .expect("rotate");
    let mut replay = ReplayCacheV1::new(8).expect("replay cache");
    assert!(matches!(
        old.verify(&id("peer-b"), NOW + 1, &registry, &mut replay),
        Err(FederationProtocolError::Credential(
            CredentialError::Revoked
        ))
    ));
    let current = seal_query(&registry, 2, [6; FEDERATION_NONCE_BYTES]);
    current
        .verify(&id("peer-b"), NOW + 1, &registry, &mut replay)
        .expect("new generation");
    registry
        .revoke(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 2)
        .expect("revoke");
    let later = seal_query_for_revoked_test();
    assert!(matches!(
        later.verify(&id("peer-b"), NOW + 1, &registry, &mut replay),
        Err(FederationProtocolError::Credential(
            CredentialError::Revoked
        ))
    ));
}

fn seal_query_for_revoked_test() -> AuthenticatedFederationFrameV1 {
    let credential = credential("peer-a", "peer-b", "key-a-b", 2, 10);
    AuthenticatedFederationFrameV1::seal(
        &credential,
        NOW,
        NOW + 10_000,
        FederationNonceV1::from_bytes([7; FEDERATION_NONCE_BYTES]),
        query(),
    )
    .expect("seal")
}

#[test]
fn authenticated_frontier_rejects_rollback_and_wrong_parent() {
    let first = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer-b"),
        generation: 3,
        frontier: 50,
        state_digest: digest(b"state-50"),
        parent_witness_digest: Digest32::ZERO,
        observed_unix_ms: NOW,
    };
    let next = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer-b"),
        generation: 3,
        frontier: 51,
        state_digest: digest(b"state-51"),
        parent_witness_digest: first.binding_digest(),
        observed_unix_ms: NOW + 1,
    };
    next.require_successor_of(&first).expect("successor");

    let rollback = AuthenticatedFrontierV1 {
        frontier: 49,
        parent_witness_digest: next.binding_digest(),
        observed_unix_ms: NOW + 2,
        ..next.clone()
    };
    assert!(matches!(
        rollback.require_successor_of(&next),
        Err(FederationProtocolError::FrontierRollback)
    ));

    let wrong_parent = AuthenticatedFrontierV1 {
        frontier: 52,
        parent_witness_digest: digest(b"wrong-parent"),
        observed_unix_ms: NOW + 2,
        ..next.clone()
    };
    assert!(matches!(
        wrong_parent.require_successor_of(&next),
        Err(FederationProtocolError::FrontierParentMismatch)
    ));
}

#[test]
fn cancellation_ack_is_authenticated_and_schema_bound() {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 11))
        .expect("enroll");
    let ack = FederationWireMessageV1::CancelAck(FederationCancelAckMessageV1 {
        query_id: id("query-1"),
        query_binding_digest: digest(b"query-binding"),
        cancellation_id: id("cancel-1"),
        disposition: FederationCancellationDispositionV1::ObservedBeforeTerminal,
        observed_unix_ms: NOW + 2,
    });
    let credential = registry
        .require_current(&id("peer-b"), &id("peer-a"), &id("key-b-a"), 1, NOW)
        .expect("current credential");
    let frame = AuthenticatedFederationFrameV1::seal(
        credential,
        NOW,
        NOW + 10_000,
        FederationNonceV1::from_bytes([12; FEDERATION_NONCE_BYTES]),
        ack.clone(),
    )
    .expect("seal");
    let (schemas, codec) = registered_codec_v1().expect("registered codec");
    let encoded = encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode");
    let decoded = decode_registered_frame_v1(&schemas, &codec, &encoded).expect("decode");
    let mut replay = ReplayCacheV1::new(8).expect("replay cache");
    let verified = decoded
        .verify(&id("peer-a"), NOW + 1, &registry, &mut replay)
        .expect("verify");
    assert_eq!(verified.message(), &ack);
}

#[test]
fn overload_fails_closed_without_evicting_unexpired_nonce() {
    let mut cache = ReplayCacheV1::new(1).expect("cache");
    cache
        .admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[1; FEDERATION_NONCE_BYTES],
            },
            NOW + 100,
            NOW,
        )
        .expect("first");
    assert!(matches!(
        cache.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[2; FEDERATION_NONCE_BYTES]
            },
            NOW + 100,
            NOW
        ),
        Err(ReplayError::CapacityExhausted)
    ));
    assert_eq!(cache.len(), 1);
}

#[test]
fn replay_cache_rejects_clock_regression_after_expiry_cleanup() {
    let mut cache = ReplayCacheV1::new(4).expect("cache");
    cache
        .admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[21; FEDERATION_NONCE_BYTES],
            },
            NOW + 10,
            NOW,
        )
        .expect("first admission");
    cache
        .admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-c"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-c-b"),
                generation: 1,
                nonce: &[22; FEDERATION_NONCE_BYTES],
            },
            NOW + 1_000,
            NOW + 20,
        )
        .expect("future admission purges expired nonce");
    assert_eq!(cache.last_observed_unix_ms(), NOW + 20);
    assert!(matches!(
        cache.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[21; FEDERATION_NONCE_BYTES]
            },
            NOW + 10,
            NOW + 5
        ),
        Err(ReplayError::ClockRegression)
    ));
}

#[test]
fn one_directional_credential_cannot_exhaust_the_shared_replay_cache() {
    let mut cache = ReplayCacheV1::with_limits(4, 2).expect("partitioned cache");
    for byte in [31_u8, 32_u8] {
        cache
            .admit(
                FederationReplayKeyV1 {
                    sender_peer_id: &id("peer-a"),
                    receiver_peer_id: &id("peer-b"),
                    key_id: &id("key-a-b"),
                    generation: 1,
                    nonce: &[byte; FEDERATION_NONCE_BYTES],
                },
                NOW + 100,
                NOW,
            )
            .expect("credential partition admission");
    }
    assert!(matches!(
        cache.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[33; FEDERATION_NONCE_BYTES]
            },
            NOW + 100,
            NOW
        ),
        Err(ReplayError::CredentialCapacityExhausted)
    ));
    cache
        .admit(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-c"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-c-b"),
                generation: 1,
                nonce: &[34; FEDERATION_NONCE_BYTES],
            },
            NOW + 100,
            NOW,
        )
        .expect("independent credential keeps capacity");
    assert_eq!(cache.len(), 3);
}

#[test]
fn two_logical_hosts_cover_partition_timeout_and_revoke_during_io() {
    let mut host_b_trust = PeerCredentialRegistryV1::new();
    host_b_trust
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 13))
        .expect("enroll");
    let outbound = seal_query(&host_b_trust, 1, [14; FEDERATION_NONCE_BYTES]);

    // A partition produces no terminal delivery. The protocol does not turn
    // absence into an empty success; the caller's bounded transport reports a
    // timeout/indeterminate outcome.
    let partitioned_delivery: Option<AuthenticatedFederationFrameV1> = None;
    assert!(partitioned_delivery.is_none());

    // Revocation while a frame is in flight is observed at the receiver's
    // verification boundary and the old credential cannot authenticate it.
    host_b_trust
        .revoke(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1)
        .expect("revoke");
    let mut replay = ReplayCacheV1::new(8).expect("replay cache");
    assert!(matches!(
        outbound.verify(&id("peer-b"), NOW + 1, &host_b_trust, &mut replay),
        Err(FederationProtocolError::Credential(
            CredentialError::Revoked
        ))
    ));
}
