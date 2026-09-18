//! Trusted-host bridge from an exact runtime.codex turn/start binding to the
//! kernel.authority final-use verifier.
//!
//! The worker never owns a signing key. It asks an independently operated Unix
//! authority endpoint for a signed grant, synchronizes the trusted revocation
//! head supplied by that endpoint, and then verifies/claims the grant locally.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

use crate::native_app_server::TurnStartAuthorityFuture;
use crate::native_app_server::TurnStartAuthorizer;

const AUTHORITY_PORT_SCHEMA_VERSION: u32 = 1;
const AUTHORITY_PORT_OPERATION: &str = "runtime.codex.turn_start";
const MAX_CONFIG_BYTES: usize = 64 * 1024;
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_DENIAL_REASON_BYTES: usize = 1024;
const MAX_ISSUER_TIMEOUT: Duration = Duration::from_secs(30);

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

/// Protected host configuration for the independent final-use authority port.
///
/// `verifying_key` is public. The private signing key is intentionally absent.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FinalUseAuthorizerConfig {
    pub issuer_socket: PathBuf,
    pub issuer_uid: u32,
    pub signer_id: String,
    pub verifying_key: [u8; 32],
    pub authority_state_dir: PathBuf,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    #[serde(default)]
    pub revoked_grant_ids: BTreeSet<String>,
    pub issuer_timeout_ms: u64,
}

/// Production runtime.codex authorizer. The independent endpoint decides
/// whether to issue a grant; this process only verifies and consumes it.
pub struct UnixFinalUseAuthorizer {
    issuer_socket: PathBuf,
    issuer_uid: u32,
    issuer_timeout: Duration,
    authority: FinalUseAuthority,
}

impl UnixFinalUseAuthorizer {
    pub fn open(config_path: &Path) -> Result<Self> {
        let config: FinalUseAuthorizerConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config(config)
    }

    pub fn from_config(config: FinalUseAuthorizerConfig) -> Result<Self> {
        if !config.issuer_socket.is_absolute() || !config.authority_state_dir.is_absolute() {
            return Err("final-use authority socket and state directory must be absolute".into());
        }
        let issuer_timeout = Duration::from_millis(config.issuer_timeout_ms);
        if issuer_timeout.is_zero() || issuer_timeout > MAX_ISSUER_TIMEOUT {
            return Err("final-use issuer timeout must be 1..=30000 ms".into());
        }
        let authority = FinalUseAuthority::open_state_dir(
            &config.authority_state_dir,
            config.signer_id,
            config.verifying_key,
            FinalUseRevocations {
                authority_epoch: config.authority_epoch,
                revision: config.revocation_revision,
                revoked_grant_ids: config.revoked_grant_ids,
            },
        )?;
        Ok(Self {
            issuer_socket: config.issuer_socket,
            issuer_uid: config.issuer_uid,
            issuer_timeout,
            authority,
        })
    }

    async fn claim_exact(&self, binding: FinalUseBinding) -> Result<VerifiedUseToken> {
        let response = self.request_grant(&binding).await?;
        if response.schema_version != AUTHORITY_PORT_SCHEMA_VERSION {
            return Err("unsupported final-use authority response schema".into());
        }
        sync_revocations(&self.authority, response.revocations)?;
        match (response.grant, response.denial_reason) {
            (Some(grant), None) => Ok(self.authority.claim(&grant, &binding)?),
            (None, Some(reason)) => {
                if reason.is_empty() || reason.len() > MAX_DENIAL_REASON_BYTES {
                    return Err("invalid final-use authority denial reason".into());
                }
                Err(format!("final-use authority denied turn/start: {reason}").into())
            }
            _ => Err("final-use authority response must contain exactly one outcome".into()),
        }
    }

