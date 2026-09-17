use std::future::pending;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use codex_hepta_types::{AuthorityPosture, Digest32, Revision, StableId};
use ed25519_dalek::{Signer, SigningKey};
use tokio_util::sync::CancellationToken;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn query(peer: u64) -> FederatedQueryV2 {
    FederatedQueryV2 {
        query_id: id(&format!("query:{peer}")),
        peer_id: id(&format!("peer:{peer}")),
        principal_id: id("principal:consumer"),
        grant_id: id(&format!("grant:{peer}")),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation-vector"),
        query_digest: digest(&format!("query-body:{peer}")),
        maximum_results: 2,
        deadline_unix_ms: 1_000,
        grant_epoch: 7,
        lease_epoch: 11,
        nonce_digest: digest(&format!("request-nonce:{peer}")),
    }
}

fn lease(query: &FederatedQueryV2) -> FederatedLeaseV2 {
    FederatedLeaseV2 {
        lease_id: id(&format!("lease:{}", query.peer_id.as_str())),
        grant_id: query.grant_id.clone(),
        issuer_id: id("authority:memory"),
        issuer_key_id: id("authority-key:1"),
        query_id: query.query_id.clone(),
        peer_id: query.peer_id.clone(),
        principal_id: query.principal_id.clone(),
        scope_digest: query.scope_digest,
        purpose_digest: query.purpose_digest,
        generation_vector_digest: query.generation_vector_digest,
        query_binding_digest: query.binding_digest(),
        grant_epoch: query.grant_epoch,
        lease_epoch: query.lease_epoch,
        expires_unix_ms: 900,
        authority_proof_digest: digest("authority-proof"),
    }
}

fn item(owner: &StableId, number: u64) -> FederatedEvidenceItemV2 {
    FederatedEvidenceItemV2 {
        source_owner_id: owner.clone(),
        record_id: id(&format!("record:{number}")),
        record_revision: revision(number),
        record_digest: digest(&format!("record-{number}")),
        support_digest: digest(&format!("support-{number}")),
        validity_digest: digest(&format!("validity-{number}")),
    }
}

#[derive(Clone)]
struct ManualClock {
    now: Arc<AtomicU64>,
}

impl ManualClock {
    fn new(now: u64) -> Self {
        Self {
            now: Arc::new(AtomicU64::new(now)),
        }
    }

    fn set(&self, now: u64) {
        self.now.store(now, Ordering::SeqCst);
    }
}

impl FederationClockV2 for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, FederationV2Error> {
        Ok(self.now.load(Ordering::SeqCst))
    }
}

#[derive(Clone)]
struct FixtureAuthority {
    revoked: Arc<AtomicBool>,
    revocation_epoch: Arc<AtomicU64>,
    expires_unix_ms: u64,
}

impl FixtureAuthority {
    fn new(expires_unix_ms: u64) -> Self {
        Self {
            revoked: Arc::new(AtomicBool::new(false)),
            revocation_epoch: Arc::new(AtomicU64::new(3)),
            expires_unix_ms,
        }
    }

    fn receipt(
        &self,
        query: &FederatedQueryV2,
        lease: &FederatedLeaseV2,
    ) -> Result<VerifiedCapabilityReceiptV2, FederationV2Error> {
        if self.revoked.load(Ordering::SeqCst) {
            return Err(FederationV2Error::LeaseRevoked);
        }
        let revocation_epoch = self.revocation_epoch.load(Ordering::SeqCst);
        let mut proof = Vec::new();
        proof.extend_from_slice(query.binding_digest().as_array());
        proof.extend_from_slice(&revocation_epoch.to_be_bytes());
        Ok(VerifiedCapabilityReceiptV2 {
            issuer_id: lease.issuer_id.clone(),
            issuer_key_id: lease.issuer_key_id.clone(),
            grant_id: query.grant_id.clone(),
            lease_id: lease.lease_id.clone(),
            peer_id: query.peer_id.clone(),
            principal_id: query.principal_id.clone(),
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            generation_vector_digest: query.generation_vector_digest,
            query_binding_digest: query.binding_digest(),
            grant_epoch: query.grant_epoch,
            lease_epoch: query.lease_epoch,
            revocation_epoch,
            expires_unix_ms: self.expires_unix_ms.min(lease.expires_unix_ms),
            verification_digest: Digest32::of_bytes(&proof),
        })
    }
}

impl FederationAuthorityV2 for FixtureAuthority {
    fn verify_for_query<'a>(
        &'a self,
        _now_unix_ms: u64,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
    ) -> FederationAuthorityFutureV2<'a> {
        Box::pin(async move { self.receipt(query, lease) })
    }

    fn revalidate<'a>(
        &'a self,
        _now_unix_ms: u64,
        query: &'a FederatedQueryV2,
        lease: &'a FederatedLeaseV2,
        _previous: &'a VerifiedCapabilityReceiptV2,
    ) -> FederationAuthorityFutureV2<'a> {
        Box::pin(async move { self.receipt(query, lease) })
    }
}

