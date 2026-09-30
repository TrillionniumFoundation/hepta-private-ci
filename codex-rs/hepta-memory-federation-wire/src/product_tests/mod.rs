mod adapter;
mod atomicity;

use codex_hepta_memory_federation::FederatedCompletenessV2;
use codex_hepta_memory_federation::FederatedEvidenceItemV2;
use codex_hepta_memory_federation::FederatedQueryV2;
use codex_hepta_memory_federation::RemoteFederatedResponseV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::*;

const NOW: u64 = 9_000_000;
const TRANSPORT_CONTEXT_SECRET: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES] =
    [93; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES];
const UNTRUSTED_TRANSPORT_CONTEXT_SECRET: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES] =
    [94; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES];

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn profile() -> FederationProductProfileV1 {
    FederationProductProfileV1::new(
        id("memory-federation-product-v1"),
        id("authenticated-channel-v1"),
        MAX_FEDERATION_PRODUCT_PACKET_BYTES,
    )
    .expect("product profile")
}

fn transport_issuer_with(
    local_peer_id: &str,
    transport_profile_id: &str,
    secret: [u8; FEDERATION_TRANSPORT_CONTEXT_KEY_BYTES],
) -> FederationTransportContextIssuerV1 {
    FederationTransportContextIssuerV1::new(
        id(local_peer_id),
        id(transport_profile_id),
        id("transport-context-key-v1"),
        1,
        secret,
    )
    .expect("transport context issuer")
}

fn transport_issuer(local_peer_id: &str) -> FederationTransportContextIssuerV1 {
    transport_issuer_with(
        local_peer_id,
        "authenticated-channel-v1",
        TRANSPORT_CONTEXT_SECRET,
    )
}

fn transport_verifier(local_peer_id: &str) -> FederationTransportContextVerifierV1 {
    transport_issuer(local_peer_id).verifier()
}

fn transport(
    local_peer_id: &str,
    peer_id: &str,
    label: &[u8],
) -> FederationAuthenticatedTransportV1 {
    transport_issuer(local_peer_id)
        .issue_verified_channel(id(peer_id), digest(label), NOW, NOW + 100_000)
        .expect("transport context")
}

fn untrusted_transport(
    local_peer_id: &str,
    peer_id: &str,
    label: &[u8],
) -> FederationAuthenticatedTransportV1 {
    transport_issuer_with(
        local_peer_id,
        "authenticated-channel-v1",
        UNTRUSTED_TRANSPORT_CONTEXT_SECRET,
    )
    .issue_verified_channel(id(peer_id), digest(label), NOW, NOW + 100_000)
    .expect("untrusted transport context")
}

fn wrong_profile_transport(
    local_peer_id: &str,
    peer_id: &str,
    label: &[u8],
) -> FederationAuthenticatedTransportV1 {
    transport_issuer_with(
        local_peer_id,
        "different-channel-profile",
        TRANSPORT_CONTEXT_SECRET,
    )
    .issue_verified_channel(id(peer_id), digest(label), NOW, NOW + 100_000)
    .expect("wrong-profile transport context")
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

fn credentials() -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("peer-a", "peer-b", "key-a-b", 1, 91))
        .expect("A to B credential");
    registry
        .enroll(credential("peer-b", "peer-a", "key-b-a", 1, 92))
        .expect("B to A credential");
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

