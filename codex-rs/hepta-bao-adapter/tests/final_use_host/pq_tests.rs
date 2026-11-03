//! PQ final-use composition through the original HTTPS client and registered
//! consumer. AuthBus and HTTPS peer authentication keep their existing profiles;
//! this test does not establish an entirely PQ Bao deployment. Clock/frontier
//! fixtures exercise the trust interfaces without claiming external durability.
use super::unix::ManualClock;
use super::unix::delayed_server;
use codex_hepta_bao_adapter::BaoClient;
use codex_hepta_bao_adapter::BaoClientError;
use codex_hepta_bao_adapter::BaoFinalUseHost;
use codex_hepta_bao_adapter::BaoFinalUseHostError;
use codex_hepta_bao_adapter::BaoReadRequest;
use codex_hepta_bao_adapter::BaoSecretReceipt;
use codex_hepta_bao_adapter::BaoToken;
use codex_hepta_bao_adapter::RegisteredBaoConsumer;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApproval;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

const SECRET: &str = "pq-fixture-secret";

#[path = "cold_restart_tests.rs"]
mod cold_restart;

#[path = "lease_tests.rs"]
mod leases;

#[path = "dispatch_window_tests.rs"]
mod dispatch_window;

#[path = "claimed_head_tests.rs"]
mod claimed_head;

struct TestFrontier {
    current: Mutex<FinalUseFrontier>,
    writes: AtomicUsize,
    before_return: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}

impl AuthorityFrontierStore<FinalUseFrontier> for TestFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != "security-owner" {
            return Err(AuthorityTrustError::Invalid);
        }
        self.current
            .lock()
            .map(|current| *current)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != "security-owner" {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut current = self
            .current
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *current != *expected
            || next.authority_epoch < expected.authority_epoch
            || (next.authority_epoch == expected.authority_epoch
                && next.revocation_revision < expected.revocation_revision)
        {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        self.writes.fetch_add(1, Ordering::SeqCst);
        if let Some(pause) = self.before_return.lock().unwrap().take() {
            pause();
        }
        Ok(())
    }
}

fn pq_key(seed: u8, key_id: &str) -> (PqNativeSigningKey, PqAuthorityTrustKey) {
    let seed = [seed; 32].into();
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let public_key_id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
    (
        PqNativeSigningKey::from_owned_seed(seed, public_key_id).unwrap(),
        PqAuthorityTrustKey {
            key_id: key_id.into(),
            public_key_id,
            public_key_spki: spki.to_vec(),
            not_before_authority_epoch: 6,
            not_after_authority_epoch: 6,
        },
    )
}

struct PqFixture<C> {
    host: BaoFinalUseHost,
    authority: FinalUseAuthority,
    request: BaoReadRequest,
    grant: SignedFinalUseGrant,
    approval: SignedFinalUseApproval,
    feed: SignedFinalUseRevocationUpdate,
    issuer: PqNativeSigningKey,
    approver: PqNativeSigningKey,
    distributor: PqNativeSigningKey,
    clock: Arc<C>,
    frontier: Arc<TestFrontier>,
    _state: tempfile::TempDir,
}

fn registered_consumer(callbacks: Arc<AtomicUsize>) -> RegisteredBaoConsumer {
    RegisteredBaoConsumer::new(
        "model-provider".into(),
        Arc::new(move |bytes| {
            if bytes != SECRET.as_bytes() {
                return Err(());
            }
            callbacks.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }),
    )
    .unwrap()
}

