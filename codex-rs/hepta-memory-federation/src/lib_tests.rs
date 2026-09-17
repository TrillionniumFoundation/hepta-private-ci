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

#[derive(Clone)]
struct CompatibilityV2Transport(RemoteFederatedResponseV2);

impl FederationTransportV2 for CompatibilityV2Transport {
    fn send_once(
        &self,
        _query: &FederatedQueryV2,
    ) -> Result<FederationTransportResultV2, FederationV2Error> {
        Ok(FederationTransportResultV2::Terminal(self.0.clone()))
    }
}

#[test]
fn v2_partial_empty_remains_partial_and_ttl_is_lease_bounded() {
    let query = FederatedQueryV2 {
        query_id: id("query:v2"),
        peer_id: id("peer:1"),
        principal_id: id("principal:1"),
        scope_digest: digest(b"scope"),
        purpose_digest: digest(b"purpose"),
        generation_vector_digest: digest(b"generation"),
        query_digest: digest(b"query"),
        maximum_results: 8,
        deadline_unix_ms: 2_000,
        lease_epoch: 3,
        nonce_digest: digest(b"nonce"),
    };
    let lease = FederatedLeaseV2 {
        lease_id: id("lease:v2"),
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        expires_unix_ms: 1_500,
        revoked: false,
    };
    let transport = CompatibilityV2Transport(RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        response_digest: digest(b"response-v2"),
        observed_frontier: 7,
        expires_unix_ms: 1_800,
        items: Vec::new(),
        completeness: FederatedCompletenessV2::Partial,
        terminal_observed: true,
    });
    let result = execute_once(&transport, 1_000, query, &lease).expect("compatibility result");
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.expires_unix_ms, 1_500);
    result.validate().expect("corrected result validates");
}
