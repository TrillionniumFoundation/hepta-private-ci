//! Final-use authority adapter for native provider dispatch.
//!
//! The signed grant is independently issued. This module only verifies and
//! consumes it; it never signs or widens authority.

use std::collections::BTreeSet;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use sha2::Digest;
use sha2::Sha256;

use super::NativeAdmission;
use super::Result;

const MAX_AUTHORITY_CONFIG_BYTES: usize = 32 * 1024;

struct NativeAuthorityFile {
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: PathBuf,
    authority_epoch: u64,
    revocation_revision: u64,
    revoked_grant_ids: BTreeSet<String>,
    grant: SignedFinalUseGrant,
}

/// Host-owned verifier plus one independently signed, single-use grant.
pub struct NativeExecutionAuthority {
    authority: FinalUseAuthority,
    grant: SignedFinalUseGrant,
}

impl NativeExecutionAuthority {
    pub fn from_file(path: &Path) -> Result<Self> {
        if !path.is_absolute() {
            return Err("authority config path must be absolute".into());
        }
        let mut bytes = Vec::new();
        open_private_authority_file(path)?
            .take((MAX_AUTHORITY_CONFIG_BYTES + 1) as u64)
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_AUTHORITY_CONFIG_BYTES {
            return Err("authority config exceeds 32768 bytes".into());
        }
        let config = parse_authority_file(&bytes)?;
        if !config.authority_state_dir.is_absolute() {
            return Err("authority state directory must be absolute".into());
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
            authority,
            grant: config.grant,
        })
    }

    pub(super) fn claim(
        &self,
        binding: &FinalUseBinding,
    ) -> std::result::Result<VerifiedUseToken, FinalUseError> {
        self.authority.claim(&self.grant, binding)
    }

    pub(super) async fn dispatch<T, Fut>(
        &self,
        token: VerifiedUseToken,
        binding: &FinalUseBinding,
        consumer: impl FnOnce() -> Fut,
    ) -> std::result::Result<T, FinalUseError>
    where
        Fut: std::future::Future<Output = T>,
    {
        self.authority
            .with_verified_use_async(token, binding, consumer)
            .await
    }

    pub(super) fn authority_epoch(&self) -> u64 {
        self.grant.grant.authority_epoch
    }

    pub(super) fn grant_id(&self) -> &str {
        &self.grant.grant.grant_id
    }
}

