use super::*;

use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::net::UnixListener;

fn random_signing_key() -> SigningKey {
    SigningKey::from_bytes(&rand::random())
}

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
        issuer_process_identity: None,
        issuer_process_attestation: None,
    }
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
    let signer = random_signing_key();
    let authorizer = UnixFinalUseAuthorizer::from_test_config(config(
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
    let trusted = random_signing_key();
    let forged = random_signing_key();
    let authorizer = UnixFinalUseAuthorizer::from_test_config(config(
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
    let signer = random_signing_key();
    let authorizer = UnixFinalUseAuthorizer::from_test_config(config(
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

#[cfg(target_os = "linux")]
fn current_process_identity() -> Result<IssuerProcessIdentityConfig> {
    let snapshot = capture_issuer_process_identity(std::process::id())?;
    Ok(IssuerProcessIdentityConfig {
        executable_sha256: snapshot.executable_sha256,
        cgroup_sha256: snapshot.cgroup_sha256,
        boot_id_sha256: snapshot.boot_id_sha256,
    })
}

#[cfg(target_os = "linux")]
#[test]
fn linux_issuer_process_identity_rejects_same_uid_substitution() -> Result<()> {
    let expected = current_process_identity()?;
    let guard = validate_connected_issuer_process(Some(std::process::id()), Some(&expected))?
        .ok_or("expected a process identity guard")?;
    guard.revalidate()?;

    let mut wrong_executable = expected.clone();
    wrong_executable.executable_sha256 = "1".repeat(64);
    assert!(
        validate_connected_issuer_process(Some(std::process::id()), Some(&wrong_executable),)
            .is_err()
    );

    let mut wrong_cgroup = expected.clone();
    wrong_cgroup.cgroup_sha256 = "2".repeat(64);
    assert!(
        validate_connected_issuer_process(Some(std::process::id()), Some(&wrong_cgroup)).is_err()
    );

    let mut wrong_boot = expected;
    wrong_boot.boot_id_sha256 = "3".repeat(64);
    assert!(
        validate_connected_issuer_process(Some(std::process::id()), Some(&wrong_boot)).is_err()
    );
    assert!(validate_connected_issuer_process(None, Some(&wrong_boot)).is_err());
    Ok(())
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn linux_connected_peer_is_bound_before_and_after_grant_exchange() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let (listener, socket) = listener(directory.path(), "process-bound.sock").await?;
    let signer = random_signing_key();
    let mut authorizer_config = config(directory.path(), socket, signer.verifying_key().to_bytes());
    authorizer_config.issuer_process_identity = Some(current_process_identity()?);
    // This compatibility fixture hashes the complete test executable before
    // and after exchange. Production uses the small root PID attestation.
    authorizer_config.issuer_timeout_ms = 10_000;
    let authorizer = UnixFinalUseAuthorizer::from_test_config(authorizer_config)?;
    let server_signer = signer.clone();
    let server = tokio::spawn(async move {
        serve_once(
            &listener,
            Some(&server_signer),
            revocations(1, &[]),
            11,
            None,
        )
        .await
    });

    let expected = binding(41);
    let token = authorizer.claim(expected.clone()).await?;
    if !token.enter(&expected)?.matches(&expected) {
        return Err("process-bound token lost its exact binding".into());
    }
    server.await??;
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn linux_production_open_requires_process_identity() -> Result<()> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let signer = random_signing_key();
    let config_path = directory.path().join("authority.json");
    let value = config(
        directory.path(),
        directory.path().join("unused.sock"),
        signer.verifying_key().to_bytes(),
    );
    std::fs::write(&config_path, serde_json::to_vec(&value)?)?;
    std::fs::set_permissions(&config_path, std::fs::Permissions::from_mode(0o600))?;
    assert!(UnixFinalUseAuthorizer::open(&config_path).is_err());
    Ok(())
}

/// Bounded test issuer over the production Unix protocol. Only this separate
/// test task holds the signing key; the worker receives the verifier-only port.
pub(crate) async fn independent_test_authorizer(
    root: &Path,
    expected_claims: u8,
) -> Result<(UnixFinalUseAuthorizer, tokio::task::JoinHandle<Result<()>>)> {
    let (listener, socket) = listener(root, "cognitive-authority.sock").await?;
    let signer = random_signing_key();
    let authorizer = UnixFinalUseAuthorizer::from_test_config(config(
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
fn workload_owned_process_attestation_cannot_replace_root_issuer_identity() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("identity.json");
    let snapshot = capture_issuer_process_identity(std::process::id())?;
    let record = codex_hepta_contracts::ModelIssuerProcessIdentity {
        schema_version: 1,
        pid: snapshot.pid,
        start_time_ticks: snapshot.start_time_ticks,
        executable_sha256: snapshot.executable_sha256,
        cgroup_sha256: snapshot.cgroup_sha256,
        boot_id_sha256: snapshot.boot_id_sha256,
    };
    std::fs::write(&path, serde_json::to_vec(&record)?)?;
    assert!(capture_attested_issuer(std::process::id(), &path).is_err());
    assert!(
        validate_connected_issuer_with_attestation(Some(std::process::id()), None, Some(&path))
            .is_err()
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn root_attestation_configuration_cannot_select_a_workload_issuer() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let mut candidate = config(
        directory.path(),
        directory.path().join("issuer.sock"),
        random_signing_key().verifying_key().to_bytes(),
    );
    candidate.issuer_process_attestation = Some(directory.path().join("identity.json"));
    candidate.issuer_uid = 1000;
    assert!(UnixFinalUseAuthorizer::from_config(candidate.clone()).is_err());
    candidate.issuer_uid = 0;
    candidate.issuer_process_attestation = Some(PathBuf::from("relative.json"));
    assert!(UnixFinalUseAuthorizer::from_config(candidate).is_err());
    Ok(())
}
