use super::*;

use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tokio::net::UnixListener;

fn binding(label: u8) -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "00000000-0000-4000-8000-000000000001".to_string(),
        destination_id: "provider:codex-app-server".to_string(),
        request_sha256: [label; 32],
        scope_sha256: [label.saturating_add(1); 32],
        payload_sha256: [label.saturating_add(2); 32],
    }
}

fn revocations(revision: u64, revoked: &[&str]) -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 9,
        revision,
        revoked_grant_ids: revoked.iter().map(|value| (*value).to_string()).collect(),
    }
}

fn config(root: &Path, socket: PathBuf, verifying_key: [u8; 32]) -> FinalUseAuthorizerConfig {
    FinalUseAuthorizerConfig {
        issuer_socket: socket,
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "authority-owner".to_string(),
        verifying_key,
        authority_state_dir: root.join("authority-state"),
        authority_epoch: 9,
        revocation_revision: 1,
        revoked_grant_ids: BTreeSet::new(),
        issuer_timeout_ms: 2_000,
    }
}

fn write_classic_config(
    path: &Path,
    config: &FinalUseAuthorizerConfig,
    profile: Option<&str>,
) -> Result<Vec<u8>> {
    let mut value = serde_json::json!({
        "issuer_socket": config.issuer_socket,
        "issuer_uid": config.issuer_uid,
        "signer_id": config.signer_id,
        "verifying_key": config.verifying_key,
        "authority_state_dir": config.authority_state_dir,
        "authority_epoch": config.authority_epoch,
        "revocation_revision": config.revocation_revision,
        "revoked_grant_ids": config.revoked_grant_ids,
        "issuer_timeout_ms": config.issuer_timeout_ms,
    });
    if let Some(profile) = profile {
        value["authentication_profile"] = serde_json::json!(profile);
    }
    let bytes = serde_json::to_vec(&value)?;
    std::fs::write(path, &bytes)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    Ok(bytes)
}

#[test]
fn ordinary_open_rejects_missing_or_classic_profile_before_creating_state() -> Result<()> {
    let root = tempfile::tempdir()?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    let socket = root.path().join("must-not-contact-issuer.sock");
    let signer = SigningKey::from_bytes(&[75; 32]);
    let config = config(
        root.path(),
        socket.clone(),
        signer.verifying_key().to_bytes(),
    );
    let path = root.path().join("legacy-authority.json");

    for (profile, expected_error) in [
        (None, "requires explicit ml_dsa65_v2 authentication profile"),
        (
            Some("classical_v1"),
            "unsupported final-use authentication profile",
        ),
    ] {
        let bytes = write_classic_config(&path, &config, profile)?;
        let error = UnixFinalUseAuthorizer::open(&path)
            .err()
            .ok_or("ordinary open accepted a classical authority profile")?;
        assert!(error.to_string().contains(expected_error), "{error}");
        assert!(!config.authority_state_dir.exists());
        assert!(!socket.exists());
        assert_eq!(std::fs::read(&path)?, bytes);
    }
    Ok(())
}

