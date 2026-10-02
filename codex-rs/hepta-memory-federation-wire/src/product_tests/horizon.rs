use super::*;

fn short_lived_credentials(
    sender: &str,
    receiver: &str,
    key: &str,
    byte: u8,
) -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(
            PeerCredentialV1::new(
                id(sender),
                id(receiver),
                id(key),
                1,
                NOW - 100,
                NOW + 10_000,
                [byte; FEDERATION_MAC_KEY_BYTES],
            )
            .expect("short-lived credential"),
        )
        .expect("enroll short-lived credential");
    if sender == "peer-b" {
        registry
            .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 91))
            .expect("request credential");
    }
    registry
}

#[test]
fn query_exceeding_signing_horizon_preserves_durable_state() {
    let wire = FederationWireClientV1::open(
        id("peer-a"),
        short_lived_credentials("peer-a", "peer-b", "key-a-b", 91),
        32,
        8,
        limits(),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("client");
    let before = wire.into_recovery_store();
    let snapshot = before.snapshot().expect("initial snapshot").to_vec();
    let mut wire = FederationWireClientV1::open(
        id("peer-a"),
        short_lived_credentials("peer-a", "peer-b", "key-a-b", 91),
        32,
        8,
        limits(),
        before,
        NOW,
    )
    .expect("reopen client");
    wire.bind_outbound_credential(
        id("peer-b"),
        FederationOutboundCredentialV1::new(id("key-a-b"), 1).expect("selector"),
    )
    .expect("bind");
    let mut client = FederationProductClientV1::new(wire, profile(), transport_verifier("peer-a"))
        .expect("product client");
    assert!(matches!(
        client.begin_query(&query(), NOW + 1),
        Err(FederationProductErrorV1::Client(
            FederationClientError::OutboundHorizonRejected
        ))
    ));
    let store = client.into_wire_client().into_recovery_store();
    assert_eq!(store.snapshot().expect("snapshot"), snapshot);
}

#[test]
fn response_exceeding_signing_horizon_preserves_durable_state() {
    let mut wire = FederationWireHostV1::open(
        id("peer-b"),
        short_lived_credentials("peer-b", "peer-a", "key-b-a", 92),
        32,
        8,
        limits(),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("host");
    wire.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind");
    let mut host = FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("product host");
    let query = query();
    let request = client().begin_query(&query, NOW + 1).expect("request");
    let FederationProductHostAdmissionV1::Query(admitted) = host
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("admission")
    else {
        panic!("query admission");
    };
    let wire = host.into_wire_host();
    let before = wire.recovery_snapshot().expect("pending snapshot");
    let mut host = FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("product host");
    assert!(matches!(
        host.complete_query(admitted, response(&query), frontier(), NOW + 4),
        Err(FederationProductErrorV1::Host(
            FederationHostError::OutboundHorizonRejected
        ))
    ));
    assert_eq!(
        host.into_wire_host().recovery_snapshot().expect("snapshot"),
        before
    );
}

#[test]
fn response_at_signing_horizon_is_accepted_end_to_end() {
    let mut wire = FederationWireHostV1::open(
        id("peer-b"),
        short_lived_credentials("peer-b", "peer-a", "key-b-a", 92),
        32,
        8,
        limits(),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("host");
    wire.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind");
    let mut host = FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("product host");
    let mut client = client();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");
    let FederationProductHostAdmissionV1::Query(admitted) = host
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("admission")
    else {
        panic!("query admission");
    };
    let mut expected = response(&query);
    expected.expires_unix_ms = NOW + 10_000;
    let expected = expected.seal().expect("sealed boundary response");
    let packet = host
        .complete_query(admitted, expected.clone(), frontier(), NOW + 4)
        .expect("boundary response");
    assert_eq!(
        client
            .admit_response_for_query(
                &query,
                &transport("peer-a", "peer-b", b"client-channel"),
                &packet,
                NOW + 5
            )
            .expect("accepted response"),
        expected
    );
}

#[test]
fn query_at_signing_horizon_is_accepted_by_host() {
    let mut wire = FederationWireClientV1::open(
        id("peer-a"),
        short_lived_credentials("peer-a", "peer-b", "key-a-b", 91),
        32,
        8,
        limits(),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("client");
    wire.bind_outbound_credential(
        id("peer-b"),
        FederationOutboundCredentialV1::new(id("key-a-b"), 1).expect("selector"),
    )
    .expect("bind");
    let mut client = FederationProductClientV1::new(wire, profile(), transport_verifier("peer-a"))
        .expect("product client");
    let mut query = query();
    query.deadline_unix_ms = NOW + 10_000;
    let packet = client.begin_query(&query, NOW + 1).expect("boundary query");
    let FederationProductHostAdmissionV1::Query(admitted) = server()
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &packet,
            NOW + 2,
        )
        .expect("accepted query")
    else {
        panic!("query admission");
    };
    assert_eq!(admitted.query(), &query);
}
