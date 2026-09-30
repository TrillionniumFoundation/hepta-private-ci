//! Exercise the public authenticated admission/completion path, not forged tokens.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::*;

const NOW: u64 = 3_000_000;

type Host = FederationWireHostV1<InMemoryFederationRecoveryStoreV1>;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn credential(sender: &str, receiver: &str, generation: u64) -> PeerCredentialV1 {
    PeerCredentialV1::new(
        id(sender),
        id(receiver),
        id("directional-key"),
        generation,
        NOW - 100,
        NOW + 100_000,
        [41; FEDERATION_MAC_KEY_BYTES],
    )
    .expect("credential")
}

fn credentials(receiver: &str) -> PeerCredentialRegistryV1 {
    let mut registry = PeerCredentialRegistryV1::new();
    registry
        .enroll(credential("requester", receiver, 1))
        .expect("inbound");
    registry
        .enroll(credential(receiver, "requester", 1))
        .expect("outbound");
    registry
}

fn open_host(
    receiver: &str,
    registry: PeerCredentialRegistryV1,
    store: InMemoryFederationRecoveryStoreV1,
    now: u64,
) -> Host {
    let mut host = FederationWireHostV1::open(
        id(receiver),
        registry,
        32,
        8,
        FederationRecoveryLimitsV1 {
            replay_capacity: 32,
            replay_per_peer_capacity: 8,
            attempt_capacity: 32,
            attempt_per_peer_capacity: 8,
        },
        store,
        now,
    )
    .expect("host");
    host.bind_outbound_credential(
        id("requester"),
        FederationOutboundCredentialV1::new(id("directional-key"), 1).expect("selector"),
    )
    .expect("outbound binding");
    host
}

fn host(receiver: &str) -> Host {
    open_host(
        receiver,
        credentials(receiver),
        InMemoryFederationRecoveryStoreV1::default(),
        NOW,
    )
}

fn query_bytes(receiver: &str, query_id: &str, generation: u64, nonce: u8) -> Vec<u8> {
    let key = credential("requester", receiver, generation);
    let frame = AuthenticatedFederationFrameV1::seal(
        &key,
        NOW,
        NOW + 10_000,
        FederationNonceV1::from_bytes([nonce; FEDERATION_NONCE_BYTES]),
        FederationWireMessageV1::Query(FederationQueryMessageV1 {
            query_id: id(query_id),
            query_binding_digest: Digest32::of_bytes(b"same-query-binding"),
            scope_digest: Digest32::of_bytes(b"scope"),
            purpose_digest: Digest32::of_bytes(b"purpose"),
            generation_vector_digest: Digest32::of_bytes(b"generation"),
            maximum_results: 8,
        }),
    )
    .expect("seal");
    let (schemas, codec) = registered_codec_v1().expect("codec");
    encode_registered_frame_v1(&schemas, &codec, &frame).expect("encode")
}

fn admit(host: &mut Host, query_id: &str, generation: u64, nonce: u8) -> AdmittedFederationQueryV1 {
    let receiver = host.local_peer_id().as_str().to_string();
    let bytes = query_bytes(&receiver, query_id, generation, nonce);
    let FederationHostAdmissionV1::Query(token) = host
        .admit(&id("requester"), &bytes, NOW + 1)
        .expect("admission")
    else {
        panic!("expected query token")
    };
    token
}

fn result(receiver: &str, now: u64) -> FederationHostQueryResultV1 {
    FederationHostQueryResultV1::new(
        Digest32::of_bytes(b"response"),
        Digest32::of_bytes(b"result"),
        AuthenticatedFrontierV1 {
            owner_peer_id: id(receiver),
            generation: 1,
            frontier: 1,
            state_digest: Digest32::of_bytes(b"owner-cut"),
            parent_witness_digest: Digest32::ZERO,
            observed_unix_ms: now,
        },
    )
    .expect("result")
}

