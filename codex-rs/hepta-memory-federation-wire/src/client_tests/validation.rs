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
