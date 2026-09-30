//! Unix vault adapter for protected model output.
//!
//! The worker sends plaintext over one UID-bound local socket to an isolated
//! encrypting service. The service never returns key material. The worker
//! validates an exact response binding and persists only ciphertext metadata.

use std::error::Error as StdError;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_infer_core::control_contracts::OutputStorageMode;
use codex_hepta_infer_core::control_contracts::ProtectedOutput;
use codex_hepta_infer_core::control_contracts::VerifiedExecutionPlan;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::time::timeout;

use crate::output_protection::NativeOutputProtectionFuture;
use crate::output_protection::NativeOutputProtector;

const VAULT_SCHEMA_VERSION: u32 = 1;
const VAULT_OPERATION: &str = "inference.control.encrypt_output";
const MAX_CONFIG_BYTES: usize = 64 * 1024;
const MAX_HEADER_BYTES: usize = 64 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const MAX_PLAINTEXT_BYTES: usize = 1024 * 1024;
const MAX_DENIAL_REASON_BYTES: usize = 1024;
const MAX_VAULT_TIMEOUT: Duration = Duration::from_secs(30);

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

/// Protected host configuration. No encryption key is accepted here.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnixOutputProtectorConfig {
    pub vault_socket: PathBuf,
    pub vault_uid: u32,
    pub vault_timeout_ms: u64,
}

/// Production output protector backed by an independently operated local vault.
pub struct UnixOutputProtector {
    vault_socket: PathBuf,
    vault_uid: u32,
    vault_timeout: Duration,
}

impl UnixOutputProtector {
    pub fn open(config_path: &Path) -> Result<Self> {
        let config: UnixOutputProtectorConfig =
            serde_json::from_slice(&read_private_config(config_path)?)?;
        Self::from_config(config)
    }

    pub fn from_config(config: UnixOutputProtectorConfig) -> Result<Self> {
        if !config.vault_socket.is_absolute() {
            return Err("output vault socket must be absolute".into());
        }
        let vault_timeout = Duration::from_millis(config.vault_timeout_ms);
        if vault_timeout.is_zero() || vault_timeout > MAX_VAULT_TIMEOUT {
            return Err("output vault timeout must be 1..=30000 ms".into());
        }
        Ok(Self {
            vault_socket: config.vault_socket,
            vault_uid: config.vault_uid,
            vault_timeout,
        })
    }

    async fn protect_exact(
        &self,
        plan: &VerifiedExecutionPlan,
        plaintext: &[u8],
        now_unix_ms: u64,
    ) -> std::result::Result<ProtectedOutput, String> {
        if plaintext.is_empty() || plaintext.len() > MAX_PLAINTEXT_BYTES {
            return Err("output plaintext must contain 1..=1048576 bytes".to_string());
        }
        let policy = plan.output_policy();
        if policy.storage_mode != OutputStorageMode::ExternalEncrypted {
            return Err("output policy did not select external encryption".to_string());
        }
        let encryption_key_id = policy
            .encryption_key_id
            .as_deref()
            .ok_or_else(|| "output policy omitted encryption key identity".to_string())?;
        let store_namespace = policy
            .encrypted_store_namespace
            .as_deref()
            .ok_or_else(|| "output policy omitted encrypted store namespace".to_string())?;
        let output_digest = output_digest(plaintext);
        let header = VaultRequestHeader {
            schema_version: VAULT_SCHEMA_VERSION,
            operation: VAULT_OPERATION.to_string(),
            request_id: plan.request_id().to_string(),
            principal_id: plan.principal_id().to_string(),
            execution_binding_digest: plan.execution_binding_digest().to_string(),
            policy_id: policy.policy_id.clone(),
            authority_epoch: policy.authority_epoch,
            classification: format!("{:?}", policy.classification).to_ascii_lowercase(),
            encryption_key_id: encryption_key_id.to_string(),
            store_namespace: store_namespace.to_string(),
            output_digest: output_digest.clone(),
            plaintext_bytes: u64::try_from(plaintext.len())
                .map_err(|_| "output plaintext length overflow".to_string())?,
            delete_after_unix_ms: policy.delete_after_unix_ms,
        };
        let header_bytes = serde_json::to_vec(&header).map_err(|error| error.to_string())?;
        if header_bytes.is_empty() || header_bytes.len() > MAX_HEADER_BYTES {
            return Err("output vault request header exceeds its bound".to_string());
        }
        let response = self
            .request_protection(&header_bytes, plaintext)
            .await
            .map_err(|error| error.to_string())?;
        if response.schema_version != VAULT_SCHEMA_VERSION
            || response.request_id != plan.request_id()
            || response.execution_binding_digest != plan.execution_binding_digest()
            || response.policy_id != policy.policy_id
            || response.encryption_key_id != encryption_key_id
            || response.store_namespace != store_namespace
            || response.output_digest != output_digest
            || response.delete_after_unix_ms != policy.delete_after_unix_ms
        {
            return Err("output vault response binding mismatch".to_string());
        }
        match (response.protected, response.denial_reason) {
            (Some(protected), None) => ProtectedOutput::external_encrypted(
                now_unix_ms,
                policy,
                plaintext,
                protected.encrypted_reference,
                protected.ciphertext_digest,
            )
            .map_err(|error| error.to_string()),
            (None, Some(reason)) => {
                if reason.is_empty() || reason.len() > MAX_DENIAL_REASON_BYTES {
                    Err("invalid output vault denial reason".to_string())
                } else {
                    Err(format!("output vault denied encryption: {reason}"))
                }
            }
            _ => Err("output vault response must contain exactly one outcome".to_string()),
        }
    }

