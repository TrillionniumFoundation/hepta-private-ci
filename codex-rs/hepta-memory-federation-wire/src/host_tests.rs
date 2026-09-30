use crate::replay::FederationReplayKeyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

const NOW: u64 = 2_000_000;

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

fn host_b_credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 41))
        .expect("inbound credential");
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 42))
        .expect("outbound credential");
    registry
}

fn host_a_credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 41))
        .expect("outbound credential");
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 42))
        .expect("inbound credential");
    registry
}

fn limits() -> FederationRecoveryLimitsV1 {
    FederationRecoveryLimitsV1 {
        replay_capacity: 32,
        replay_per_peer_capacity: 8,
        attempt_capacity: 32,
        attempt_per_peer_capacity: 8,
    }
}

fn open_host_b(
    store: InMemoryFederationRecoveryStoreV1,
    now_unix_ms: u64,
) -> FederationWireHostV1<InMemoryFederationRecoveryStoreV1> {
    let mut host = FederationWireHostV1::open(
        id("peer-b"),
        host_b_credentials(),
        32,
        8,
        limits(),
        store,
        now_unix_ms,
    )
    .expect("open host B");
    host.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind outbound");
    host
}

fn query_message() -> FederationQueryMessageV1 {
    FederationQueryMessageV1 {
        query_id: id("query-host-1"),
        query_binding_digest: digest(b"query-host-binding"),
        scope_digest: digest(b"query-host-scope"),
        purpose_digest: digest(b"query-host-purpose"),
        generation_vector_digest: digest(b"query-host-generation"),
        maximum_results: 8,
    }
}

fn encode_from_a(message: FederationWireMessageV1, nonce_byte: u8) -> Vec<u8> {
    let registry = host_a_credentials();
    let credential = registry
        .require_current(&id("peer-a"), &id("peer-b"), &id("key-a-b"), 1, NOW)
        .expect("current A->B credential");
    let frame = AuthenticatedFederationFrameV1::seal(
        credential,
        NOW,
        NOW + 10_000,
        FederationNonceV1::from_bytes([nonce_byte; FEDERATION_NONCE_BYTES]),
        message,
    )
    .expect("seal A frame");
    let (schemas, codec) = registered_codec_v1().expect("codec");
    encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode")
}

fn verify_at_a(payload: &[u8], now_unix_ms: u64) -> VerifiedFederationFrameV1 {
    let registry = host_a_credentials();
    let (schemas, codec) = registered_codec_v1().expect("codec");
    let frame = decode_registered_frame_v1(&schemas, &codec, payload).expect("decode");
    let mut replay = ReplayCacheV1::new(8).expect("replay");
    frame
        .verify(&id("peer-a"), now_unix_ms, &registry, &mut replay)
        .expect("verify at A")
}

#[test]
fn authenticated_transport_identity_and_owner_cut_form_a_vertical_read_path() {
    let mut host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let encoded = encode_from_a(FederationWireMessageV1::Query(query_message()), 51);
    let admission = host
        .admit(&id("peer-a"), &encoded, NOW + 1)
        .expect("admit query");
    let FederationHostAdmissionV1::Query(query) = admission else {
        panic!("query admission")
    };
    assert_eq!(query.peer_id(), &id("peer-a"));
    assert_eq!(query.query(), &query_message());

    let result = FederationHostQueryResultV1::new(
        digest(b"response-digest"),
        digest(b"result-digest"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id("peer-b"),
            generation: 7,
            frontier: 99,
            state_digest: digest(b"durable-owner-cut"),
            parent_witness_digest: digest(b"prior-owner-cut"),
            observed_unix_ms: NOW + 2,
        },
    )
    .expect("result");
    let response = host
        .complete_query(query, result, NOW + 2)
        .expect("complete query");
    let verified = verify_at_a(&response, NOW + 3);
    let FederationWireMessageV1::Response(response) = verified.message() else {
        panic!("response")
    };
    assert_eq!(response.frontier.owner_peer_id, id("peer-b"));
    assert_eq!(response.frontier.state_digest, digest(b"durable-owner-cut"));
    assert!(response.terminal_observed);
}

#[test]
fn secure_transport_peer_must_match_authenticated_frame_sender() {
    let mut host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let encoded = encode_from_a(FederationWireMessageV1::Query(query_message()), 52);
    assert!(matches!(
        host.admit(&id("peer-c"), &encoded, NOW + 1),
        Err(FederationHostError::TransportPeerMismatch)
    ));
}

#[test]
fn durable_replay_state_survives_host_restart() {
    let mut host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let encoded = encode_from_a(FederationWireMessageV1::Query(query_message()), 53);
    let _ = host
        .admit(&id("peer-a"), &encoded, NOW + 1)
        .expect("first admission");
    let store = host.into_recovery_store();
    let mut restarted = open_host_b(store, NOW + 2);
    assert!(matches!(
        restarted.admit(&id("peer-a"), &encoded, NOW + 2),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::Replay
        ))
    ));
}