#[test]
fn revoked_request_key_cannot_complete_under_still_current_response_key() {
    let mut server = host("owner");
    let token = admit(&mut server, "query", 1, 1);
    let before = server.recovery_snapshot().expect("before");
    server
        .revoke_credential(&id("requester"), &id("owner"), &id("directional-key"), 1)
        .expect("revoke inbound only");
    assert!(matches!(
        server.complete_query(token, result("owner", NOW + 2), NOW + 2),
        Err(FederationHostError::Credential(CredentialError::Revoked))
    ));
    assert_eq!(server.recovery_snapshot().expect("after"), before);
}

#[test]
fn request_key_rotation_fences_old_admission_but_allows_fresh_generation() {
    let mut server = host("owner");
    let old = admit(&mut server, "old-query", 1, 2);
    server
        .rotate_credential(credential("requester", "owner", 2))
        .expect("rotate inbound");
    let before = server.recovery_snapshot().expect("before");
    assert!(matches!(
        server.complete_query(old, result("owner", NOW + 2), NOW + 2),
        Err(FederationHostError::Credential(CredentialError::Revoked))
    ));
    assert_eq!(server.recovery_snapshot().expect("after"), before);
    let fresh = admit(&mut server, "fresh-query", 2, 3);
    assert!(
        server
            .complete_query(fresh, result("owner", NOW + 3), NOW + 3)
            .is_ok()
    );
}

#[test]
fn response_key_rotation_does_not_revoke_current_request_authority() {
    let mut server = host("owner");
    let token = admit(&mut server, "query", 1, 4);
    server
        .rotate_credential(credential("owner", "requester", 2))
        .expect("rotate outbound");
    server
        .bind_outbound_credential(
            id("requester"),
            FederationOutboundCredentialV1::new(id("directional-key"), 2).expect("selector"),
        )
        .expect("bind rotated outbound");
    assert!(
        server
            .complete_query(token, result("owner", NOW + 2), NOW + 2)
            .is_ok()
    );
}

#[test]
fn token_from_another_host_is_rejected_even_with_matching_pending_query() {
    let mut first = host("owner-b");
    let mut second = host("owner-c");
    let wrong_host = admit(&mut first, "same-query", 1, 5);
    let own = admit(&mut second, "same-query", 1, 6);
    let before = second.recovery_snapshot().expect("before");
    assert!(matches!(
        second.complete_query(wrong_host, result("owner-c", NOW + 2), NOW + 2),
        Err(FederationHostError::AdmissionHostMismatch)
    ));
    assert_eq!(second.recovery_snapshot().expect("after"), before);
    assert!(
        second
            .complete_query(own, result("owner-c", NOW + 3), NOW + 3)
            .is_ok()
    );
}

#[test]
fn expired_request_credential_is_rejected_without_recording_terminal() {
    let mut server = host("owner");
    let token = admit(&mut server, "query", 1, 7);
    let before = server.recovery_snapshot().expect("before");
    assert!(matches!(
        server.complete_query(token, result("owner", NOW + 100_000), NOW + 100_000),
        Err(FederationHostError::Credential(CredentialError::Expired))
    ));
    assert_eq!(server.recovery_snapshot().expect("after"), before);
}

#[test]
fn reloaded_current_credentials_fence_late_callback_after_host_recovery() {
    let mut server = host("owner");
    let token = admit(&mut server, "query", 1, 8);
    let store = server.into_recovery_store();
    let mut current = credentials("owner");
    current
        .revoke(&id("requester"), &id("owner"), &id("directional-key"), 1)
        .expect("credential owner supplies current revocation");
    let mut recovered = open_host("owner", current, store, NOW + 2);
    let before = recovered.recovery_snapshot().expect("before");
    assert!(matches!(
        recovered.complete_query(token, result("owner", NOW + 3), NOW + 3),
        Err(FederationHostError::Credential(CredentialError::Revoked))
    ));
    assert_eq!(recovered.recovery_snapshot().expect("after"), before);
}
