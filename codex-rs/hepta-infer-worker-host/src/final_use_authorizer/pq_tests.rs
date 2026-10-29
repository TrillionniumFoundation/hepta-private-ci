use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::Ordering;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_pq_host_reaches_owner_with_external_trust_and_rejects_classic_or_replayed_reply()
-> Result<()> {
    let root = tempfile::tempdir()?;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    let state = root.path().join("owner-state");
    fs::create_dir(&state)?;
    fs::set_permissions(&state, fs::Permissions::from_mode(0o700))?;
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let initial = FinalUseFrontier::for_initial_head_with_profile(
        &head,
        FinalUseAuthenticationProfile::MlDsa65V2,
    )?;
    let clock = TestService::start(
        root.path(),
        "clock.sock",
        /*seed*/ 80,
        |request, key| signed(request, PqTrustOutcomeV2::Clock { unix_ms: 1100 }, key),
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
        head: head.clone(),
        issuer_timeout_ms: 2000,
        revocation_distributor_id: "feed".into(),
        revocation_keys: vec![feed_key],
        external_clock: clock.config.clone(),
        external_frontier: frontier.config.clone(),
    };
    let authorizer = UnixFinalUseAuthorizer::from_pq_config(config)?;
    assert!(
        crate::smollm_cognitive_host::validate_final_use_profile(
            &authorizer,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )
        .is_ok()
    );
    assert!(
        crate::smollm_cognitive_host::validate_final_use_profile(
            &authorizer,
            FinalUseAuthenticationProfile::ClassicalV1,
        )
        .is_err()
    );
    let server = tokio::spawn(async move {
        let mut first_challenge = [0; 32];
        for index in 0..3 {
            let (mut socket, _) = listener.accept().await?;
            let mut length = [0; 4];
            socket.read_exact(&mut length).await?;
            let mut bytes = vec![0; u32::from_be_bytes(length) as usize];
            socket.read_exact(&mut bytes).await?;
            let request: PqIssuerRequestV2 = serde_json::from_slice(&bytes)?;
            if index == 0 {
                first_challenge = request.challenge;
            }
            let grant = FinalUseGrant {
                schema_version: if index == 1 { 1 } else { 2 },
                signer_id: "issuer".into(),
                authority_epoch: 1,
                grant_id: format!("grant-{index}"),
                nonce: request.challenge,
                binding: request.binding,
                not_before_unix_ms: 1000,
                expires_at_unix_ms: 1500,
            };
            let signature = issuer.sign_exact_message(&grant.signing_bytes()?)?.to_vec();
            let update = FinalUseRevocationUpdate::new_pq(
                "feed".into(),
                head.clone(),
                /*issued_at_unix_ms*/ 1000,
                /*expires_at_unix_ms*/ 2000,
            );
            let revocation_signature = feed.sign_exact_message(&update.signing_bytes()?)?.to_vec();
            let response = PqIssuerResponseV2 {
                schema_version: 2,
                challenge: if index == 2 {
                    first_challenge
                } else {
                    request.challenge
                },
                revocations: SignedFinalUseRevocationUpdate {
                    update,
                    signature: revocation_signature,
                },
                grant: Some(SignedFinalUseGrant { grant, signature }),
                denial_reason: None,
            };
            let bytes = serde_json::to_vec(&response)?;
            socket
                .write_all(&(bytes.len() as u32).to_be_bytes())
                .await?;
            socket.write_all(&bytes).await?;
        }
        Ok::<(), Box<dyn StdError + Send + Sync>>(())
    });
    let binding = FinalUseBinding {
        subject_id: "worker".into(),
        destination_id: "runtime".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let token = authorizer.claim_exact(binding.clone()).await?;
    assert!(token.enter(&binding)?.matches(&binding));
    assert!(authorizer.claim_exact(binding.clone()).await.is_err());
    assert!(authorizer.claim_exact(binding).await.is_err());
    server.await??;
    assert!(clock.requests.load(Ordering::Relaxed) >= 4);
    assert!(frontier.requests.load(Ordering::Relaxed) >= 3);
    let stored: FinalUseFrontier =
        serde_json::from_slice(&fs::read(root.path().join("external-frontier.json"))?)?;
    assert_ne!(stored, initial);
    drop(clock);
    drop(frontier);
    Ok(())
}
