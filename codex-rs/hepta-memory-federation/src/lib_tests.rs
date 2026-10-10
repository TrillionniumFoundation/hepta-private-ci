use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn fixture() -> (FederatedReadRequest, FederatedReadLease) {
    let request = FederatedReadRequest {
        request_id: id("request:1"),
        peer_id: id("peer:1"),
        scope_digest: digest(b"scope"),
        source_snapshot_digest: digest(b"snapshot"),
        request_digest: digest(b"request"),
        deadline_ms: 2_000,
    };
    let lease = FederatedReadLease {
        lease_id: id("lease:1"),
        request_id: request.request_id.clone(),
        peer_id: request.peer_id.clone(),
        scope_digest: request.scope_digest,
        source_snapshot_digest: request.source_snapshot_digest,
        request_digest: request.request_digest,
        expires_at_ms: 1_500,
        revoked: false,
    };
    (request, lease)
}

#[test]
fn missing_terminal_observation_is_indeterminate() {
    let (request, lease) = fixture();
    let Ok(receipt) = observe(1_000, request, lease, None) else {
        panic!("bounded unknown outcome must be representable");
    };
    assert_eq!(receipt.status, FederatedStatus::Indeterminate);
    assert_eq!(receipt.response_digest, None);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn revoked_lease_is_rejected() {
    let (request, mut lease) = fixture();
    lease.revoked = true;
    assert_eq!(
        observe(1_000, request, lease, None),
        Err(Error::LeaseRevoked)
    );
}

#[test]
fn snapshot_drift_is_rejected() {
    let (request, mut lease) = fixture();
    lease.source_snapshot_digest = digest(b"drift");
    assert_eq!(
        observe(1_000, request, lease, None),
        Err(Error::DigestMismatch("snapshot"))
    );
}

#[test]
fn terminal_response_is_bound() {
    let (request, lease) = fixture();
    let observation = RemoteObservation {
        response_digest: digest(b"response"),
        terminal_observed: true,
    };
    let Ok(receipt) = observe(1_000, request, lease, Some(observation)) else {
        panic!("terminal observation must succeed");
    };
    assert_eq!(receipt.status, FederatedStatus::Succeeded);
    assert_eq!(receipt.response_digest, Some(digest(b"response")));
}
