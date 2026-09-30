use codex_hepta_types::Digest32;

use crate::*;

use super::support::*;

#[test]
fn frontier_chain_is_anchored_and_survives_client_restart() {
    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let first_query = query();
    let _ = client
        .begin_query(&id("peer-b"), first_query.clone(), NOW + 1, NOW + 20_000)
        .expect("first query");
    let first_frontier = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer-b"),
        generation: 1,
        frontier: 10,
        state_digest: digest(b"first-cut"),
        parent_witness_digest: Digest32::ZERO,
        observed_unix_ms: NOW + 2,
    };
    let first_response = FederationWireMessageV1::Response(FederationResponseMessageV1 {
        query_id: first_query.query_id,
        query_binding_digest: first_query.query_binding_digest,
        response_digest: digest(b"first-response"),
        result_digest: digest(b"first-result"),
        frontier: first_frontier.clone(),
        terminal_observed: true,
    });
    let first_payload = encode_from_b(first_response, NOW + 3);
    client
        .admit(&id("peer-b"), &first_payload, NOW + 4)
        .expect("first frontier");
    assert_eq!(client.last_frontier(&id("peer-b")), Some(&first_frontier));

    let store = client.into_recovery_store();
    let mut restarted = open_client(store, NOW + 5);
    assert_eq!(
        restarted.last_frontier(&id("peer-b")),
        Some(&first_frontier)
    );

    let second_query = FederationQueryMessageV1 {
        query_id: id("client-query-2"),
        query_binding_digest: digest(b"client-query-binding-2"),
        ..query()
    };
    let _ = restarted
        .begin_query(&id("peer-b"), second_query.clone(), NOW + 6, NOW + 20_000)
        .expect("second query");
    let second_frontier = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer-b"),
        generation: 1,
        frontier: 11,
        state_digest: digest(b"second-cut"),
        parent_witness_digest: first_frontier.binding_digest(),
        observed_unix_ms: NOW + 7,
    };
    let second_response = FederationWireMessageV1::Response(FederationResponseMessageV1 {
        query_id: second_query.query_id,
        query_binding_digest: second_query.query_binding_digest,
        response_digest: digest(b"second-response"),
        result_digest: digest(b"second-result"),
        frontier: second_frontier.clone(),
        terminal_observed: true,
    });
    let second_payload = encode_from_b(second_response, NOW + 8);
    restarted
        .admit(&id("peer-b"), &second_payload, NOW + 9)
        .expect("successor frontier");
    assert_eq!(
        restarted.last_frontier(&id("peer-b")),
        Some(&second_frontier)
    );
}

#[test]
fn frontier_chain_rejects_unanchored_first_and_wrong_successor() {
    let mut unanchored = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let first_query = query();
    let _ = unanchored
        .begin_query(&id("peer-b"), first_query.clone(), NOW + 1, NOW + 20_000)
        .expect("query");
    let mut first_message = response_for_query(&first_query, "peer-b", NOW + 2);
    let FederationWireMessageV1::Response(first_response) = &mut first_message else {
        unreachable!()
    };
    first_response.frontier.parent_witness_digest = digest(b"unknown-parent");
    let unanchored_payload = encode_from_b(first_message, NOW + 3);
    assert!(matches!(
        unanchored.admit(&id("peer-b"), &unanchored_payload, NOW + 4),
        Err(FederationClientError::FrontierChainUnanchored)
    ));

    let mut client = open_client(InMemoryFederationRecoveryStoreV1::default(), NOW);
    let _ = client
        .begin_query(&id("peer-b"), first_query.clone(), NOW + 1, NOW + 20_000)
        .expect("first query");
    let first_payload = encode_from_b(response_for_query(&first_query, "peer-b", NOW + 2), NOW + 3);
    client
        .admit(&id("peer-b"), &first_payload, NOW + 4)
        .expect("first frontier");

    let second_query = FederationQueryMessageV1 {
        query_id: id("client-query-wrong-successor"),
        query_binding_digest: digest(b"client-query-wrong-successor"),
        ..query()
    };
    let _ = client
        .begin_query(&id("peer-b"), second_query.clone(), NOW + 5, NOW + 20_000)
        .expect("second query");
    let wrong_successor = response_for_query(&second_query, "peer-b", NOW + 6);
    let wrong_payload = encode_from_b(wrong_successor, NOW + 7);
    assert!(matches!(
        client.admit(&id("peer-b"), &wrong_payload, NOW + 8),
        Err(FederationClientError::Protocol(
            FederationProtocolError::FrontierParentMismatch
        ))
    ));
}