fn client() -> FederationProductClientV1<InMemoryFederationRecoveryStoreV1> {
    let mut wire = FederationWireClientV1::open(
        id("peer-a"),
        credentials(),
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
    .expect("bind client credential");
    FederationProductClientV1::new(wire, profile(), transport_verifier("peer-a"))
        .expect("product client")
}

fn server() -> FederationProductHostV1<InMemoryFederationRecoveryStoreV1> {
    let mut wire = FederationWireHostV1::open(
        id("peer-b"),
        credentials(),
        32,
        8,
        limits(),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
    .expect("server");
    wire.bind_outbound_credential(
        id("peer-a"),
        FederationOutboundCredentialV1::new(id("key-b-a"), 1).expect("selector"),
    )
    .expect("bind server credential");
    FederationProductHostV1::new(wire, profile(), transport_verifier("peer-b"))
        .expect("product host")
}

fn query() -> FederatedQueryV2 {
    FederatedQueryV2 {
        query_id: id("product-query-1"),
        peer_id: id("peer-b"),
        principal_id: id("consumer-a"),
        scope_digest: digest(b"product-scope"),
        purpose_digest: digest(b"product-purpose"),
        generation_vector_digest: digest(b"product-generation"),
        query_digest: digest(b"product-query"),
        maximum_results: 8,
        deadline_unix_ms: NOW + 20_000,
        lease_epoch: 1,
        nonce_digest: digest(b"product-nonce"),
    }
}

fn response(query: &FederatedQueryV2) -> RemoteFederatedResponseV2 {
    RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        query_binding_digest: query.binding_digest(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: Digest32::ZERO,
        observed_frontier: 71,
        expires_unix_ms: NOW + 15_000,
        items: vec![FederatedEvidenceItemV2 {
            source_owner_id: id("peer-b"),
            record_id: id("memory-record-1"),
            record_revision: Revision::new(1).expect("revision"),
            record_digest: digest(b"record"),
            support_digest: digest(b"support"),
            validity_digest: digest(b"validity"),
        }],
        completeness: FederatedCompletenessV2::Complete,
        terminal_observed: true,
    }
    .seal()
    .expect("sealed response")
}

fn frontier() -> AuthenticatedFrontierV1 {
    AuthenticatedFrontierV1 {
        owner_peer_id: id("peer-b"),
        generation: 1,
        frontier: 71,
        state_digest: digest(b"frontier-state"),
        parent_witness_digest: Digest32::ZERO,
        observed_unix_ms: NOW + 3,
    }
}

fn complete_round_trip(
    client: &mut FederationProductClientV1<InMemoryFederationRecoveryStoreV1>,
    server: &mut FederationProductHostV1<InMemoryFederationRecoveryStoreV1>,
) -> (Vec<u8>, RemoteFederatedResponseV2) {
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");
    let FederationProductHostAdmissionV1::Query(admitted) = server
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("admit request")
    else {
        panic!("query admission");
    };
    assert_eq!(admitted.query(), &query);
    let expected = response(&query);
    let packet = server
        .complete_query(admitted, expected.clone(), frontier(), NOW + 4)
        .expect("complete query");
    (packet, expected)
}

#[test]
fn canonical_product_body_encoding_is_stable() {
    let query = query();
    let encoded_query = encode_query_v2(&query).expect("encode query");
    let decoded_query = decode_query_v2(&encoded_query).expect("decode query");
    assert_eq!(decoded_query, query);
    assert_eq!(
        encode_query_v2(&decoded_query).expect("re-encode query"),
        encoded_query
    );

    let response = response(&query);
    let encoded_response = encode_response_v2(&response).expect("encode response");
    let decoded_response = decode_response_v2(&encoded_response).expect("decode response");
    assert_eq!(decoded_response, response);
    assert_eq!(
        encode_response_v2(&decoded_response).expect("re-encode response"),
        encoded_response
    );
}

#[test]
fn transport_context_from_untrusted_issuer_is_rejected_before_replay_commit() {
    let mut client = client();
    let mut server = server();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");

    let error = match server.admit(
        &untrusted_transport("peer-b", "peer-a", b"forged-server-channel"),
        &request,
        NOW + 2,
    ) {
        Ok(_) => panic!("untrusted context must fail"),
        Err(error) => error,
    };
    assert!(matches!(
        error,
        FederationProductErrorV1::InvalidTransportContext
    ));

    let FederationProductHostAdmissionV1::Query(admitted) = server
        .admit(
            &transport("peer-b", "peer-a", b"server-channel"),
            &request,
            NOW + 2,
        )
        .expect("trusted context remains admissible")
    else {
        panic!("query admission");
    };
    assert_eq!(admitted.query(), &query);
}

#[test]
fn transport_context_for_another_local_host_is_rejected_before_replay_commit() {
    let mut client = client();
    let mut server = server();
    let query = query();
    let request = client.begin_query(&query, NOW + 1).expect("request");

    let error = match server.admit(
        &transport("peer-c", "peer-a", b"other-host-channel"),
        &request,
        NOW + 2,
    ) {
        Ok(_) => panic!("other-host context must fail"),
        Err(error) => error,
    };
    assert!(matches!(
        error,
        FederationProductErrorV1::InvalidTransportContext
    ));

    assert!(matches!(
        server
            .admit(
                &transport("peer-b", "peer-a", b"server-channel"),
                &request,
                NOW + 3,
            )
            .expect("correct local host remains admissible"),
        FederationProductHostAdmissionV1::Query(_)
    ));
}

#[test]
fn canonical_v2_query_and_response_cross_the_authenticated_product_bridge() {
    let mut client = client();
    let mut server = server();
    let (packet, expected) = complete_round_trip(&mut client, &mut server);
    let observed = client
        .admit_response(
            &transport("peer-a", "peer-b", b"client-channel"),
            &packet,
            NOW + 5,
        )
        .expect("admit response");
    assert_eq!(observed, expected);
}
