use crate::*;

use super::support::*;

#[test]
fn authenticated_unsolicited_response_is_rejected() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let unknown = FederationQueryMessageV1 {
        query_id: id("unknown-query"),
        ..query()
    };
    let payload = encode_from_b(response_for_query(&unknown, "peer-b", NOW + 1), NOW + 2);
    assert!(matches!(
        client.admit(&id("peer-b"), &payload, NOW + 3),
        Err(FederationClientError::UnknownAttempt)
    ));
}

#[test]
fn cancellation_ack_must_match_exact_durable_cancellation_id() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query = query();
    let _ = client
        .begin_query(&id("peer-b"), query.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    let cancellation = FederationCancelMessageV1 {
        query_id: query.query_id.clone(),
        query_binding_digest: query.query_binding_digest,
        cancellation_id: id("expected-cancel"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let _ = client
        .cancel_query(&id("peer-b"), cancellation, NOW + 2, NOW + 20_000)
        .expect("cancel");
    let wrong_ack = FederationWireMessageV1::CancelAck(FederationCancelAckMessageV1 {
        query_id: query.query_id,
        query_binding_digest: query.query_binding_digest,
        cancellation_id: id("wrong-cancel"),
        disposition: FederationCancellationDispositionV1::ObservedBeforeTerminal,
        observed_unix_ms: NOW + 3,
    });
    let payload = encode_from_b(wrong_ack, NOW + 4);
    assert!(matches!(
        client.admit(&id("peer-b"), &payload, NOW + 5),
        Err(FederationClientError::CancellationAckMismatch)
    ));
}

#[test]
fn response_frontier_is_bound_to_sender_and_frame_time() {
    let mut wrong_owner_client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query = query();
    let _ = wrong_owner_client
        .begin_query(&id("peer-b"), query.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    let wrong_owner = encode_from_b(response_for_query(&query, "peer-c", NOW + 2), NOW + 3);
    assert!(matches!(
        wrong_owner_client.admit(&id("peer-b"), &wrong_owner, NOW + 4),
        Err(FederationClientError::FrontierOwnerMismatch)
    ));

    let mut future_client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let _ = future_client
        .begin_query(&id("peer-b"), query.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    let future = encode_from_b(response_for_query(&query, "peer-b", NOW + 20), NOW + 3);
    assert!(matches!(
        future_client.admit(&id("peer-b"), &future, NOW + 4),
        Err(FederationClientError::RemoteObservationClockInvalid)
    ));
}

#[test]
fn invalid_mac_precedes_client_staging_and_preserves_valid_response() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let request = query();
    client
        .begin_query(&id("peer-b"), request.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    client
        .begin_query(
            &id("peer-b"),
            FederationQueryMessageV1 {
                query_id: id("advance-clock-query"),
                query_binding_digest: digest(b"advance-clock"),
                ..query()
            },
            NOW + 20,
            NOW + 20_000,
        )
        .expect("advance durable clock");
    let original = encode_from_b(response_for_query(&request, "peer-b", NOW + 2), NOW + 3);
    let (schemas, codec) = registered_codec_v1().expect("codec");
    let mut frame = decode_registered_frame_v1(&schemas, &codec, &original).expect("decode");
    frame.mac[0] ^= 1;
    let forged = encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode");
    let before = client.recovery_snapshot().expect("before");
    assert!(matches!(
        client.admit(&id("peer-b"), &forged, NOW + 4),
        Err(FederationClientError::Protocol(
            FederationProtocolError::MacMismatch
        ))
    ));
    assert_eq!(client.recovery_snapshot().expect("unchanged"), before);
    client
        .admit(&id("peer-b"), &original, NOW + 21)
        .expect("original response");
}
