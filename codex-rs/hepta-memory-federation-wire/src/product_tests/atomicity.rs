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
