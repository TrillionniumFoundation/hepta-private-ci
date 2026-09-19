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
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

use super::NativeAdmission;
use super::Result;

const MAX_AUTHORITY_CONFIG_BYTES: usize = 32 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeAuthorityFile {
    signer_id: String,
    verifying_key: [u8; 32],
    authority_state_dir: PathBuf,
    authority_epoch: u64,
    revocation_revision: u64,
    #[serde(default)]
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
        std::fs::File::open(path)?
            .take((MAX_AUTHORITY_CONFIG_BYTES + 1) as u64)
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_AUTHORITY_CONFIG_BYTES {
            return Err("authority config exceeds 32768 bytes".into());
        }
        let config: NativeAuthorityFile = serde_json::from_slice(&bytes)?;
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
    if admission.operation_id.is_empty()
        || model_provider.is_empty()
        || context_digest.len() != 64
        || !context_digest
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
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
        admission.quota_reservation_digest.to_string(),
        admission.resource_snapshot_digest.to_string(),
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

fn digest_array(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}