#[test]
fn ordinary_open_does_not_reactivate_or_change_existing_classic_state() -> Result<()> {
    let root = tempfile::tempdir()?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    let socket = root.path().join("must-not-contact-historical-issuer.sock");
    let signer = SigningKey::from_bytes(&[76; 32]);
    let mut config = config(
        root.path(),
        socket.clone(),
        signer.verifying_key().to_bytes(),
    );
    config.revocation_revision = 2;
    config
        .revoked_grant_ids
        .insert("historically-revoked".to_owned());
    let owner = UnixFinalUseAuthorizer::from_config(config.clone())?;
    assert_eq!(
        owner.authentication_profile(),
        FinalUseAuthenticationProfile::ClassicalV1
    );
    drop(owner);
    let snapshot = std::fs::read(config.authority_state_dir.join("authority.json"))?;
    let claims = std::fs::read(config.authority_state_dir.join("authority.claims"))?;
    let path = root.path().join("historical-authority.json");

    for (profile, expected_error) in [
        (None, "requires explicit ml_dsa65_v2 authentication profile"),
        (
            Some("classical_v1"),
            "unsupported final-use authentication profile",
        ),
    ] {
        let bytes = write_classic_config(&path, &config, profile)?;
        let error = UnixFinalUseAuthorizer::open(&path)
            .err()
            .ok_or("historical classical state regained ordinary runtime authority")?;
        assert!(error.to_string().contains(expected_error), "{error}");
        assert_eq!(
            std::fs::read(config.authority_state_dir.join("authority.json"))?,
            snapshot
        );
        assert_eq!(
            std::fs::read(config.authority_state_dir.join("authority.claims"))?,
            claims
        );
        assert!(!socket.exists());
        assert_eq!(std::fs::read(&path)?, bytes);
    }
    // Explicit historical opening remains possible and preserves the original
    // revocation head after the ordinary route refused activation.
    let owner = UnixFinalUseAuthorizer::from_config(config)?;
    assert_eq!(
        owner.authority.revocation_head()?,
        revocations(2, &["historically-revoked"])
    );
    Ok(())
}

async fn listener(root: &Path, name: &str) -> Result<(UnixListener, PathBuf)> {
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    let socket = root.join(name);
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660))?;
    Ok((listener, socket))
}

async fn serve_once(
    listener: &UnixListener,
    signer: Option<&SigningKey>,
    head: FinalUseRevocations,
    nonce: u8,
    denial_reason: Option<&str>,
) -> Result<()> {
    let (mut stream, _) = listener.accept().await?;
    let mut length = [0_u8; 4];
    stream.read_exact(&mut length).await?;
    let request_len = usize::try_from(u32::from_be_bytes(length))?;
    if request_len == 0 || request_len > MAX_REQUEST_BYTES {
        return Err("invalid test authority request length".into());
    }
    let mut request_bytes = vec![0_u8; request_len];
    stream.read_exact(&mut request_bytes).await?;
    let request: IssuerRequest = serde_json::from_slice(&request_bytes)?;
    if request.schema_version != AUTHORITY_PORT_SCHEMA_VERSION
        || request.operation != AUTHORITY_PORT_OPERATION
    {
        return Err("unexpected authority request protocol".into());
    }

    let grant = match signer {
        Some(signer) => {
            let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "authority-owner".to_string(),
                authority_epoch: head.authority_epoch,
                grant_id: format!("grant-{nonce}"),
                nonce: [nonce; 32],
                binding: request.binding,
                not_before_unix_ms: now.saturating_sub(1_000),
                expires_at_unix_ms: now
                    .checked_add(60_000)
                    .ok_or("test grant expiry overflow")?,
            };
            let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
            Some(SignedFinalUseGrant { grant, signature })
        }
        None => None,
    };
    let response = IssuerResponse {
        schema_version: AUTHORITY_PORT_SCHEMA_VERSION,
        revocations: head,
        grant,
        denial_reason: denial_reason.map(str::to_string),
    };
    let response_bytes = serde_json::to_vec(&response)?;
    let response_len = u32::try_from(response_bytes.len())?;
    stream.write_all(&response_len.to_be_bytes()).await?;
    stream.write_all(&response_bytes).await?;
    stream.flush().await?;
    Ok(())
}

