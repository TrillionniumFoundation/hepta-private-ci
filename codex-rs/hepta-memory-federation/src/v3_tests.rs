use super::*;

use std::sync::atomic::{AtomicU64, Ordering};

use ed25519_dalek::{Signer, SigningKey};

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn signing_key(byte: u8) -> SigningKey {
    SigningKey::from_bytes(&[byte; 32])
}

#[derive(Default)]
struct Keys {
    values: BTreeMap<(StableId, StableId), [u8; 32]>,
}

impl Keys {
    fn insert(&mut self, issuer: StableId, key: StableId, signing: &SigningKey) {
        self.values
            .insert((issuer, key), signing.verifying_key().to_bytes());
    }
}

impl FederationKeyResolverV3 for Keys {
    fn verification_key(
        &self,
        issuer_id: &StableId,
        key_id: &StableId,
    ) -> Option<[u8; 32]> {
        self.values
            .get(&(issuer_id.clone(), key_id.clone()))
            .copied()
    }
}

#[derive(Clone)]
struct Clock {
    now: Arc<AtomicU64>,
}

impl Clock {
    fn new(value: u64) -> Self {
        Self {
            now: Arc::new(AtomicU64::new(value)),
        }
    }

    fn set(&self, value: u64) {
        self.now.store(value, Ordering::SeqCst);
    }
}

