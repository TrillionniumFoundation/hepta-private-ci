//! Exercise actual serde wire sizes and protected configuration loading at the
//! maximum PQ key-roster/revocation capacity, retaining the classic wire cap.
use super::*;
use crate::authority_trust_unix::PqTrustOutcomeV2;
use crate::authority_trust_unix::tests::TestService;
use crate::authority_trust_unix::tests::frontier_service;
use crate::authority_trust_unix::tests::key;
use crate::authority_trust_unix::tests::signed;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use serde_json::json;
use std::fs;
use std::os::unix::fs::PermissionsExt;

fn full_head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: (0..FinalUseAuthenticationProfile::MlDsa65V2.max_revocations())
            .map(|index| format!("{index:03}{}", "r".repeat(125)))
            .collect(),
    }
}

fn endpoint_wire(config: &UnixPqTrustEndpointConfig) -> serde_json::Value {
    json!({
        "socket_path": config.socket_path,
        "peer_uid": config.peer_uid,
        "service_id": config.service_id,
        "key_generation": config.key_generation,
        "public_key_id": config.public_key_id,
        "public_key_spki": config.public_key_spki,
        "timeout_ms": config.timeout_ms,
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn max_rotation_config_loads_only_as_pq_and_oversize_response_stops_at_prefix() -> Result<()>
{
    let root = tempfile::tempdir()?;
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))?;
    let state = root.path().join("owner-state");
    fs::create_dir(&state)?;
    fs::set_permissions(&state, fs::Permissions::from_mode(0o700))?;
    let head = full_head();
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
    let issuer_keys: Vec<_> = (100..108).map(|seed| key(seed).1).collect();
    let feed_keys: Vec<_> = (110..118).map(|seed| key(seed).1).collect();
    let config = json!({
        "authentication_profile": "ml_dsa65_v2",
        "issuer_socket": issuer_socket,
        "issuer_uid": rustix::process::geteuid().as_raw(),
        "signer_id": "issuer",
        "issuer_keys": issuer_keys,
        "authority_state_dir": state,
        "head": head,
        "issuer_timeout_ms": 2000,
        "revocation_distributor_id": "feed",
        "revocation_keys": feed_keys,
        "external_clock": endpoint_wire(&clock.config),
        "external_frontier": endpoint_wire(&frontier.config),
    });
    let mut raw = serde_json::to_vec(&config)?;
    assert!(raw.len() > MAX_CONFIG_BYTES && raw.len() <= MAX_PQ_CONFIG_BYTES);
    let path = root.path().join("protected.json");
    raw.resize(MAX_PQ_CONFIG_BYTES, b' ');
    fs::write(&path, &raw)?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
    let authorizer = UnixFinalUseAuthorizer::open(&path)?;
    assert_eq!(
        authorizer.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );

    raw.push(b' ');
    fs::write(&path, &raw)?;
    assert!(
        UnixFinalUseAuthorizer::open(&path)
            .err()
            .unwrap()
            .to_string()
            .contains("256 KiB")
    );
    let classic_key = ed25519_dalek::SigningKey::from_bytes(&[78; 32]);
    let mut classic_config = json!({
        "issuer_socket": root.path().join("unused-classic.sock"),
        "issuer_uid": rustix::process::geteuid().as_raw(),
        "signer_id": "classic",
        "verifying_key": classic_key.verifying_key().to_bytes(),
        "authority_state_dir": root.path().join("classic-state"),
        "authority_epoch": 1,
        "revocation_revision": 1,
        "issuer_timeout_ms": 2000,
    });
    let mut classic = serde_json::to_vec(&classic_config)?;
    classic.resize(MAX_CONFIG_BYTES, b' ');
    fs::write(&path, &classic)?;
    let classic_owner = UnixFinalUseAuthorizer::open(&path)?;
    assert_eq!(
        classic_owner.authentication_profile(),
        FinalUseAuthenticationProfile::ClassicalV1
    );
    drop(classic_owner);
    classic_config["authority_state_dir"] = json!(root.path().join("unused-classic-state"));
    classic = serde_json::to_vec(&classic_config)?;
    classic.resize(MAX_CONFIG_BYTES + 1, b' ');
    fs::write(&path, &classic)?;
    assert!(
        UnixFinalUseAuthorizer::open(&path)
            .err()
            .unwrap()
            .to_string()
            .contains("64 KiB")
    );
    assert!(!root.path().join("unused-classic-state").exists());
    let mut unknown = br#"{"authentication_profile":"future"}"#.to_vec();
    unknown.resize(MAX_PQ_CONFIG_BYTES, b' ');
    fs::write(&path, &unknown)?;
    assert!(
        UnixFinalUseAuthorizer::open(&path)
            .err()
            .unwrap()
            .to_string()
            .contains("unsupported final-use authentication profile")
    );

    // Send no response body: oversized length must be rejected immediately,
    // before allocation/read, rather than waiting for the issuer deadline.
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut length = [0; 4];
        socket.read_exact(&mut length).await?;
        let mut request = vec![0; u32::from_be_bytes(length) as usize];
        socket.read_exact(&mut request).await?;
        socket
            .write_all(&((MAX_RESPONSE_BYTES + 1) as u32).to_be_bytes())
            .await?;
        Ok::<(), Box<dyn StdError + Send + Sync>>(())
    });
    let error = authorizer.request_port_bytes(b"{}").await.unwrap_err();
    assert!(error.to_string().contains("response exceeds its bound"));
    server.await??;
    Ok(())
}