#[test]
fn cancellation_persisted_before_terminal_fences_late_completion_after_restart() {
    let mut host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query = query_message();
    let query_payload = encode_from_a(FederationWireMessageV1::Query(query.clone()), 54);
    let admission = host
        .admit(&id("peer-a"), &query_payload, NOW + 1)
        .expect("query admission");
    let FederationHostAdmissionV1::Query(admitted) = admission else {
        panic!("query admission")
    };

    let cancel = FederationCancelMessageV1 {
        query_id: query.query_id.clone(),
        query_binding_digest: query.query_binding_digest,
        cancellation_id: id("cancel-host-1"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let cancel_payload = encode_from_a(FederationWireMessageV1::Cancel(cancel), 55);
    let cancellation = host
        .admit(&id("peer-a"), &cancel_payload, NOW + 2)
        .expect("cancel admission");
    let FederationHostAdmissionV1::Reply(ack_payload) = cancellation else {
        panic!("cancel ack")
    };
    let verified_ack = verify_at_a(&ack_payload, NOW + 3);
    let FederationWireMessageV1::CancelAck(ack) = verified_ack.message() else {
        panic!("cancel ack message")
    };
    assert_eq!(
        ack.disposition,
        FederationCancellationDispositionV1::ObservedBeforeTerminal
    );

    let store = host.into_recovery_store();
    let mut restarted = open_host_b(store, NOW + 3);
    let result = FederationHostQueryResultV1::new(
        digest(b"late-response"),
        digest(b"late-result"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id("peer-b"),
            generation: 7,
            frontier: 100,
            state_digest: digest(b"late-cut"),
            parent_witness_digest: digest(b"prior-cut"),
            observed_unix_ms: NOW + 4,
        },
    )
    .expect("late result");
    assert!(matches!(
        restarted.complete_query(admitted, result, NOW + 4),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::Cancelled
        ))
    ));
}

#[test]
fn recovery_snapshot_rejects_clock_rollback_on_restart() {
    let host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW + 10);
    let store = host.into_recovery_store();
    assert!(matches!(
        FederationWireHostV1::open(
            id("peer-b"),
            host_b_credentials(),
            32,
            8,
            limits(),
            store,
            NOW + 9,
        ),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::ClockRegression
        ))
    ));
}

#[test]
fn owner_cut_witness_from_another_peer_is_rejected() {
    let mut host = open_host_b(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let payload = encode_from_a(FederationWireMessageV1::Query(query_message()), 56);
    let FederationHostAdmissionV1::Query(admitted) = host
        .admit(&id("peer-a"), &payload, NOW + 1)
        .expect("query admission")
    else {
        panic!("query admission")
    };
    let result = FederationHostQueryResultV1::new(
        digest(b"wrong-owner-response"),
        digest(b"wrong-owner-result"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id("peer-c"),
            generation: 1,
            frontier: 1,
            state_digest: digest(b"wrong-owner-cut"),
            parent_witness_digest: Digest32::ZERO,
            observed_unix_ms: NOW + 2,
        },
    )
    .expect("result shape");
    assert!(matches!(
        host.complete_query(admitted, result, NOW + 2),
        Err(FederationHostError::FrontierOwnerMismatch)
    ));
}

#[test]
fn durable_state_partitions_replay_and_attempt_capacity_by_peer() {
    let limits = FederationRecoveryLimitsV1 {
        replay_capacity: 4,
        replay_per_peer_capacity: 2,
        attempt_capacity: 4,
        attempt_per_peer_capacity: 2,
    };
    let mut state =
        DurableFederationStateV1::empty(id("peer-b"), limits, NOW).expect("durable state");
    for byte in [61_u8, 62_u8] {
        let key = state
            .preflight_frame(
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
            .expect("preflight");
        state
            .record_verified_frame(key, &id("peer-a"), NOW + 100)
            .expect("record");
    }
    assert!(matches!(
        state.preflight_frame(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-a"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-a-b"),
                generation: 1,
                nonce: &[63; FEDERATION_NONCE_BYTES]
            },
            NOW + 100,
            NOW
        ),
        Err(FederationRecoveryError::ReplayPeerCapacityExhausted)
    ));
    let other = state
        .preflight_frame(
            FederationReplayKeyV1 {
                sender_peer_id: &id("peer-c"),
                receiver_peer_id: &id("peer-b"),
                key_id: &id("key-c-b"),
                generation: 1,
                nonce: &[64; FEDERATION_NONCE_BYTES],
            },
            NOW + 100,
            NOW,
        )
        .expect("other peer retains capacity");
    state
        .record_verified_frame(other, &id("peer-c"), NOW + 100)
        .expect("record other peer");

    for index in 0..2 {
        let query_id = id(&format!("attempt-a-{index}"));
        state
            .begin_attempt(
                &id("peer-a"),
                &query_id,
                digest(format!("binding-{index}").as_bytes()),
                NOW + 100,
                NOW,
            )
            .expect("attempt");
    }
    assert!(matches!(
        state.begin_attempt(
            &id("peer-a"),
            &id("attempt-a-3"),
            digest(b"binding-3"),
            NOW + 100,
            NOW,
        ),
        Err(FederationRecoveryError::AttemptPeerCapacityExhausted)
    ));
    state
        .begin_attempt(
            &id("peer-c"),
            &id("attempt-c-1"),
            digest(b"binding-c"),
            NOW + 100,
            NOW,
        )
        .expect("other peer attempt");
}
