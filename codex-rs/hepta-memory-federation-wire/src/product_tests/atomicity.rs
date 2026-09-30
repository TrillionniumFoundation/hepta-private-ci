use super::*;

#[test]
fn query_body_tamper_is_rejected_before_server_replay_is_committed() {
    let mut client = client();
    let mut server = server();
    let request = client
        .begin_query(&query(), NOW + 1)
        .expect("request packet");
    let packet = FederationProductPacketV1::decode(&request, &profile()).expect("decode packet");
    let mut body = packet.body().to_vec();
    let last = body.len() - 1;
    body[last] ^= 1;
    let tampered = FederationProductPacketV1::new(packet.authenticated_frame().to_vec(), body)
        .expect("tampered packet")
        .encode()
        .expect("encode tampered packet");
    assert!(matches!(
        server.admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &tampered,
            NOW + 2,
        ),
        Err(FederationProductErrorV1::BodyCodec)
            | Err(FederationProductErrorV1::QueryBindingMismatch)
            | Err(FederationProductErrorV1::V2(_))
    ));
    assert!(matches!(
        server
            .admit(
                &transport("peer-b", "peer-a", b"server-channel"),
                &request,
                NOW + 3,
            )
            .expect("original frame remains admissible"),
        FederationProductHostAdmissionV1::Query(_)
    ));
}

#[test]
fn response_body_tamper_is_rejected_before_client_terminal_state_is_committed() {
    let mut client = client();
    let mut server = server();
    let (response_packet, expected) = complete_round_trip(&mut client, &mut server);
    let packet =
        FederationProductPacketV1::decode(&response_packet, &profile()).expect("decode response");
    let mut body = packet.body().to_vec();
    let last = body.len() - 1;
    body[last] ^= 1;
    let tampered = FederationProductPacketV1::new(packet.authenticated_frame().to_vec(), body)
        .expect("tampered response")
        .encode()
        .expect("encode tampered response");
    assert!(matches!(
        client.admit_response(
            &transport("peer-a", "peer-b", b"client-channel"),
            &tampered,
            NOW + 5,
        ),
        Err(FederationProductErrorV1::BodyDigestMismatch)
    ));
    assert_eq!(
        client
            .admit_response(
                &transport("peer-a", "peer-b", b"client-channel"),
                &response_packet,
                NOW + 6,
            )
            .expect("valid response remains admissible"),
        expected
    );
}

#[test]
fn transport_profile_mismatch_fails_before_wire_admission() {
    let mut client = client();
    let mut server = server();
    let request = client.begin_query(&query(), NOW + 1).expect("request");
    let wrong = wrong_profile_transport("peer-b", "peer-a", b"wrong-profile");
    assert!(matches!(
        server.admit(&wrong, &request, NOW + 2),
        Err(FederationProductErrorV1::TransportProfileMismatch)
    ));
    assert!(matches!(
        server
            .admit(
                &transport("peer-b", "peer-a", b"server-channel"),
                &request,
                NOW + 3,
            )
            .expect("valid profile remains admissible"),
        FederationProductHostAdmissionV1::Query(_)
    ));
}

#[test]
fn expired_owner_response_does_not_commit_terminal_state() {
    let mut client = client();
    let mut server = server();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");
    let FederationProductHostAdmissionV1::Query(admitted) = server
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("admitted query")
    else {
        panic!("query admission");
    };
    let wire = server.into_wire_host();
    let before = wire.recovery_snapshot().expect("pending snapshot");
    let mut server = FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("same host wrapper");
    let mut expired = response(&query);
    expired.expires_unix_ms = NOW + 3;
    let expired = expired.seal().expect("sealed expired response");
    assert!(matches!(
        server.complete_query(admitted, expired, frontier(), NOW + 4),
        Err(FederationProductErrorV1::V2(
            codex_hepta_memory_federation::FederationV2Error::ResponseExpired
        ))
    ));
    assert_eq!(
        server
            .into_wire_host()
            .recovery_snapshot()
            .expect("snapshot"),
        before
    );
}

