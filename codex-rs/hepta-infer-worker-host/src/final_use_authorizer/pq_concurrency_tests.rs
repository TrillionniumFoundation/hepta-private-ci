//! Two real issuer requests and the original signed Unix trust services.
//! The per-instance, test-only after-feed hook controls scheduling only: it
//! creates no receipt, grant, token or authority state and is absent in builds
//! without cfg(test).
use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use tokio::sync::Notify;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_real_pq_claim_cannot_inherit_an_older_heads_longer_feed() -> Result<()> {
    let root = tempfile::tempdir()?;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    let state = root.path().join("owner-state");
    fs::create_dir(&state)?;
    fs::set_permissions(&state, fs::Permissions::from_mode(0o700))?;
    let head_a = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head_a,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let protected_now = Arc::new(AtomicU64::new(10_000));
    let service_now = Arc::clone(&protected_now);
    let clock = TestService::start(
        root.path(),
        "clock.sock",
        /*seed*/ 80,
        move |request, key| {
            signed(
                request,
                PqTrustOutcomeV2::Clock {
                    unix_ms: service_now.load(Ordering::SeqCst),
                },
                key,
            )
        },
    );
    let frontier = frontier_service(root.path(), initial);
    let issuer_socket = root.path().join("issuer.sock");
    let listener = tokio::net::UnixListener::bind(&issuer_socket)?;
    fs::set_permissions(&issuer_socket, fs::Permissions::from_mode(0o600))?;
    let (issuer, issuer_key) = key(/*seed*/ 82);
    let (feed, feed_key) = key(/*seed*/ 83);
    let config = PqFinalUseAuthorizerConfig {
        authentication_profile: FinalUseAuthenticationProfile::MlDsa65V2,
        issuer_socket,
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "issuer".into(),
        issuer_keys: vec![issuer_key],
        authority_state_dir: state,
        head: head_a.clone(),
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![feed_key],
        external_clock: clock.config.clone(),
        external_frontier: frontier.config.clone(),
    };
    let mut authorizer = UnixFinalUseAuthorizer::from_pq_config(config)?;
    let binding_a = FinalUseBinding {
        subject_id: "worker-a".into(),
        destination_id: "runtime".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let binding_b = FinalUseBinding {
        subject_id: "worker-b".into(),
        destination_id: "runtime".into(),
        request_sha256: [4; 32],
        scope_sha256: [5; 32],
        payload_sha256: [6; 32],
    };
    let a_after_authenticated_feed = Arc::new(Notify::new());
    let reached = Arc::clone(&a_after_authenticated_feed);
    let (release_a, wait_for_release) = mpsc::sync_channel(1);
    let wait_for_release = Mutex::new(wait_for_release);
    let paused_binding = binding_a.clone();
    Arc::get_mut(authorizer.pq.as_mut().expect("explicit PQ runtime"))
        .expect("test hook is configured before the runtime is shared")
        .after_feed_hook = Some(Arc::new(move |binding| {
        if binding == &paused_binding {
            reached.notify_one();
            wait_for_release
                .lock()
                .expect("test scheduling receiver")
                .recv_timeout(Duration::from_secs(10))
                .expect("test must release A after B's real claim");
        }
    }));
    let authorizer = Arc::new(authorizer);
    let issuer_binding_a = binding_a.clone();
    let issuer_binding_b = binding_b.clone();
    let server = tokio::spawn(async move {
        let mut issued = Vec::new();
        for index in 0..2 {
            let (mut socket, _) = listener.accept().await?;
            let mut length = [0; 4];
            socket.read_exact(&mut length).await?;
            let length = u32::from_be_bytes(length) as usize;
            assert!(length > 0 && length <= MAX_REQUEST_BYTES);
            let mut bytes = vec![0; length];
            socket.read_exact(&mut bytes).await?;
            let request: PqIssuerRequestV2 = serde_json::from_slice(&bytes)?;
            assert_eq!(request.schema_version, 2);
            assert_eq!(request.operation, AUTHORITY_PORT_OPERATION);
            assert_ne!(request.challenge, [0; 32]);
            let expected = if index == 0 {
                &issuer_binding_a
            } else {
                &issuer_binding_b
            };
            assert_eq!(&request.binding, expected);
            let grant = FinalUseGrant {
                schema_version: 2,
                signer_id: "issuer".into(),
                authority_epoch: 1,
                grant_id: format!("concurrent-grant-{index}"),
                nonce: request.challenge,
                binding: request.binding,
                not_before_unix_ms: 9_000,
                expires_at_unix_ms: if index == 0 { 19_000 } else { 14_000 },
            };
            let grant = SignedFinalUseGrant {
                signature: issuer.sign_exact_message(&grant.signing_bytes()?)?.to_vec(),
                grant,
            };
            let update = FinalUseRevocationUpdate::new_pq(
                "feed".into(),
                FinalUseRevocations {
                    authority_epoch: 1,
                    revision: index + 1,
                    revoked_grant_ids: Default::default(),
                },
                /*issued_at_unix_ms*/ 9_500,
                if index == 0 { 20_000 } else { 15_000 },
            );
            let revocations = SignedFinalUseRevocationUpdate {
                signature: feed.sign_exact_message(&update.signing_bytes()?)?.to_vec(),
                update,
            };
            issued.push(grant.clone());
            let response = PqIssuerResponseV2 {
                schema_version: 2,
                challenge: request.challenge,
                revocations,
                grant: Some(grant),
                denial_reason: None,
            };
            let bytes = serde_json::to_vec(&response)?;
            assert!(bytes.len() <= MAX_RESPONSE_BYTES);
            socket
                .write_all(&(bytes.len() as u32).to_be_bytes())
                .await?;
            socket.write_all(&bytes).await?;
        }
        Ok::<_, Box<dyn StdError + Send + Sync>>(issued)
    });

    let a_owner = Arc::clone(&authorizer);
    let a_request = binding_a.clone();
    let a_claim =
        tokio::spawn(async move { TurnStartAuthorizer::claim(a_owner.as_ref(), a_request).await });
    timeout(
        Duration::from_secs(5),
        a_after_authenticated_feed.notified(),
    )
    .await?;
    // A has a genuine signed receipt for head 1, but has claimed no nonce yet.
    assert_eq!(authorizer.authority.revocation_head()?, head_a);
    assert_eq!(authorizer.authority.capacity()?.used_nonces, 0);
    assert_eq!(authorizer.authority.frontier()?, initial);

    // B goes through the same public authorizer and real Unix issuer. Its feed
    // advances the owner to head 2; neither the test nor the hook updates it.
    let b_token = timeout(
        Duration::from_secs(5),
        TurnStartAuthorizer::claim(authorizer.as_ref(), binding_b.clone()),
    )
    .await??;
    assert_eq!(b_token.claimed_authority_epoch(), 1);
    assert_eq!(b_token.claimed_revocation_revision(), 2);
    assert!(b_token.enter(&binding_b)?.matches(&binding_b));
    assert_eq!(authorizer.authority.capacity()?.used_nonces, 1);
    assert_eq!(authorizer.authority.revocation_head()?.revision, 2);
    let after_b = authorizer.authority.frontier()?;
    assert_eq!(after_b.revocation_revision, 2);

    // B's feed has now expired, while A's grant and old feed remain valid. If
    // A could return a token claimed under B, token.enter would see B == B and
    // could not identify the old lease. The post-claim receipt binding must fail.
    protected_now.store(16_000, Ordering::SeqCst);
    release_a.send(())?;
    let a_result = timeout(Duration::from_secs(5), a_claim).await??;
    let error = a_result.expect_err("A must not attach its head-1 lease to a head-2 token");
    assert_eq!(
        error.to_string(),
        "PQ claimed revocation head does not match authenticated feed"
    );
    let issued = timeout(Duration::from_secs(5), server).await???;
    assert_eq!(issued.len(), 2);
    assert_ne!(issued[0].grant.nonce, issued[1].grant.nonce);

    // Failed post-claim admission does not refund the exact issuer nonce. Both
    // real claims remain durable, and the independent service agrees with the
    // original owner rather than an alternate in-memory ledger.
    assert_eq!(authorizer.authority.capacity()?.used_nonces, 2);
    assert_eq!(authorizer.authority.revocation_head()?.revision, 2);
    assert_eq!(
        authorizer
            .authority
            .claim(&issued[0], &binding_a)
            .unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    let final_frontier = authorizer.authority.frontier()?;
    assert_eq!(final_frontier.revocation_revision, 2);
    assert_ne!(final_frontier, after_b);
    let persisted: FinalUseFrontier =
        serde_json::from_slice(&fs::read(root.path().join("external-frontier.json"))?)?;
    assert_eq!(persisted, final_frontier);
    assert!(clock.requests.load(Ordering::Relaxed) >= 8);
    assert!(frontier.requests.load(Ordering::Relaxed) >= 5);
    Ok(())
}
