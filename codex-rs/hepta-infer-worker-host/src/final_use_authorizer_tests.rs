use super::*;

use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
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

fn config(
    root: &Path,
    socket: PathBuf,
    verifying_key: [u8; 32],
) -> FinalUseAuthorizerConfig {
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
            let now = u64::try_from(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)?
                    .as_millis(),
            )?;
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
        serve_once(&listener, Some(&server_signer), revocations(1, &[]), 7, None).await
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
    let authorizer =
        UnixFinalUseAuthorizer::from_config(config(directory.path(), socket, signer.verifying_key().to_bytes()))?;
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
