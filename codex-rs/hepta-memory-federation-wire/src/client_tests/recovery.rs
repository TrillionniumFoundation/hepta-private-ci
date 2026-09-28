use crate::*;

use super::support::*;

#[test]
fn failed_store_does_not_advance_live_outbound_state() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut client = open_client(store, NOW);
    let before = client.recovery_snapshot().expect("initial snapshot");
    control.fail_next_store();
    assert!(matches!(
        client.begin_query(&id("peer-b"), query(), NOW + 1, NOW + 20_000),
        Err(FederationClientError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(client.recovery_snapshot().expect("unchanged snapshot"), before);
    client
        .begin_query(&id("peer-b"), query(), NOW + 2, NOW + 20_000)
        .expect("retry after store recovery");
}

#[test]
fn failed_inbound_store_can_be_retried_in_same_process_without_replay_poisoning() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut client = open_client(store, NOW);
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
        .complete_query(admitted, result(403, NOW + 3), NOW + 3)
        .expect("response");
    let before = client.recovery_snapshot().expect("pending snapshot");

    control.fail_next_store();
    assert!(matches!(
        client.admit(&id("peer-b"), &response_payload, NOW + 4),
        Err(FederationClientError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(client.recovery_snapshot().expect("unchanged snapshot"), before);
    assert!(matches!(
        client
            .admit(&id("peer-b"), &response_payload, NOW + 5)
            .expect("same-process retry after store recovery")
            .message(),
        FederationWireMessageV1::Response(_)
    ));
}

#[test]
fn failed_inbound_store_can_be_retried_after_restart_without_state_drift() {
    let store = ControlledStore::default();
    let control = store.clone();
    let mut client = open_client(store, NOW);
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
        .complete_query(admitted, result(404, NOW + 3), NOW + 3)
        .expect("response");
    let before = client.recovery_snapshot().expect("pending snapshot");

    control.fail_next_store();
    assert!(matches!(
        client.admit(&id("peer-b"), &response_payload, NOW + 4),
        Err(FederationClientError::Recovery(
            FederationRecoveryError::StoreUnavailable
        ))
    ));
    assert_eq!(client.recovery_snapshot().expect("unchanged snapshot"), before);

    let store = client.into_recovery_store();
    let mut restarted = open_client(store, NOW + 5);
    assert!(matches!(
        restarted
            .admit(&id("peer-b"), &response_payload, NOW + 6)
            .expect("retry after restart")
            .message(),
        FederationWireMessageV1::Response(_)
    ));
}
