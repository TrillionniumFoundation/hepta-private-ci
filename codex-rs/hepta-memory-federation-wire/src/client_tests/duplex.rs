use crate::*;

use super::support::*;

#[test]
fn client_and_server_form_a_correlated_duplex_read_path() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let mut server = open_server(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query = query();

    let query_payload = client
        .begin_query(&id("peer-b"), query.clone(), NOW + 1, NOW + 20_000)
        .expect("durable outbound query");
    let FederationHostAdmissionV1::Query(admitted) = server
        .admit(&id("peer-a"), &query_payload, NOW + 2)
        .expect("server admission")
    else {
        panic!("query admission")
    };
    let response_payload = server
        .complete_query(admitted, result(401, NOW + 3), NOW + 3)
        .expect("server response");
    let verified = client
        .admit(&id("peer-b"), &response_payload, NOW + 4)
        .expect("client correlation");
    let FederationWireMessageV1::Response(response) = verified.message() else {
        panic!("response message")
    };
    assert_eq!(response.query_id, query.query_id);
    assert_eq!(response.query_binding_digest, query.query_binding_digest);
    assert_eq!(response.frontier.owner_peer_id, id("peer-b"));
    assert_eq!(response.frontier.frontier, 401);
}

#[test]
fn pending_outbound_attempt_survives_client_restart() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let mut server = open_server(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query_payload = client
        .begin_query(&id("peer-b"), query(), NOW + 1, NOW + 20_000)
        .expect("query");
    let FederationHostAdmissionV1::Query(admitted) = server
        .admit(&id("peer-a"), &query_payload, NOW + 2)
        .expect("server admission")
    else {
        panic!("query admission")
    };
    let response_payload = server
        .complete_query(admitted, result(402, NOW + 3), NOW + 3)
        .expect("response");

    let store = client.into_recovery_store();
    let mut restarted = open_client(store, NOW + 4);
    assert!(matches!(
        restarted
            .admit(&id("peer-b"), &response_payload, NOW + 5)
            .expect("correlate after restart")
            .message(),
        FederationWireMessageV1::Response(_)
    ));
}

#[test]
fn cancellation_ack_and_late_terminal_fence_survive_restart() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let mut server = open_server(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let query = query();
    let query_payload = client
        .begin_query(&id("peer-b"), query.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    let FederationHostAdmissionV1::Query(admitted) = server
        .admit(&id("peer-a"), &query_payload, NOW + 2)
        .expect("server admission")
    else {
        panic!("query admission")
    };

    let cancellation = FederationCancelMessageV1 {
        query_id: query.query_id.clone(),
        query_binding_digest: query.query_binding_digest,
        cancellation_id: id("client-cancel-1"),
        reason: FederationCancellationReasonV1::CallerCancelled,
    };
    let cancel_payload = client
        .cancel_query(&id("peer-b"), cancellation.clone(), NOW + 3, NOW + 20_000)
        .expect("durable cancel");
    let FederationHostAdmissionV1::Reply(ack_payload) = server
        .admit(&id("peer-a"), &cancel_payload, NOW + 4)
        .expect("server cancel")
    else {
        panic!("cancel acknowledgement")
    };

    let store = client.into_recovery_store();
    let mut restarted = open_client(store, NOW + 5);
    let ack = restarted
        .admit(&id("peer-b"), &ack_payload, NOW + 6)
        .expect("ack after restart");
    let FederationWireMessageV1::CancelAck(ack) = ack.message() else {
        panic!("cancel acknowledgement message")
    };
    assert_eq!(ack.cancellation_id, cancellation.cancellation_id);
    assert_eq!(
        ack.disposition,
        FederationCancellationDispositionV1::ObservedBeforeTerminal
    );

    assert!(matches!(
        server.complete_query(admitted, result(403, NOW + 7), NOW + 7),
        Err(FederationHostError::Recovery(
            FederationRecoveryError::Cancelled
        ))
    ));
    let late_response = encode_from_b(response_for_query(&query, "peer-b", NOW + 7), NOW + 8);
    assert!(matches!(
        restarted.admit(&id("peer-b"), &late_response, NOW + 9),
        Err(FederationClientError::AttemptCancelled)
    ));
}