fn open_private_authority_file(path: &Path) -> Result<std::fs::File> {
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() || !before.is_file() {
        return Err("authority config must be a regular, non-symlink file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;

        if before.permissions().mode() & 0o077 != 0 || before.nlink() != 1 {
            return Err("authority config must be owner-only and singly linked".into());
        }
        let file = std::fs::File::open(path)?;
        let after = file.metadata()?;
        if !after.is_file()
            || after.permissions().mode() & 0o077 != 0
            || after.nlink() != 1
            || (before.dev(), before.ino()) != (after.dev(), after.ino())
        {
            return Err("authority config changed or is unsafe while opening".into());
        }
        return Ok(file);
    }
    #[cfg(not(unix))]
    {
        std::fs::File::open(path).map_err(Into::into)
    }
}

fn parse_authority_file(bytes: &[u8]) -> Result<NativeAuthorityFile> {
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    let object = value
        .as_object()
        .ok_or("authority config must be a JSON object")?;
    const ALLOWED: &[&str] = &[
        "signer_id",
        "verifying_key",
        "authority_state_dir",
        "authority_epoch",
        "revocation_revision",
        "revoked_grant_ids",
        "grant",
    ];
    if object.keys().any(|key| !ALLOWED.contains(&key.as_str())) {
        return Err("authority config contains an unknown field".into());
    }
    let signer_id = required_string(object, "signer_id")?;
    let authority_state_dir = PathBuf::from(required_string(object, "authority_state_dir")?);
    let authority_epoch = required_u64(object, "authority_epoch")?;
    let revocation_revision = required_u64(object, "revocation_revision")?;

    let key = object
        .get("verifying_key")
        .and_then(serde_json::Value::as_array)
        .ok_or("authority verifying_key must be an array")?;
    if key.len() != 32 {
        return Err("authority verifying_key must contain 32 bytes".into());
    }
    let mut verifying_key = [0_u8; 32];
    for (index, value) in key.iter().enumerate() {
        let byte = value
            .as_u64()
            .and_then(|value| u8::try_from(value).ok())
            .ok_or("authority verifying_key contains a non-byte value")?;
        verifying_key[index] = byte;
    }

    let mut revoked_grant_ids = BTreeSet::new();
    if let Some(values) = object.get("revoked_grant_ids") {
        let values = values
            .as_array()
            .ok_or("authority revoked_grant_ids must be an array")?;
        for value in values {
            let id = value
                .as_str()
                .ok_or("authority revoked_grant_ids must contain strings")?;
            if !revoked_grant_ids.insert(id.to_string()) {
                return Err("authority revoked_grant_ids contains a duplicate".into());
            }
        }
    }
    let grant = object
        .get("grant")
        .cloned()
        .ok_or("authority config is missing grant")
        .and_then(|value| {
            serde_json::from_value::<SignedFinalUseGrant>(value).map_err(|error| error.into())
        })?;

    Ok(NativeAuthorityFile {
        signer_id,
        verifying_key,
        authority_state_dir,
        authority_epoch,
        revocation_revision,
        revoked_grant_ids,
        grant,
    })
}

fn required_string(
    object: &serde_json::Map<String, serde_json::Value>,
    field: &'static str,
) -> Result<String> {
    object
        .get(field)
        .and_then(serde_json::Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| format!("authority config is missing valid {field}").into())
}

fn required_u64(
    object: &serde_json::Map<String, serde_json::Value>,
    field: &'static str,
) -> Result<u64> {
    object
        .get(field)
        .and_then(serde_json::Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("authority config is missing valid {field}").into())
}

pub(super) fn build_binding(
    admission: &NativeAdmission,
    agent_id: &AgentId,
    generation: u64,
    model: &str,
    model_provider: &str,
    agentd_socket: &Path,
    timeout: Duration,
    prompt: &str,
    context_query: Option<&str>,
    context_digest: &str,
) -> Result<FinalUseBinding> {
    if !valid_identity(&admission.operation_id)
        || !valid_identity(model_provider)
        || admission.maximum_in_flight == 0
        || admission.maximum_in_flight > 256
        || admission.quota_reservation_digest.is_zero()
        || admission.resource_snapshot_digest.is_zero()
        || admission.worker_assignment_digest.is_zero()
        || !valid_digest(context_digest)
    {
        return Err("invalid native final-use binding input".into());
    }
    let request_sha256 = digest_array(&serde_json::to_vec(&(
        "hepta.inference.final-use.request.v1",
        &admission.operation_id,
        &admission.request_id,
        agent_id.to_string(),
        generation,
    ))?);
    let scope_sha256 = digest_array(&serde_json::to_vec(&(
        "hepta.inference.final-use.scope.v1",
        agent_id.to_string(),
        generation,
        model,
        model_provider,
        agentd_socket,
        timeout.as_millis(),
        admission.maximum_in_flight,
        admission.quota_reservation_digest.to_string(),
        admission.resource_snapshot_digest.to_string(),
        admission.worker_assignment_digest.to_string(),
    ))?);
    let payload_sha256 = digest_array(&serde_json::to_vec(&(
        "hepta.inference.final-use.payload.v1",
        &admission.request_id,
        model,
        prompt,
        context_query,
        context_digest,
    ))?);
    Ok(FinalUseBinding {
        subject_id: agent_id.to_string(),
        destination_id: model_provider.to_string(),
        request_sha256,
        scope_sha256,
        payload_sha256,
    })
}

pub(super) fn binding_digest(binding: &FinalUseBinding) -> Result<String> {
    Ok(Digest32::of_bytes(&serde_json::to_vec(binding)?).to_string())
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn digest_array(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}

#[cfg(test)]
#[path = "native_authority_tests.rs"]
mod tests;