#[test]
fn maximum_revocation_and_grant_response_fits_the_existing_transport_bound() -> Result<()> {
    let mut head = full_head();
    head.authority_epoch = u64::MAX;
    head.revision = u64::MAX;
    let grant = FinalUseGrant {
        schema_version: 2,
        signer_id: "i".repeat(128),
        authority_epoch: u64::MAX,
        grant_id: "g".repeat(128),
        nonce: [u8::MAX; 32],
        binding: FinalUseBinding {
            subject_id: "s".repeat(128),
            destination_id: "d".repeat(128),
            request_sha256: [u8::MAX; 32],
            scope_sha256: [u8::MAX; 32],
            payload_sha256: [u8::MAX; 32],
        },
        not_before_unix_ms: u64::MAX - 1000,
        expires_at_unix_ms: u64::MAX,
    };
    let update = FinalUseRevocationUpdate::new_pq("f".repeat(128), head, u64::MAX - 1000, u64::MAX);
    let (issuer, _) = key(/*seed*/ 101);
    let (feed, _) = key(/*seed*/ 111);
    let mut response = PqIssuerResponseV2 {
        schema_version: 2,
        challenge: [u8::MAX; 32],
        revocations: SignedFinalUseRevocationUpdate {
            signature: feed.sign_exact_message(&update.signing_bytes()?)?.to_vec(),
            update,
        },
        grant: Some(SignedFinalUseGrant {
            signature: issuer.sign_exact_message(&grant.signing_bytes()?)?.to_vec(),
            grant,
        }),
        denial_reason: None,
    };
    let actual = serde_json::to_vec(&response)?;
    let decoded: PqIssuerResponseV2 = serde_json::from_slice(&actual)?;
    assert_eq!(serde_json::to_vec(&decoded)?, actual);
    // Size-only upper bound, deliberately not accepted as authority: every
    // signature byte now requires the maximum three JSON decimal digits.
    response.grant.as_mut().unwrap().signature.fill(u8::MAX);
    response.revocations.signature.fill(u8::MAX);
    let upper_bound = serde_json::to_vec(&response)?.len();
    assert!(actual.len() <= upper_bound);
    assert!(
        upper_bound <= MAX_RESPONSE_BYTES,
        "maximum PQ response = {upper_bound} bytes"
    );
    Ok(())
}
