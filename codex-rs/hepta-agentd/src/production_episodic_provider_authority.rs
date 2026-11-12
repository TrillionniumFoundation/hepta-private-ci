//! One fixture-only final-use claim over the existing Unix authority protocol.
//! This repeats the bounded issuer pattern in runtime_codex_product_e2e.rs.
//! The public test key is not a deployment credential or an independent owner.

use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_worker_host::final_use_authorizer::FinalUseAuthorizerConfig;
use codex_hepta_infer_worker_host::final_use_authorizer::UnixFinalUseAuthorizer;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

pub(super) async fn start(
    root: &Path,
    subject_id: String,
    source_reads: Arc<AtomicUsize>,
    reads_before_run: usize,
) -> Result<(
    UnixFinalUseAuthorizer,
    tokio::task::JoinHandle<Result<serde_json::Value>>,
)> {
    start_with_withdrawal(
        root,
        subject_id,
        source_reads,
        reads_before_run,
        /*withdrawal*/ None,
    )
    .await
}

pub(super) async fn start_with_withdrawal(
    root: &Path,
    subject_id: String,
    source_reads: Arc<AtomicUsize>,
    reads_before_run: usize,
    withdrawal: Option<super::diagnostic::Withdrawal>,
) -> Result<(
    UnixFinalUseAuthorizer,
    tokio::task::JoinHandle<Result<serde_json::Value>>,
)> {
    std::fs::create_dir(root)?;
    std::fs::set_permissions(root, std::fs::Permissions::from_mode(0o700))?;
    let socket = root.join("fixture.sock");
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660))?;
    let signer = SigningKey::from_bytes(&[73; 32]);
    let authorizer = UnixFinalUseAuthorizer::from_config(FinalUseAuthorizerConfig {
        issuer_uid: std::fs::metadata(&socket)?.uid(),
        issuer_socket: socket,
        signer_id: "fixture-only-memory-context".to_string(),
        verifying_key: signer.verifying_key().to_bytes(),
        authority_state_dir: root.join("authority-state"),
        authority_epoch: 9,
        revocation_revision: 1,
        revoked_grant_ids: BTreeSet::new(),
        issuer_timeout_ms: 2_000,
    })?;
    let task = tokio::spawn(async move {
        tokio::time::timeout(Duration::from_secs(30), async move {
            let (mut stream, _) = listener.accept().await?;
            let mut length = [0_u8; 4];
            stream.read_exact(&mut length).await?;
            let size = usize::try_from(u32::from_be_bytes(length))?;
            if !(1..=16 * 1024).contains(&size) {
                return Err("bounded fixture grant request required".into());
            }
            let mut bytes = vec![0_u8; size];
            stream.read_exact(&mut bytes).await?;
            let request: Request = serde_json::from_slice(&bytes)?;
            let reads_at_claim = source_reads.load(Ordering::SeqCst);
            if request.schema_version != 1
                || request.operation != "runtime.codex.turn_start"
                || request.binding.subject_id != subject_id
                || !request.binding.destination_id.starts_with("codex-app-server:")
                || reads_at_claim != reads_before_run + 2
            {
                return Err("fixture claim did not follow the exact owner context read".into());
            }
            let withdrawal = match withdrawal {
                Some(withdrawal) => Some(withdrawal.commit().await?),
                None => None,
            };
            let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            let grant = FinalUseGrant {
                schema_version: 1,
                signer_id: "fixture-only-memory-context".to_string(),
                authority_epoch: 9,
                grant_id: "one-fixture-context-turn".to_string(),
                nonce: [91; 32],
                binding: request.binding.clone(),
                not_before_unix_ms: now.saturating_sub(1_000),
                expires_at_unix_ms: now.checked_add(60_000).ok_or("fixture expiry overflow")?,
            };
            let signature = signer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
            let response = serde_json::json!({
                "schema_version": 1,
                "revocations": FinalUseRevocations { authority_epoch: 9, revision: 1, revoked_grant_ids: BTreeSet::new() },
                "grant": SignedFinalUseGrant { grant, signature },
                "denial_reason": null,
            });
            let response = serde_json::to_vec(&response)?;
            stream.write_all(&u32::try_from(response.len())?.to_be_bytes()).await?;
            stream.write_all(&response).await?;
            stream.flush().await?;
            Ok(serde_json::json!({
                "fixture_only": true,
                "claim_count": 1,
                "source_checks_before_run": reads_before_run,
                "source_checks_at_claim": reads_at_claim,
                "source_checks_before_claim": reads_at_claim - reads_before_run,
                "binding": request.binding,
                "native_withdrawal": withdrawal,
            }))
        })
        .await
        .map_err(|_| "fixture issuer timed out before its only claim")?
    });
    Ok((authorizer, task))
}
