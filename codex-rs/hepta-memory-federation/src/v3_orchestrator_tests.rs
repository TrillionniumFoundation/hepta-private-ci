use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct FixedClock;

impl FederationClockV3 for FixedClock {
    fn now_unix_ms(&self) -> u64 {
        10
    }
}

struct FixtureVerifier;

impl CapabilityVerifierV3 for FixtureVerifier {
    fn verify_current(
        &self,
        _now_unix_ms: u64,
        query: &FederatedQueryV3,
        authority: &CapabilityAuthorityEnvelopeV3,
    ) -> Result<VerifiedCapabilityV3, FederationV3Error> {
        query.validate(10)?;
        if query.peer_id != authority.peer_id {
            return Err(FederationV3Error::IdentityMismatch("peer_id"));
        }
        Ok(VerifiedCapabilityV3 {
            issuer_id: authority.issuer_id.clone(),
            key_id: authority.key_id.clone(),
            grant_id: authority.grant_id.clone(),
            lease_id: authority.lease_id.clone(),
            lease_epoch: authority.lease_epoch,
            revocation_epoch: authority.revocation_epoch,
            expires_unix_ms: authority.expires_unix_ms,
            authority_proof_digest: digest("authority-proof"),
            revocation_proof_digest: digest("revocation-proof"),
        })
    }
}

struct NoKeys;

impl FederationKeyResolverV3 for NoKeys {
    fn verification_key(&self, _issuer_id: &StableId, _key_id: &StableId) -> Option<[u8; 32]> {
        None
    }
}

struct UnavailableTransport;

impl FederationTransportV3 for UnavailableTransport {
    fn send_once(
        &self,
        _query: &FederatedQueryV3,
        _deadline_unix_ms: u64,
        _cancellation: &FederationCancellationTokenV3,
    ) -> Result<FederationTransportResultV3, FederationV3Error> {
        Ok(FederationTransportResultV3::NonTerminal(
            FederationTransportOutcomeV3::Unavailable,
        ))
    }
}

fn query(peer: &str, maximum_results: u32) -> FederatedQueryV3 {
    FederatedQueryV3 {
        query_id: id(&format!("query:{peer}")),
        peer_id: id(peer),
        principal_id: id("principal:1"),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation"),
        query_digest: digest(&format!("query-digest:{peer}")),
        maximum_results,
        deadline_unix_ms: 100,
        lease_epoch: 1,
        request_nonce_digest: digest(&format!("nonce:{peer}")),
    }
}

fn authority(query: &FederatedQueryV3) -> CapabilityAuthorityEnvelopeV3 {
    CapabilityAuthorityEnvelopeV3 {
        issuer_id: id("issuer:1"),
        key_id: id("authority-key:1"),
        grant_id: id(&format!("grant:{}", query.peer_id.as_str())),
        lease_id: id(&format!("lease:{}", query.peer_id.as_str())),
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        revocation_epoch: 1,
        expires_unix_ms: 90,
        proof_digest: digest("unused-proof"),
        signature: [0; 64],
    }
}

#[test]
fn hard_failure_on_one_peer_does_not_abort_other_peer_coverage() {
    let valid = query("peer:valid", 2);
    let invalid = query("peer:invalid", 0);
    let result = execute_federation_resilient_v3(
        &UnavailableTransport,
        &FixedClock,
        &FixtureVerifier,
        &NoKeys,
        vec![(valid.clone(), authority(&valid)), (invalid.clone(), authority(&invalid))],
    )
    .unwrap_or_else(|error| panic!("orchestration should survive peer error: {error}"));

    assert_eq!(result.results.len(), 1);
    assert_eq!(result.failures.len(), 1);
    assert_eq!(result.failures[0].peer_id, invalid.peer_id);
    assert_eq!(result.coverage.requested_peers, 2);
    assert_eq!(result.coverage.completed_peers, 0);
    assert_eq!(result.coverage.failed_peers, 2);
    assert_eq!(result.completeness, FederatedCompletenessV3::Partial);
    assert!(result.items.is_empty());
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
}