impl FederationClockV3 for Clock {
    fn now_unix_ms(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
}

#[derive(Clone)]
struct Revocations {
    observation: Arc<Mutex<CapabilityRevocationObservationV3>>,
}

impl CapabilityRevocationSourceV3 for Revocations {
    fn current_revocation(
        &self,
        _grant_id: &StableId,
    ) -> Result<CapabilityRevocationObservationV3, FederationV3Error> {
        self.observation
            .lock()
            .map(|value| value.clone())
            .map_err(|_| FederationV3Error::TransportRejected)
    }
}

fn query(peer: &str) -> FederatedQueryV3 {
    FederatedQueryV3 {
        query_id: id(&format!("query:{peer}")),
        peer_id: id(peer),
        principal_id: id("principal:1"),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation"),
        query_digest: digest(&format!("query-body:{peer}")),
        maximum_results: 2,
        deadline_unix_ms: 100,
        lease_epoch: 7,
        request_nonce_digest: digest(&format!("request-nonce:{peer}")),
    }
}

fn signed_authority(
    query: &FederatedQueryV3,
    signing: &SigningKey,
    expires_unix_ms: u64,
) -> CapabilityAuthorityEnvelopeV3 {
    let mut value = CapabilityAuthorityEnvelopeV3 {
        issuer_id: id("authority:1"),
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
        revocation_epoch: 3,
        expires_unix_ms,
        proof_digest: Digest32::ZERO,
        signature: [0; 64],
    };
    value.proof_digest = value.compute_proof_digest();
    value.signature = signing.sign(value.proof_digest.as_array()).to_bytes();
    value
}

fn signed_revocation(
    grant_id: StableId,
    signing: &SigningKey,
    revoked: bool,
    epoch: u64,
    observed_unix_ms: u64,
) -> CapabilityRevocationObservationV3 {
    let mut value = CapabilityRevocationObservationV3 {
        issuer_id: id("authority:1"),
        key_id: id("authority-key:1"),
        grant_id,
        observed_revocation_epoch: epoch,
        revoked,
        observed_unix_ms,
        proof_digest: Digest32::ZERO,
        signature: [0; 64],
    };
    value.proof_digest = value.compute_proof_digest();
    value.signature = signing.sign(value.proof_digest.as_array()).to_bytes();
    value
}

fn item(number: u64) -> FederatedEvidenceItemV3 {
    FederatedEvidenceItemV3 {
        source_owner_id: id("owner:1"),
        record_id: id(&format!("record:{number}")),
        record_revision: revision(number),
        record_digest: digest(&format!("record:{number}")),
        support_digest: digest(&format!("support:{number}")),
        validity_digest: digest(&format!("validity:{number}")),
    }
}

fn signed_response(
    query: &FederatedQueryV3,
    authority: &CapabilityAuthorityEnvelopeV3,
    peer_key_id: &str,
    peer_signing: &SigningKey,
    completeness: FederatedCompletenessV3,
    items: Vec<FederatedEvidenceItemV3>,
    expires_unix_ms: u64,
) -> RemoteFederatedResponseV3 {
    let mut response = RemoteFederatedResponseV3 {
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        grant_id: authority.grant_id.clone(),
        key_id: id(peer_key_id),
        query_binding_digest: query.binding_digest(),
        request_nonce_digest: query.request_nonce_digest,
        response_nonce_digest: digest(&format!("response-nonce:{}", query.peer_id.as_str())),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        lease_epoch: query.lease_epoch,
        observed_frontier: 9,
        expires_unix_ms,
        items,
        completeness,
        terminal_observed: true,
        payload_digest: Digest32::ZERO,
        signature: [0; 64],
    };
    response.payload_digest = response.compute_payload_digest();
    response.signature = peer_signing
        .sign(response.payload_digest.as_array())
        .to_bytes();
    response
}

#[derive(Clone)]
struct FixtureTransport {
    response: FederationTransportResultV3,
    clock_after: Option<(Clock, u64)>,
    revoke_after: Option<(Revocations, CapabilityRevocationObservationV3)>,
}

impl FederationTransportV3 for FixtureTransport {
    fn send_once(
        &self,
        _query: &FederatedQueryV3,
        _deadline_unix_ms: u64,
        cancellation: &FederationCancellationTokenV3,
    ) -> Result<FederationTransportResultV3, FederationV3Error> {
        if cancellation.is_cancelled() {
            return Ok(FederationTransportResultV3::NonTerminal(
                FederationTransportOutcomeV3::Cancelled,
            ));
        }
        if let Some((clock, value)) = &self.clock_after {
            clock.set(*value);
        }
        if let Some((source, next)) = &self.revoke_after {
            *source
                .observation
                .lock()
                .map_err(|_| FederationV3Error::TransportRejected)? = next.clone();
        }
        Ok(self.response.clone())
    }
}

struct EnrolledPeers(BTreeSet<StableId>);

impl PeerEnrollmentRegistryV3 for EnrolledPeers {
    fn is_enrolled(&self, peer_id: &StableId) -> bool {
        self.0.contains(peer_id)
    }
}

struct Fixture {
    authority_signing: SigningKey,
    peer_signing: SigningKey,
    keys: Keys,
    clock: Clock,
    revocations: Revocations,
}

impl Fixture {
    fn new(query: &FederatedQueryV3) -> (Self, CapabilityAuthorityEnvelopeV3) {
        let authority_signing = signing_key(3);
        let peer_signing = signing_key(9);
        let authority = signed_authority(query, &authority_signing, 90);
        let revocation = signed_revocation(
            authority.grant_id.clone(),
            &authority_signing,
            false,
            authority.revocation_epoch,
            10,
        );
        let revocations = Revocations {
            observation: Arc::new(Mutex::new(revocation)),
        };
        let mut keys = Keys::default();
        keys.insert(
            authority.issuer_id.clone(),
            authority.key_id.clone(),
            &authority_signing,
        );
        keys.insert(query.peer_id.clone(), id("peer-key:1"), &peer_signing);
        (
            Self {
                authority_signing,
                peer_signing,
                keys,
                clock: Clock::new(10),
                revocations,
            },
            authority,
        )
    }
}

#[test]
fn partial_zero_items_is_preserved_and_ttl_is_authority_bounded() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Partial,
        Vec::new(),
        95,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: None,
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    let result = execute_once_v3(
        &transport,
        &fixture.clock,
        &verifier,
        &fixture.keys,
        query,
        &authority,
        &FederationCancellationTokenV3::default(),
    )
    .unwrap_or_else(|error| panic!("valid v3 result: {error}"));
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV3::Partial);
    assert_eq!(result.expires_unix_ms, 90);
}

#[test]
fn remote_payload_tampering_is_rejected_cryptographically() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let mut response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    response.items[0].record_digest = digest("tampered");
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: None,
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    assert_eq!(
        execute_once_v3(
            &transport,
            &fixture.clock,
            &verifier,
            &fixture.keys,
            query,
            &authority,
            &FederationCancellationTokenV3::default(),
        ),
        Err(FederationV3Error::DigestMismatch("remote_payload"))
    );
}

#[test]
fn transport_returning_after_deadline_is_rejected_using_fresh_clock() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        120,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: Some((fixture.clock.clone(), 101)),
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 200,
    };
    assert_eq!(
        execute_once_v3(
            &transport,
            &fixture.clock,
            &verifier,
            &fixture.keys,
            query,
            &authority,
            &FederationCancellationTokenV3::default(),
        ),
        Err(FederationV3Error::DeadlineExpired)
    );
}