    #[cfg(unix)]
    async fn request_protection(&self, header: &[u8], plaintext: &[u8]) -> Result<VaultResponse> {
        validate_vault_socket(&self.vault_socket, self.vault_uid)?;
        let header_len = u32::try_from(header.len())?;
        let plaintext_len = u64::try_from(plaintext.len())?;
        let exchange = async {
            let mut stream = tokio::net::UnixStream::connect(&self.vault_socket).await?;
            let peer = stream.peer_cred()?;
            validate_vault_peer_uid(peer.uid(), self.vault_uid)?;
            stream.write_all(&header_len.to_be_bytes()).await?;
            stream.write_all(header).await?;
            stream.write_all(&plaintext_len.to_be_bytes()).await?;
            stream.write_all(plaintext).await?;
            stream.flush().await?;

            let mut length = [0_u8; 4];
            stream.read_exact(&mut length).await?;
            let response_len = usize::try_from(u32::from_be_bytes(length))?;
            if response_len == 0 || response_len > MAX_RESPONSE_BYTES {
                return Err::<Vec<u8>, Box<dyn StdError + Send + Sync>>(
                    "output vault response exceeds its bound".into(),
                );
            }
            let mut response = vec![0_u8; response_len];
            stream.read_exact(&mut response).await?;
            Ok(response)
        };
        let response = timeout(self.vault_timeout, exchange)
            .await
            .map_err(|_| "output vault request timed out")??;
        Ok(serde_json::from_slice(&response)?)
    }

    #[cfg(not(unix))]
    async fn request_protection(&self, _header: &[u8], _plaintext: &[u8]) -> Result<VaultResponse> {
        Err("inference output Unix vault is unsupported on this platform".into())
    }
}

impl NativeOutputProtector for UnixOutputProtector {
    fn protect<'a>(
        &'a self,
        plan: &'a VerifiedExecutionPlan,
        plaintext: &'a [u8],
        now_unix_ms: u64,
    ) -> NativeOutputProtectionFuture<'a> {
        Box::pin(async move { self.protect_exact(plan, plaintext, now_unix_ms).await })
    }
}

#[derive(Clone, Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct VaultRequestHeader {
    schema_version: u32,
    operation: String,
    request_id: String,
    principal_id: String,
    execution_binding_digest: String,
    policy_id: String,
    authority_epoch: u64,
    classification: String,
    encryption_key_id: String,
    store_namespace: String,
    output_digest: String,
    plaintext_bytes: u64,
    delete_after_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct VaultResponse {
    schema_version: u32,
    request_id: String,
    execution_binding_digest: String,
    policy_id: String,
    encryption_key_id: String,
    store_namespace: String,
    output_digest: String,
    delete_after_unix_ms: u64,
    protected: Option<VaultProtectedOutput>,
    denial_reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct VaultProtectedOutput {
    encrypted_reference: String,
    ciphertext_digest: String,
}

fn output_digest(plaintext: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(b"hepta.inference-control.output.v1\0");
    hash.update((plaintext.len() as u64).to_be_bytes());
    hash.update(plaintext);
    format!("{:x}", hash.finalize())
}

#[cfg(unix)]
fn read_private_config(path: &Path) -> Result<Vec<u8>> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    if !path.is_absolute() {
        return Err("output vault config path must be absolute".into());
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
        return Err("output vault config must be a protected root/owner regular file".into());
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(u64::try_from(MAX_CONFIG_BYTES + 1)?)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_CONFIG_BYTES {
        return Err("output vault config exceeds 64 KiB".into());
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_config(_path: &Path) -> Result<Vec<u8>> {
    Err("inference output vault configuration requires Unix".into())
}

#[cfg(unix)]
fn validate_vault_peer_uid(actual_uid: u32, expected_uid: u32) -> Result<()> {
    if actual_uid != expected_uid {
        return Err("connected output vault peer UID does not match configuration".into());
    }
    Ok(())
}

#[cfg(unix)]
fn validate_vault_socket(path: &Path, vault_uid: u32) -> Result<()> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err("output vault socket path must be absolute".into());
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_socket()
        || metadata.uid() != vault_uid
        || metadata.mode() & 0o007 != 0
    {
        return Err("output vault socket identity or permissions are unsafe".into());
    }
    let parent = path
        .parent()
        .ok_or("output vault socket has no parent directory")?;
    let parent_metadata = std::fs::symlink_metadata(parent)?;
    if !parent_metadata.is_dir() || parent_metadata.mode() & 0o022 != 0 {
        return Err("output vault socket parent is writable by an unsafe principal".into());
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "unix_output_protector_boundary_tests.rs"]
mod boundary_tests;
