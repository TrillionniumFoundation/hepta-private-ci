use super::*;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

#[derive(Clone)]
struct Clock(Arc<AtomicU64>);

impl Clock {
    fn new(now: u64) -> Self {
        Self(Arc::new(AtomicU64::new(now)))
    }

    fn set(&self, now: u64) {
        self.0.store(now, Ordering::Release);
    }
}

impl FederationClockV2 for Clock {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error> {
        Ok(self.0.load(Ordering::Acquire))
    }
}

#[derive(Clone)]
struct Authority {
    revoked: Arc<AtomicBool>,
}

impl Authority {
    fn new() -> Self {
        Self {
            revoked: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl FederationAuthorityVerifierV2 for Authority {
    fn verify(
        &self,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
        now_unix_ms: u64,
    ) -> Result<VerifiedFederationAuthorityV2, FederationV2Error> {
        if self.revoked.load(Ordering::Acquire) {
            return Err(FederationV2Error::AuthorityRevoked);
        }
        Ok(VerifiedFederationAuthorityV2 {
            issuer_id: id("authority:1"),
            key_id: id("authority-key:1"),
            grant_id: id("grant:1"),
            lease_id: lease.lease_id.clone(),
            peer_id: query.peer_id.clone(),
            principal_id: query.principal_id.clone(),
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            lease_epoch: query.lease_epoch,
            revocation_epoch: 9,
            observed_at_unix_ms: now_unix_ms,
            revocation_fresh_until_unix_ms: 700,
            expires_unix_ms: lease.expires_unix_ms,
            proof_digest: digest("authority-proof"),
        })
    }
}

struct PeerVerifier;

impl FederationPeerSignatureVerifierV2 for PeerVerifier {
    fn verify(
        &self,
        response: &RemoteFederatedResponseV2,
    ) -> Result<PeerAuthenticationReceiptV2, FederationV2Error> {
        if response.signature.as_slice() != response.signing_digest().as_array().as_ref() {
            return Err(FederationV2Error::InvalidSignature);
        }
        Ok(PeerAuthenticationReceiptV2 {
            peer_id: response.peer_id.clone(),
            key_id: response.signer_key_id.clone(),
            signing_digest: response.signing_digest(),
            proof_digest: Digest32::of_bytes(&response.signature),
        })
    }
}

#[derive(Clone)]
struct Transport {
    response: FederationTransportResultV2,
    clock_after_send: Option<(Clock, u64)>,
    revoke_after_send: Option<Arc<AtomicBool>>,
}

impl FederationTransportV2 for Transport {
    fn send_once(
        &self,
        request: &FederationTransportRequestV2,
    ) -> Result<FederationTransportResultV2, FederationV2Error> {
        assert_eq!(request.grant_id, id("grant:1"));
        if let Some((clock, now)) = &self.clock_after_send {
            clock.set(*now);
        }
        if let Some(revoked) = &self.revoke_after_send {
            revoked.store(true, Ordering::Release);
        }
        Ok(self.response.clone())
    }
}

fn query(number: u64) -> FederatedQueryV2 {
    FederatedQueryV2 {
        query_id: id(&format!("query:{number}")),
        peer_id: id("peer:1"),
        principal_id: id("principal:1"),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation"),
        query_digest: digest("query"),
        maximum_results: 2,
        deadline_unix_ms: 1_000,
        lease_epoch: 3,
        nonce_digest: digest(&format!("nonce:{number}")),
    }
}

fn lease(query: &FederatedQueryV2) -> FederatedLeaseV2 {
    FederatedLeaseV2 {
        lease_id: id("lease:1"),
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        lease_epoch: query.lease_epoch,
        expires_unix_ms: 900,
        revoked: true,
    }
}

fn item(number: u64) -> FederatedEvidenceItemV2 {
    FederatedEvidenceItemV2 {
        source_owner_id: id("owner:1"),
        record_id: id(&format!("record:{number}")),
        record_revision: revision(number),
        record_digest: digest(&format!("record:{number}")),
        support_digest: digest(&format!("support:{number}")),
        validity_digest: digest(&format!("validity:{number}")),
    }
}

fn response(query: &FederatedQueryV2, lease: &FederatedLeaseV2) -> RemoteFederatedResponseV2 {
    let mut response = RemoteFederatedResponseV2 {
        peer_id: query.peer_id.clone(),
        signer_key_id: id("peer-key:1"),
        query_binding_digest: query.binding_digest(),
        request_nonce_digest: query.nonce_digest,
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        grant_id: id("grant:1"),
        lease_id: lease.lease_id.clone(),
        lease_epoch: query.lease_epoch,
        response_nonce_digest: digest("response-nonce"),
        payload_digest: Digest32::ZERO,
        observed_frontier: 7,
        expires_unix_ms: 800,
        items: vec![item(1), item(2), item(3)],
        completeness: FederatedCompletenessV2::Complete,
        terminal_observed: true,
        signature: Vec::new(),
    };
    response.payload_digest = response.compute_payload_digest();
    response.signature = response.signing_digest().as_array().to_vec();
    response
}

#[test]
fn canonical_signed_result_is_bounded_and_capability_capped() {
    let query = query(1);
    let lease = lease(&query);
    let result = execute_once(
        &Transport {
            response: FederationTransportResultV2::Terminal(response(&query, &lease)),
            clock_after_send: None,
            revoke_after_send: None,
        },
        &Authority::new(),
        &PeerVerifier,
        &Clock::new(10),
        query,
        &lease,
    )
    .unwrap_or_else(|error| panic!("valid result: {error}"));

    assert_eq!(result.items.len(), 2);
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.expires_unix_ms, 700);
    assert!(!result.authority.grants_any());
}

#[test]
fn partial_empty_stays_partial_and_payload_tampering_is_rejected() {
    let query = query(1);
    let lease = lease(&query);
    let mut partial = response(&query, &lease);
    partial.items.clear();
    partial.completeness = FederatedCompletenessV2::Partial;
    partial.payload_digest = partial.compute_payload_digest();
    partial.signature = partial.signing_digest().as_array().to_vec();
    let result = execute_once(
        &Transport {
            response: FederationTransportResultV2::Terminal(partial),
            clock_after_send: None,
            revoke_after_send: None,
        },
        &Authority::new(),
        &PeerVerifier,
        &Clock::new(10),
        query.clone(),
        &lease,
    )
    .unwrap_or_else(|error| panic!("partial result: {error}"));
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);

    let mut tampered = response(&query, &lease);
    tampered.items[0].record_digest = digest("tampered");
    assert_eq!(
        execute_once(
            &Transport {
                response: FederationTransportResultV2::Terminal(tampered),
                clock_after_send: None,
                revoke_after_send: None,
            },
            &Authority::new(),
            &PeerVerifier,
            &Clock::new(10),
            query,
            &lease,
        ),
        Err(FederationV2Error::DigestMismatch("response_payload"))
    );
}

#[test]
fn fresh_clock_and_revocation_are_rechecked_after_transport() {
    let query = query(1);
    let lease = lease(&query);
    let clock = Clock::new(10);
    let late = Transport {
        response: FederationTransportResultV2::Terminal(response(&query, &lease)),
        clock_after_send: Some((clock.clone(), query.deadline_unix_ms)),
        revoke_after_send: None,
    };
    assert_eq!(
        execute_once(
            &late,
            &Authority::new(),
            &PeerVerifier,
            &clock,
            query.clone(),
            &lease,
        ),
        Err(FederationV2Error::Legacy(
            crate::v2::FederationV2Error::DeadlineExpired
        ))
    );

    clock.set(10);
    let authority = Authority::new();
    let revoked = Transport {
        response: FederationTransportResultV2::Terminal(response(&query, &lease)),
        clock_after_send: None,
        revoke_after_send: Some(authority.revoked.clone()),
    };
    assert_eq!(
        execute_once(
            &revoked,
            &authority,
            &PeerVerifier,
            &clock,
            query,
            &lease,
        ),
        Err(FederationV2Error::AuthorityRevoked)
    );
}

#[test]
fn response_is_bound_to_query_nonce_and_peer_signature() {
    let query = query(1);
    let lease = lease(&query);
    let replay_query = query(2);
    let replay_lease = lease(&replay_query);
    assert_eq!(
        execute_once(
            &Transport {
                response: FederationTransportResultV2::Terminal(response(&query, &lease)),
                clock_after_send: None,
                revoke_after_send: None,
            },
            &Authority::new(),
            &PeerVerifier,
            &Clock::new(10),
            replay_query,
            &replay_lease,
        ),
        Err(FederationV2Error::DigestMismatch("response_query_binding"))
    );

    let mut bad_signature = response(&query, &lease);
    bad_signature.signature[0] ^= 1;
    assert_eq!(
        execute_once(
            &Transport {
                response: FederationTransportResultV2::Terminal(bad_signature),
                clock_after_send: None,
                revoke_after_send: None,
            },
            &Authority::new(),
            &PeerVerifier,
            &Clock::new(10),
            query,
            &lease,
        ),
        Err(FederationV2Error::InvalidSignature)
    );
}