    #[cfg(unix)]
    async fn request_grant(&self, binding: &FinalUseBinding) -> Result<IssuerResponse> {
        validate_issuer_socket(&self.issuer_socket, self.issuer_uid)?;
        let request = IssuerRequest {
            schema_version: AUTHORITY_PORT_SCHEMA_VERSION,
            operation: AUTHORITY_PORT_OPERATION.to_string(),
            binding: binding.clone(),
        };
        let request_bytes = serde_json::to_vec(&request)?;
        if request_bytes.is_empty() || request_bytes.len() > MAX_REQUEST_BYTES {
            return Err("final-use authority request exceeds its bound".into());
        }
        let request_len = u32::try_from(request_bytes.len())?;
        let exchange = async {
            let mut stream = tokio::net::UnixStream::connect(&self.issuer_socket).await?;
            stream.write_all(&request_len.to_be_bytes()).await?;
            stream.write_all(&request_bytes).await?;
            stream.flush().await?;

            let mut length = [0_u8; 4];
            stream.read_exact(&mut length).await?;
            let response_len = usize::try_from(u32::from_be_bytes(length))?;
            if response_len == 0 || response_len > MAX_RESPONSE_BYTES {
                return Err::<Vec<u8>, Box<dyn StdError + Send + Sync>>(
                    "final-use authority response exceeds its bound".into(),
                );
            }
            let mut response = vec![0_u8; response_len];
            stream.read_exact(&mut response).await?;
            Ok(response)
        };
        let response = timeout(self.issuer_timeout, exchange)
            .await
            .map_err(|_| "final-use authority request timed out")??;
        Ok(serde_json::from_slice(&response)?)
    }

    #[cfg(not(unix))]
    async fn request_grant(&self, _binding: &FinalUseBinding) -> Result<IssuerResponse> {
        Err("runtime.codex final-use Unix authority port is unsupported on this platform".into())
    }
}

impl TurnStartAuthorizer for UnixFinalUseAuthorizer {
    fn claim<'a>(&'a self, binding: FinalUseBinding) -> TurnStartAuthorityFuture<'a> {
        Box::pin(async move { self.claim_exact(binding).await })
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerRequest {
    schema_version: u32,
    operation: String,
    binding: FinalUseBinding,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IssuerResponse {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<String>,
}

fn sync_revocations(authority: &FinalUseAuthority, candidate: FinalUseRevocations) -> Result<()> {
    let current = authority.revocation_head()?;
    if current.authority_epoch == candidate.authority_epoch
        && current.revision == candidate.revision
        && current.revoked_grant_ids == candidate.revoked_grant_ids
    {
        return Ok(());
    }
    authority.update_revocations(candidate)?;
    Ok(())
}

#[cfg(unix)]
fn read_private_config(path: &Path) -> Result<Vec<u8>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute() {
        return Err("final-use authority config path must be absolute".into());
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    let metadata = file.metadata()?;
    let effective_uid = rustix::process::geteuid().as_raw();
    if !metadata.is_file()
        || metadata.mode() & 0o022 != 0
        || metadata.nlink() != 1
        || (metadata.uid() != 0 && metadata.uid() != effective_uid)
    {
        return Err(
            "final-use authority config must be a protected root/owner regular file".into(),
        );
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(u64::try_from(MAX_CONFIG_BYTES + 1)?)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_CONFIG_BYTES {
        return Err("final-use authority config exceeds 64 KiB".into());
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_config(_path: &Path) -> Result<Vec<u8>> {
    Err("runtime.codex final-use authority configuration requires Unix".into())
}

#[cfg(unix)]
fn validate_issuer_socket(path: &Path, issuer_uid: u32) -> Result<()> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err("final-use authority socket path must be absolute".into());
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_socket()
        || metadata.uid() != issuer_uid
        || metadata.mode() & 0o007 != 0
    {
        return Err("final-use authority socket identity or permissions are unsafe".into());
    }
    let parent = path
        .parent()
        .ok_or("final-use authority socket has no parent directory")?;
    let parent_metadata = std::fs::symlink_metadata(parent)?;
    if !parent_metadata.is_dir() || parent_metadata.mode() & 0o022 != 0 {
        return Err(
            "final-use authority socket parent directory is writable by an unsafe principal".into(),
        );
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "final_use_authorizer_tests.rs"]
mod tests;