impl<C: AuthorityClock + 'static> PqFixture<C> {
    fn new(
        client: &BaoClient,
        clock: Arc<C>,
        callbacks: Arc<AtomicUsize>,
        feed_expires_at: u64,
    ) -> Self {
        let request = BaoReadRequest {
            subject_id: "agent-one".into(),
            consumer_id: "model-provider".into(),
            namespace: "team/one".into(),
            mount: "secret".into(),
            path: "provider/token".into(),
            field: "value".into(),
            version: 1,
            expected_secret_sha256: Digest32::of_bytes(SECRET.as_bytes()).into_array(),
        };
        let (issuer, issuer_pin) = pq_key(/*seed*/ 71, "issuer-key");
        let (approver, approver_pin) = pq_key(/*seed*/ 72, "operator-key");
        let (distributor, distributor_pin) = pq_key(/*seed*/ 73, "feed-key");
        let head = FinalUseRevocations {
            authority_epoch: 6,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let frontier = Arc::new(TestFrontier {
            current: Mutex::new(
                FinalUseFrontier::for_initial_head_with_profile(
                    &head,
                    FinalUseAuthenticationProfile::MlDsa65V2,
                )
                .unwrap(),
            ),
            writes: AtomicUsize::new(0),
            before_return: Mutex::new(None),
        });
        let state = tempfile::tempdir().unwrap();
        std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            state.path(),
            "security-owner".into(),
            vec![issuer_pin],
            head,
            clock.clone(),
            frontier.clone(),
        )
        .unwrap();
        let approval_verifier = FinalUseApprovalVerifier::new_pq_with_keys(
            "operator-approver".into(),
            vec![approver_pin],
        )
        .unwrap();
        let feed_verifier = FinalUseRevocationFeedVerifier::new_pq_with_keys(
            "revocation-distributor".into(),
            vec![distributor_pin],
        )
        .unwrap();
        let host = BaoFinalUseHost::new(
            authority.clone(),
            approval_verifier,
            feed_verifier,
            clock.clone(),
            [registered_consumer(callbacks)],
        )
        .unwrap();
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: "security-owner".into(),
            authority_epoch: 6,
            grant_id: "pq-host-read".into(),
            nonce: [31; 32],
            binding: client.binding(&request).unwrap(),
            not_before_unix_ms: 9_000,
            expires_at_unix_ms: 20_000,
        };
        let grant = SignedFinalUseGrant {
            signature: issuer
                .sign_exact_message(&grant.signing_bytes().unwrap())
                .unwrap()
                .to_vec(),
            grant,
        };
        let approval =
            FinalUseApproval::for_grant("operator-approver".into(), &grant.grant).unwrap();
        let approval = SignedFinalUseApproval {
            signature: approver
                .sign_exact_message(&approval.signing_bytes().unwrap())
                .unwrap()
                .to_vec(),
            approval,
        };
        let update = FinalUseRevocationUpdate::new_pq(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 6,
                revision: 2,
                revoked_grant_ids: BTreeSet::new(),
            },
            /*issued_at_unix_ms*/ 9_500,
            feed_expires_at,
        );
        let feed = SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign_exact_message(&update.signing_bytes().unwrap())
                .unwrap()
                .to_vec(),
            update,
        };
        Self {
            host,
            authority,
            request,
            grant,
            approval,
            feed,
            issuer,
            approver,
            distributor,
            clock,
            frontier,
            _state: state,
        }
    }
}