#[test]
fn outgoing_query_profile_rejection_does_not_commit_pending_state() {
    let store = client().into_wire_client().into_recovery_store();
    let before = store.snapshot().expect("initial snapshot").to_vec();
    let mut wire =
        FederationWireClientV1::open(id("peer-a"), credentials(), 32, 8, limits(), store, NOW)
            .expect("reopened client");
    wire.bind_outbound_credential(
        id("peer-b"),
        FederationOutboundCredentialV1::new(id("key-a-b"), 1).expect("selector"),
    )
    .expect("credential");
    let bounded = FederationProductProfileV1::new(
        id("memory-federation-product-v1"),
        id("authenticated-channel-v1"),
        64,
    )
    .expect("bounded profile");
    let mut client = FederationProductClientV1::new(wire, bounded, transport_verifier("peer-a"))
        .expect("bounded client");
    assert!(matches!(
        client.begin_query(&query(), NOW + 1),
        Err(FederationProductErrorV1::Client(
            FederationClientError::OutboundFrameRejected
        ))
    ));
    let store = client.into_wire_client().into_recovery_store();
    assert_eq!(store.snapshot().expect("snapshot"), before);
}

#[test]
fn outgoing_response_profile_rejection_does_not_commit_terminal_state() {
    let mut client = client();
    let mut server = server();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");
    let FederationProductHostAdmissionV1::Query(admitted) = server
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("admitted query")
    else {
        panic!("query admission");
    };
    let wire = server.into_wire_host();
    let before = wire.recovery_snapshot().expect("pending snapshot");
    let bounded = FederationProductProfileV1::new(
        id("memory-federation-product-v1"),
        id("authenticated-channel-v1"),
        64,
    )
    .expect("bounded profile");
    let mut server = FederationProductHostV1::new(wire, bounded, transport_verifier("peer-b"))
        .expect("bounded host wrapper");
    assert!(matches!(
        server.complete_query(admitted, response(&query), frontier(), NOW + 4),
        Err(FederationProductErrorV1::Host(
            FederationHostError::OutboundFrameRejected
        ))
    ));
    assert_eq!(
        server
            .into_wire_host()
            .recovery_snapshot()
            .expect("snapshot"),
        before
    );
}

#[test]
fn oversized_cancel_reply_preserves_replay_and_cancellation_state() {
    let mut client = client();
    let mut server = server();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");
    assert!(matches!(
        server
            .admit(
                &transport("peer-b", "peer-a", b"server-channel"),
                &request,
                NOW + 2
            )
            .expect("query admission"),
        FederationProductHostAdmissionV1::Query(_)
    ));
    let cancel_frame = client
        .into_wire_client()
        .cancel_query(
            &query.peer_id,
            FederationCancelMessageV1 {
                query_id: query.query_id.clone(),
                query_binding_digest: query.binding_digest(),
                cancellation_id: id("cancel-profile"),
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            NOW + 3,
            query.deadline_unix_ms,
        )
        .expect("cancel frame");
    let cancel = FederationProductPacketV1::new(cancel_frame, Vec::new())
        .expect("cancel packet")
        .encode()
        .expect("encoded cancel");
    let wire = server.into_wire_host();
    let before = wire.recovery_snapshot().expect("pending snapshot");
    let bounded = FederationProductProfileV1::new(
        id("memory-federation-product-v1"),
        id("authenticated-channel-v1"),
        cancel.len(),
    )
    .expect("profile admits request but not its larger acknowledgement");
    let mut server = FederationProductHostV1::new(wire, bounded, transport_verifier("peer-b"))
        .expect("bounded host");
    assert!(matches!(
        server.admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &cancel,
            NOW + 4
        ),
        Err(FederationProductErrorV1::Host(
            FederationHostError::OutboundFrameRejected
        ))
    ));
    let wire = server.into_wire_host();
    assert_eq!(wire.recovery_snapshot().expect("snapshot"), before);
    let mut server = FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("same host with sufficient reply capacity");
    assert!(matches!(
        server
            .admit(
                &transport("peer-b", "peer-a", b"server-channel"),
                &cancel,
                NOW + 5
            )
            .expect("original cancel still admissible"),
        FederationProductHostAdmissionV1::Reply(_)
    ));
}