#[tokio::test]
async fn exact_signed_grant_becomes_one_entry_verified_token() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (listener, socket) = listener(directory.path(), "authority.sock").await?;
    let signer = SigningKey::from_bytes(&[41; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(config(
        directory.path(),
        socket,
        signer.verifying_key().to_bytes(),
    ))?;
    let expected = binding(11);
    let server_signer = signer.clone();
    let server = tokio::spawn(async move {
        serve_once(
            &listener,
            Some(&server_signer),
            revocations(1, &[]),
            7,
            None,
        )
        .await
    });

    let token = authorizer.claim(expected.clone()).await?;
    if token.witness_sha256() == [0; 32] {
        return Err("verified token witness was empty".into());
    }
    let entered = token.enter(&expected)?;
    if !entered.matches(&expected) {
        return Err("entered token lost its exact binding".into());
    }
    server.await??;
    Ok(())
}

#[tokio::test]
async fn forged_grant_never_reaches_effect_entry() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (listener, socket) = listener(directory.path(), "forged.sock").await?;
    let trusted = SigningKey::from_bytes(&[42; 32]);
    let forged = SigningKey::from_bytes(&[43; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(config(
        directory.path(),
        socket,
        trusted.verifying_key().to_bytes(),
    ))?;
    let server = tokio::spawn(async move {
        serve_once(&listener, Some(&forged), revocations(1, &[]), 8, None).await
    });

    if authorizer.claim(binding(21)).await.is_ok() {
        return Err("forged final-use grant was accepted".into());
    }
    server.await??;
    Ok(())
}

#[tokio::test]
async fn endpoint_denial_updates_head_and_old_head_cannot_roll_back() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (listener, socket) = listener(directory.path(), "revocation.sock").await?;
    let signer = SigningKey::from_bytes(&[44; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(config(
        directory.path(),
        socket,
        signer.verifying_key().to_bytes(),
    ))?;
    let server_signer = signer.clone();
    let server = tokio::spawn(async move {
        serve_once(
            &listener,
            None,
            revocations(2, &["revoked-before-entry"]),
            9,
            Some("policy denied"),
        )
        .await?;
        serve_once(
            &listener,
            Some(&server_signer),
            revocations(1, &[]),
            10,
            None,
        )
        .await
    });

    if authorizer.claim(binding(31)).await.is_ok() {
        return Err("authority denial was ignored".into());
    }
    if authorizer.claim(binding(32)).await.is_ok() {
        return Err("older revocation head rolled authority state back".into());
    }
    server.await??;
    Ok(())
}

#[test]
fn connected_issuer_peer_uid_must_match_configured_owner() {
    let owner = rustix::process::geteuid().as_raw();
    assert!(validate_issuer_peer_uid(owner, owner).is_ok());
    let other = owner
        .checked_add(1)
        .unwrap_or_else(|| owner.saturating_sub(1));
    assert!(validate_issuer_peer_uid(other, owner).is_err());
}

/// Bounded test issuer over the production Unix protocol. Only this separate
/// test task holds the signing key; the worker receives the verifier-only port.
pub(crate) async fn independent_test_authorizer(
    root: &Path,
    expected_claims: u8,
) -> Result<(UnixFinalUseAuthorizer, tokio::task::JoinHandle<Result<()>>)> {
    let (listener, socket) = listener(root, "cognitive-authority.sock").await?;
    let signer = SigningKey::from_bytes(&[79; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(config(
        root,
        socket,
        signer.verifying_key().to_bytes(),
    ))?;
    let issuer = tokio::spawn(async move {
        for nonce in 1..=expected_claims {
            timeout(
                Duration::from_secs(30),
                serve_once(&listener, Some(&signer), revocations(1, &[]), nonce, None),
            )
            .await
            .map_err(|_| "test issuer did not receive the expected claim")??;
        }
        Ok(())
    });
    Ok((authorizer, issuer))
}

#[cfg(target_os = "linux")]
#[test]
fn pq_selected_artifact_cannot_use_classic_final_use_before_issuer_dispatch() -> Result<()> {
    let root = tempfile::tempdir()?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    let socket = root.path().join("not-contacted.sock");
    let signer = SigningKey::from_bytes(&[78; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(config(
        root.path(),
        socket.clone(),
        signer.verifying_key().to_bytes(),
    ))?;
    assert!(
        crate::smollm_cognitive_host::validate_final_use_profile(
            &authorizer,
            FinalUseAuthenticationProfile::ClassicalV1,
        )
        .is_ok()
    );
    assert!(
        crate::smollm_cognitive_host::validate_final_use_profile(
            &authorizer,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )
        .is_err()
    );
    assert!(!socket.exists());
    Ok(())
}
