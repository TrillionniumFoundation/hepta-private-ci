use super::*;

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering as AtomicOrdering;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use futures::FutureExt;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn system_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64
}

struct AuthorityFixture {
    authority: FinalUseAuthority,
    issuer: SigningKey,
    _directory: tempfile::TempDir,
}

fn authority_fixture() -> AuthorityFixture {
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let directory = tempfile::tempdir().expect("tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private state dir");
    let authority = FinalUseAuthority::open_state_dir(
        directory.path(),
        "security-owner".to_owned(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    AuthorityFixture {
        authority,
        issuer,
        _directory: directory,
    }
}

#[derive(Clone)]
struct ScriptedClock {
    samples: Arc<Mutex<VecDeque<u64>>>,
}

impl ScriptedClock {
    fn fixed(value: u64) -> Self {
        Self::new([value])
    }

    fn new(values: impl IntoIterator<Item = u64>) -> Self {
        let values = values.into_iter().collect::<VecDeque<_>>();
        assert!(!values.is_empty());
        Self {
            samples: Arc::new(Mutex::new(values)),
        }
    }
}

impl FederationClockV3 for ScriptedClock {
    fn now_unix_ms(&self) -> Result<u64, FederationV3Error> {
        let mut samples = self.samples.lock().map_err(|_| FederationV3Error::ClockUnavailable)?;
        if samples.len() > 1 {
            samples.pop_front().ok_or(FederationV3Error::ClockUnavailable)
        } else {
            samples.front().copied().ok_or(FederationV3Error::ClockUnavailable)
        }
    }
}

fn spec(query_id: &str, deadline: u64, maximum_results: u32) -> FederatedReadSpecV3 {
    FederatedReadSpecV3 {
        query_id: id(query_id),
        principal_id: id("principal:1"),
        scope_digest: digest("scope"),
        purpose_digest: digest("purpose"),
        generation_vector_digest: digest("generation"),
        query_digest: digest("query"),
        maximum_results,
        deadline_unix_ms: deadline,
    }
}

fn target(peer: &str, nonce: &str) -> FederatedPeerTargetV3 {
    FederatedPeerTargetV3 {
        peer_id: id(peer),
        authority_epoch: 9,
        request_nonce_digest: digest(nonce),
    }
}

fn signed_grant(
    issuer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce_byte: u8,
) -> SignedFinalUseGrant {
    let now = system_now();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_owned(),
        authority_epoch: 9,
        grant_id: grant_id.to_owned(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 120_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn permit(
    spec: &FederatedReadSpecV3,
    issuer: &SigningKey,
    peer: &str,
    nonce_label: &str,
    grant_id: &str,
    nonce_byte: u8,
) -> FederatedPeerPermitV3 {
    let target = target(peer, nonce_label);
    let binding = spec.authority_binding(&target).expect("authority binding");
    FederatedPeerPermitV3 {
        target,
        signed_grant: signed_grant(issuer, binding, grant_id, nonce_byte),
    }
}

fn enrollment(peer: &str, key_id: &str, signing_key: &SigningKey, expiry: u64) -> FederatedPeerEnrollmentV3 {
    FederatedPeerEnrollmentV3 {
        peer_id: id(peer),
        endpoint: "https://federation.example.test/".to_owned(),
        ca_pem: b"-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n".to_vec(),
        key_id: key_id.to_owned(),
        verifying_key: signing_key.verifying_key().to_bytes(),
        enrollment_epoch: 4,
        expires_unix_ms: expiry,
        revoked: false,
    }
}

fn item(owner: &str, record: &str, rev: u64) -> FederatedEvidenceItemV2 {
    FederatedEvidenceItemV2 {
        source_owner_id: id(owner),
        record_id: id(record),
        record_revision: revision(rev),
        record_digest: digest(&format!("record:{owner}:{record}:{rev}")),
        support_digest: digest(&format!("support:{owner}:{record}:{rev}")),
        validity_digest: digest(&format!("validity:{owner}:{record}:{rev}")),
    }
}

fn signed_response(
    attempt: &FederatedAttemptV3,
    peer_signing_key: &SigningKey,
    completeness: FederatedCompletenessV2,
    items: Vec<FederatedEvidenceItemV2>,
    expiry: u64,
) -> RemoteFederatedEnvelopeV3 {
    let mut response = RemoteFederatedEnvelopeV3 {
        query_id: attempt.query.query_id.clone(),
        peer_id: attempt.query.peer_id.clone(),
        principal_id: attempt.query.principal_id.clone(),
        scope_digest: attempt.query.scope_digest,
        purpose_digest: attempt.query.purpose_digest,
        generation_vector_digest: attempt.query.generation_vector_digest,
        query_binding_digest: attempt.query.binding_digest(),
        request_nonce_digest: attempt.query.request_nonce_digest,
        authority_epoch: attempt.query.authority_epoch,
        grant_id: attempt.grant.grant.grant_id.clone(),
        response_nonce_digest: digest(&format!("response-nonce:{}", attempt.query.peer_id.as_str())),
        key_id: attempt.enrollment.key_id.clone(),
        observed_frontier: 17,
        expires_unix_ms: expiry,
        items,
        completeness,
        terminal_observed: true,
        payload_digest: Digest32::ZERO,
        signature: Vec::new(),
    };
    response.payload_digest = response.compute_payload_digest();
    response.signature = peer_signing_key
        .sign(&response.signature_message())
        .to_bytes()
        .to_vec();
    response
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FixtureOutcome {
    Complete,
    Empty,
    PartialEmpty,
    Unavailable,
    Tampered,
}

#[derive(Clone)]
struct FixtureTransport {
    peer_keys: Arc<BTreeMap<StableId, SigningKey>>,
    outcomes: Arc<BTreeMap<StableId, FixtureOutcome>>,
    response_expiry: u64,
    revoke_during_send: Option<(FinalUseAuthority, String)>,
    active: Option<Arc<AtomicUsize>>,
    maximum_active: Option<Arc<AtomicUsize>>,
    delay_ms: u64,
}

impl FixtureTransport {
    fn simple<I, P>(peers: I, response_expiry: u64) -> Self
    where
        I: IntoIterator<Item = (P, SigningKey, FixtureOutcome)>,
        P: AsRef<str>,
    {
        let mut peer_keys = BTreeMap::new();
        let mut outcomes = BTreeMap::new();
        for (peer, key, outcome) in peers {
            peer_keys.insert(id(peer.as_ref()), key);
            outcomes.insert(id(peer.as_ref()), outcome);
        }
        Self {
            peer_keys: Arc::new(peer_keys),
            outcomes: Arc::new(outcomes),
            response_expiry,
            revoke_during_send: None,
            active: None,
            maximum_active: None,
            delay_ms: 0,
        }
    }
}

impl FederationTransportV3 for FixtureTransport {
    fn send_once<'a>(
        &'a self,
        attempt: FederatedAttemptV3,
        cancellation: FederationCancellationTokenV3,
    ) -> BoxFuture<'a, Result<FederationTransportResultV3, FederationV3Error>> {
        async move {
            let _active_guard = if let (Some(active), Some(maximum)) = (&self.active, &self.maximum_active) {
                let now = active.fetch_add(1, AtomicOrdering::AcqRel) + 1;
                maximum.fetch_max(now, AtomicOrdering::AcqRel);
                Some(ActiveGuard(Arc::clone(active)))
            } else {
                None
            };
            if self.delay_ms > 0 {
                tokio::select! {
                    _ = cancellation.cancelled() => {
                        return Ok(FederationTransportResultV3::NonTerminal(FederationTransportOutcomeV3::Cancelled));
                    }
                    _ = tokio::time::sleep(Duration::from_millis(self.delay_ms)) => {}
                }
            }
            if cancellation.is_cancelled() {
                return Ok(FederationTransportResultV3::NonTerminal(
                    FederationTransportOutcomeV3::Cancelled,
                ));
            }
            if let Some((authority, grant_id)) = &self.revoke_during_send {
                authority
                    .update_revocations(FinalUseRevocations {
                        authority_epoch: 9,
                        revision: 2,
                        revoked_grant_ids: BTreeSet::from([grant_id.clone()]),
                    })
                    .expect("revoke during transport");
            }
            let outcome = self
                .outcomes
                .get(&attempt.query.peer_id)
                .copied()
                .unwrap_or(FixtureOutcome::Unavailable);
            if matches!(outcome, FixtureOutcome::Unavailable) {
                return Ok(FederationTransportResultV3::NonTerminal(
                    FederationTransportOutcomeV3::Unavailable,
                ));
            }
            let signing_key = self.peer_keys.get(&attempt.query.peer_id).expect("peer key");
            let (completeness, items) = match outcome {
                FixtureOutcome::Complete => (
                    FederatedCompletenessV2::Complete,
                    vec![item("owner:1", &format!("record:{}", attempt.query.peer_id.as_str()), 1)],
                ),
                FixtureOutcome::Empty => (FederatedCompletenessV2::Empty, Vec::new()),
                FixtureOutcome::PartialEmpty => (FederatedCompletenessV2::Partial, Vec::new()),
                FixtureOutcome::Tampered => (
                    FederatedCompletenessV2::Complete,
                    vec![item("owner:1", &format!("record:{}", attempt.query.peer_id.as_str()), 1)],
                ),
                FixtureOutcome::Unavailable => unreachable!(),
            };
            let mut response = signed_response(
                &attempt,
                signing_key,
                completeness,
                items,
                self.response_expiry,
            );
            if matches!(outcome, FixtureOutcome::Tampered) {
                response.items[0].support_digest = digest("tampered-after-signing");
            }
            Ok(FederationTransportResultV3::Terminal(response))
        }
        .boxed()
    }
}

struct ActiveGuard(Arc<AtomicUsize>);
impl Drop for ActiveGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, AtomicOrdering::AcqRel);
    }
}

#[derive(Clone)]
struct BlockingTransport;

impl FederationTransportV3 for BlockingTransport {
    fn send_once<'a>(
        &'a self,
        _attempt: FederatedAttemptV3,
        cancellation: FederationCancellationTokenV3,
    ) -> BoxFuture<'a, Result<FederationTransportResultV3, FederationV3Error>> {
        async move {
            cancellation.cancelled().await;
            Ok(FederationTransportResultV3::NonTerminal(
                FederationTransportOutcomeV3::Cancelled,
            ))
        }
        .boxed()
    }
}

fn registry(
    now: u64,
    peers: &[(&str, &str, &SigningKey, u64)],
) -> FederationPeerRegistryV3 {
    FederationPeerRegistryV3::new(
        peers
            .iter()
            .map(|(peer, key_id, key, expiry)| enrollment(peer, key_id, key, *expiry))
            .collect(),
        now,
    )
    .expect("registry")
}