#[test]
fn revocation_during_io_is_revalidated_and_fails_closed() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    let revoked = signed_revocation(
        authority.grant_id.clone(),
        &fixture.authority_signing,
        true,
        authority.revocation_epoch,
        11,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: Some((fixture.clock.clone(), 11)),
        revoke_after: Some((fixture.revocations.clone(), revoked)),
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    assert_eq!(
        execute_once_v3(
            &transport,
            &fixture.clock,
            &verifier,
            &fixture.keys,
            query,
            &authority,
            &FederationCancellationTokenV3::default(),
        ),
        Err(FederationV3Error::LeaseRevoked)
    );
}

#[test]
fn response_from_another_query_cannot_be_replayed() {
    let query_a = query("peer:1");
    let (fixture, authority_a) = Fixture::new(&query_a);
    let query_b = FederatedQueryV3 {
        query_id: id("query:other"),
        query_digest: digest("different-query"),
        request_nonce_digest: digest("different-nonce"),
        ..query_a.clone()
    };
    let authority_b = signed_authority(&query_b, &fixture.authority_signing, 90);
    let response_a = signed_response(
        &query_a,
        &authority_a,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response_a),
        clock_after: None,
        revoke_after: None,
    };
    let revocation_b = signed_revocation(
        authority_b.grant_id.clone(),
        &fixture.authority_signing,
        false,
        authority_b.revocation_epoch,
        10,
    );
    *fixture.revocations.observation.lock().unwrap() = revocation_b;
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    assert_eq!(
        execute_once_v3(
            &transport,
            &fixture.clock,
            &verifier,
            &fixture.keys,
            query_b,
            &authority_b,
            &FederationCancellationTokenV3::default(),
        ),
        Err(FederationV3Error::DigestMismatch("response_query_binding"))
    );
}

#[test]
fn pre_cancelled_request_never_exposes_remote_data() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: None,
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    let cancellation = FederationCancellationTokenV3::default();
    cancellation.cancel();
    let result = execute_once_v3(
        &transport,
        &fixture.clock,
        &verifier,
        &fixture.keys,
        query,
        &authority,
        &cancellation,
    )
    .unwrap();
    assert!(result.items.is_empty());
    assert_eq!(result.completeness, FederatedCompletenessV3::Indeterminate);
}

#[test]
fn cache_revalidates_and_purges_by_grant() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: None,
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    let result = execute_once_v3(
        &transport,
        &fixture.clock,
        &verifier,
        &fixture.keys,
        query.clone(),
        &authority,
        &FederationCancellationTokenV3::default(),
    )
    .unwrap();
    let cache_id = id("cache:1");
    let mut cache = FederatedResultCacheV3::default();
    cache
        .insert(FederatedCacheEntryV3 {
            cache_id: cache_id.clone(),
            query,
            authority: authority.clone(),
            result,
        })
        .unwrap();
    assert!(cache
        .get_revalidated(&cache_id, 10, &verifier)
        .unwrap()
        .is_some());
    assert_eq!(cache.purge_grant(&authority.grant_id), 1);
    assert!(cache
        .get_revalidated(&cache_id, 10, &verifier)
        .unwrap()
        .is_none());
}

#[test]
fn service_rejects_unenrolled_peer_before_transport() {
    let query = query("peer:1");
    let (fixture, authority) = Fixture::new(&query);
    let response = signed_response(
        &query,
        &authority,
        "peer-key:1",
        &fixture.peer_signing,
        FederatedCompletenessV3::Complete,
        vec![item(1)],
        80,
    );
    let transport = FixtureTransport {
        response: FederationTransportResultV3::Terminal(response),
        clock_after: None,
        revoke_after: None,
    };
    let verifier = SignedCapabilityVerifierV3 {
        keys: &fixture.keys,
        revocations: &fixture.revocations,
        max_revocation_age_ms: 20,
    };
    let service = FederationServiceV3::new(
        transport,
        fixture.clock.clone(),
        verifier,
        &fixture.keys,
        EnrolledPeers(BTreeSet::new()),
    );
    assert_eq!(
        service.query_peer(
            query,
            authority,
            &FederationCancellationTokenV3::default(),
        ),
        Err(FederationV3Error::PeerNotEnrolled)
    );
}