#[tokio::test]
async fn pq_role_proofs_gate_real_https_delivery_and_exact_nonce_replay() {
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let calls = provider_calls.clone();
    let body =
        serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}}).to_string();
    let (endpoint, ca, task) = delayed_server(body.clone(), move || {
        calls.fetch_add(1, Ordering::SeqCst);
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let callbacks = Arc::new(AtomicUsize::new(0));
    let fixture = PqFixture::new(
        &client,
        Arc::new(ManualClock::new(/*now_unix_ms*/ 10_000)),
        callbacks.clone(),
        /*feed_expires_at*/ 20_000,
    );
    let initial = fixture.authority.frontier().unwrap();
    let classic = SigningKey::from_bytes(&[99; 32]);

    let mut corrupt_feed = fixture.feed.clone();
    corrupt_feed.signature[0] ^= 1;
    let mut wrong_role_feed = fixture.feed.clone();
    wrong_role_feed.signature = fixture
        .approver
        .sign_exact_message(&wrong_role_feed.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    let mut classic_signature_feed = fixture.feed.clone();
    classic_signature_feed.signature = classic
        .sign(&classic_signature_feed.update.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let mut classic_wire_feed = fixture.feed.clone();
    classic_wire_feed.update.schema_version = 2;
    classic_wire_feed.signature = fixture
        .distributor
        .sign_exact_message(&classic_wire_feed.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    for (feed, error) in [
        (corrupt_feed, FinalUseControlError::InvalidSignature),
        (wrong_role_feed, FinalUseControlError::InvalidSignature),
        (
            classic_signature_feed,
            FinalUseControlError::InvalidSignature,
        ),
        (
            classic_wire_feed,
            FinalUseControlError::InvalidRevocationUpdate,
        ),
    ] {
        assert_eq!(
            fixture.host.apply_revocation_update(&feed),
            Err(BaoFinalUseHostError::Control(error))
        );
        assert_eq!(
            fixture
                .host
                .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
                .await,
            Err(BaoFinalUseHostError::StaleRevocationFeed)
        );
        assert_eq!(fixture.authority.frontier().unwrap(), initial);
        assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
        assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    }
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    let admitted = fixture.authority.frontier().unwrap();
    let mut corrupt_approval = fixture.approval.clone();
    corrupt_approval.signature[0] ^= 1;
    let mut wrong_role_approval = fixture.approval.clone();
    wrong_role_approval.signature = fixture
        .issuer
        .sign_exact_message(&wrong_role_approval.approval.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    let mut classic_signature_approval = fixture.approval.clone();
    classic_signature_approval.signature = classic
        .sign(&classic_signature_approval.approval.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let mut classic_wire_approval = fixture.approval.clone();
    classic_wire_approval.approval.schema_version = 1;
    classic_wire_approval.signature = fixture
        .approver
        .sign_exact_message(&classic_wire_approval.approval.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    for (approval, error) in [
        (corrupt_approval, FinalUseControlError::InvalidSignature),
        (wrong_role_approval, FinalUseControlError::InvalidSignature),
        (
            classic_signature_approval,
            FinalUseControlError::InvalidSignature,
        ),
        (classic_wire_approval, FinalUseControlError::InvalidApproval),
    ] {
        assert_eq!(
            fixture
                .host
                .consume_kv_v2(&client, &fixture.grant, &approval, &fixture.request)
                .await,
            Err(BaoFinalUseHostError::Control(error))
        );
        assert_eq!(fixture.authority.frontier().unwrap(), admitted);
        assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
        assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    }
    let mut bad_grant = fixture.grant.clone();
    bad_grant.signature[0] ^= 1;
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &bad_grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::InvalidSignature
        )))
    );
    assert_eq!(fixture.authority.frontier().unwrap(), admitted);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 0);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);

    let receipt = fixture
        .host
        .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
        .await
        .unwrap();
    assert_eq!(
        receipt,
        BaoSecretReceipt {
            request_sha256: fixture.grant.grant.binding.request_sha256,
            response_sha256: Digest32::of_bytes(body.as_bytes()).into_array(),
            secret_sha256: fixture.request.expected_secret_sha256,
            version: 1,
            secret_bytes: SECRET.len(),
        }
    );
    task.await.unwrap().unwrap();
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    let consumed = fixture.authority.frontier().unwrap();
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
            FinalUseError::AlreadyClaimed
        )))
    );
    assert_eq!(fixture.authority.frontier().unwrap(), consumed);
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn pq_feed_expiry_during_provider_io_denies_registered_consumer_entry() {
    let clock = Arc::new(ManualClock::new(/*now_unix_ms*/ 10_000));
    let advance = clock.clone();
    let provider_calls = Arc::new(AtomicUsize::new(0));
    let calls = provider_calls.clone();
    let body =
        serde_json::json!({"data":{"data":{"value":SECRET},"metadata":{"version":1}}}).to_string();
    let (endpoint, ca, task) = delayed_server(body, move || {
        calls.fetch_add(1, Ordering::SeqCst);
        advance.set(/*now_unix_ms*/ 10_500);
    })
    .await
    .unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("fixture-token".into()).unwrap(),
        Duration::from_secs(2),
    )
    .unwrap();
    let callbacks = Arc::new(AtomicUsize::new(0));
    let fixture = PqFixture::new(
        &client,
        clock,
        callbacks.clone(),
        /*feed_expires_at*/ 10_500,
    );
    fixture.host.apply_revocation_update(&fixture.feed).unwrap();
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    task.await.unwrap().unwrap();
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    assert_eq!(
        fixture
            .host
            .consume_kv_v2(&client, &fixture.grant, &fixture.approval, &fixture.request)
            .await,
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(provider_calls.load(Ordering::SeqCst), 1);
    assert_eq!(callbacks.load(Ordering::SeqCst), 0);
}