#[derive(Clone, Copy)]
enum FixtureMode {
    Complete,
    PartialEmpty,
    InvalidPayloadDigest,
    InvalidSignature,
    NonTerminal,
    PartialPeerTwo,
    Pending,
}

#[derive(Clone)]
struct FixtureTransport {
    signing_key: SigningKey,
    mode: FixtureMode,
    clock_after_send: Option<ManualClock>,
    post_send_now: Option<u64>,
    revoke_after_send: Option<Arc<AtomicBool>>,
    captured_cancellation: Arc<Mutex<Option<CancellationToken>>>,
}

impl FixtureTransport {
    fn new(signing_key: SigningKey, mode: FixtureMode) -> Self {
        Self {
            signing_key,
            mode,
            clock_after_send: None,
            post_send_now: None,
            revoke_after_send: None,
            captured_cancellation: Arc::new(Mutex::new(None)),
        }
    }

    fn response(
        &self,
        query: &FederatedQueryV2,
        capability: &VerifiedCapabilityReceiptV2,
    ) -> RemoteFederatedResponseV2 {
        let partial_empty = matches!(self.mode, FixtureMode::PartialEmpty)
            || (matches!(self.mode, FixtureMode::PartialPeerTwo)
                && query.peer_id == id("peer:2"));
        let items = if partial_empty {
            Vec::new()
        } else {
            vec![item(&query.peer_id, 1)]
        };
        let mut response = RemoteFederatedResponseV2 {
            peer_id: query.peer_id.clone(),
            peer_key_id: id("peer-key:1"),
            peer_key_epoch: 5,
            query_binding_digest: query.binding_digest(),
            request_nonce_digest: query.nonce_digest,
            grant_id: query.grant_id.clone(),
            lease_id: capability.lease_id.clone(),
            grant_epoch: capability.grant_epoch,
            lease_epoch: capability.lease_epoch,
            revocation_epoch: capability.revocation_epoch,
            scope_digest: query.scope_digest,
            purpose_digest: query.purpose_digest,
            generation_vector_digest: query.generation_vector_digest,
            response_nonce_digest: digest(&format!("response-nonce:{}", query.peer_id.as_str())),
            payload_digest: Digest32::ZERO,
            response_digest: Digest32::ZERO,
            observed_frontier: 17,
            expires_unix_ms: 950,
            items,
            completeness: if partial_empty {
                FederatedCompletenessV2::Partial
            } else {
                FederatedCompletenessV2::Complete
            },
            terminal_observed: true,
            signature: [0; 64],
        };
        response.payload_digest = response.compute_payload_digest();
        response.response_digest = response.compute_response_digest();
        response.signature = self.signing_key.sign(&response.signing_bytes()).to_bytes();
        match self.mode {
            FixtureMode::InvalidPayloadDigest => {
                response.items[0].record_digest = digest("tampered-after-signature");
            }
            FixtureMode::InvalidSignature => {
                response.signature[0] ^= 1;
            }
            _ => {}
        }
        response
    }
}

impl FederationTransportV2 for FixtureTransport {
    fn send_once<'a>(
        &'a self,
        query: &'a FederatedQueryV2,
        capability: &'a VerifiedCapabilityReceiptV2,
        cancellation: CancellationToken,
    ) -> FederationTransportFutureV2<'a> {
        if let Ok(mut captured) = self.captured_cancellation.lock() {
            *captured = Some(cancellation.clone());
        }
        Box::pin(async move {
            if matches!(self.mode, FixtureMode::Pending) {
                return pending::<Result<FederationTransportResultV2, FederationV2Error>>().await;
            }
            if let (Some(clock), Some(now)) = (&self.clock_after_send, self.post_send_now) {
                clock.set(now);
            }
            if let Some(revoked) = &self.revoke_after_send {
                revoked.store(true, Ordering::SeqCst);
            }
            if matches!(self.mode, FixtureMode::NonTerminal) {
                return Ok(FederationTransportResultV2::NonTerminal(
                    FederationTransportOutcomeV2::Unavailable,
                ));
            }
            Ok(FederationTransportResultV2::Terminal(Box::new(
                self.response(query, capability),
            )))
        })
    }
}

fn peer_directory(signing_key: &SigningKey, peers: &[u64]) -> TrustedPeerSnapshotV2 {
    TrustedPeerSnapshotV2::from_records(
        peers
            .iter()
            .map(|peer| PeerTrustV2 {
                peer_id: id(&format!("peer:{peer}")),
                key_id: id("peer-key:1"),
                key_epoch: 5,
                verifying_key: signing_key.verifying_key(),
                enabled: true,
            })
            .collect(),
    )
    .unwrap_or_else(|error| panic!("valid peer snapshot: {error}"))
}

async fn execute_fixture(
    transport: &FixtureTransport,
    authority: &FixtureAuthority,
    peers: &TrustedPeerSnapshotV2,
    clock: &ManualClock,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> Result<FederatedResultV2, FederationV2Error> {
    execute_once(
        transport,
        authority,
        peers,
        clock,
        &CancellationToken::new(),
        query,
        lease,
    )
    .await
}
