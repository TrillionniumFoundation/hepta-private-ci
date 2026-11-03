//! Request an unconsumed grant from the deployment's existing Unix issuer.
//! The production writer remains the only consumer of its FinalUse nonce.

use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;

use crate::AgentdError;
use crate::AgentdFinalUseGrantFuture;
use crate::AgentdFinalUseGrantProvider;

const SCHEMA_VERSION: u32 = 1;
const OPERATION: &str = "runtime.hepta.production_effect";
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;

/// An adapter to an already operated issuer and an already registered authority.
/// Construction does not create an issuer, signing key, grant, or nonce store.
pub struct AgentdUnixFinalUseGrantProvider {
    socket: PathBuf,
    issuer_uid: u32,
    timeout: Duration,
    authority: FinalUseAuthority,
}

impl AgentdUnixFinalUseGrantProvider {
    pub fn new(
        socket: PathBuf,
        issuer_uid: u32,
        timeout: Duration,
        authority: FinalUseAuthority,
    ) -> Result<Self, AgentdError> {
        if !socket.is_absolute() || timeout.is_zero() || timeout > Duration::from_secs(30) {
            return Err(AgentdError::Invalid(
                "issuer requires an absolute socket and a timeout within 1..=30000 ms".to_owned(),
            ));
        }
        Ok(Self {
            socket,
            issuer_uid,
            timeout,
            authority,
        })
    }

    #[cfg(unix)]
    async fn request(&self, binding: &FinalUseBinding) -> Result<SignedFinalUseGrant, AgentdError> {
        use std::os::unix::fs::FileTypeExt;
        use std::os::unix::fs::MetadataExt;

        let metadata = std::fs::symlink_metadata(&self.socket)?;
        let parent = self
            .socket
            .parent()
            .ok_or_else(|| protocol("issuer socket has no parent"))?;
        let directory = std::fs::symlink_metadata(parent)?;
        if !metadata.file_type().is_socket()
            || metadata.uid() != self.issuer_uid
            || metadata.mode() & 0o007 != 0
            || !directory.is_dir()
            || directory.mode() & 0o022 != 0
        {
            return Err(protocol("issuer socket identity or permissions changed"));
        }
        let request = serde_json::to_vec(&GrantRequest {
            schema_version: SCHEMA_VERSION,
            operation: OPERATION,
            binding,
        })?;
        if request.len() > MAX_REQUEST_BYTES {
            return Err(protocol("issuer request exceeds 16 KiB"));
        }
        let exchange = async {
            let mut stream = tokio::net::UnixStream::connect(&self.socket).await?;
            if stream.peer_cred()?.uid() != self.issuer_uid {
                return Err(protocol(
                    "connected issuer UID differs from the configured issuer",
                ));
            }
            stream
                .write_all(&(request.len() as u32).to_be_bytes())
                .await?;
            stream.write_all(&request).await?;
            stream.flush().await?;
            let size = stream.read_u32().await? as usize;
            if size == 0 || size > MAX_RESPONSE_BYTES {
                return Err(protocol("issuer response must be 1..=65536 bytes"));
            }
            let mut response = vec![0; size];
            stream.read_exact(&mut response).await?;
            let response: GrantResponse = serde_json::from_slice(&response)?;
            if response.schema_version != SCHEMA_VERSION {
                return Err(protocol("unsupported issuer response schema"));
            }
            let current = self
                .authority
                .revocation_head()
                .map_err(|error| protocol(&format!("issuer revocation head: {error}")))?;
            if current != response.revocations {
                self.authority
                    .update_revocations(response.revocations)
                    .map_err(|error| protocol(&format!("issuer revocation update: {error}")))?;
            }
            match (response.grant, response.denial_reason) {
                (Some(signed), None) => {
                    if &signed.grant.binding != binding {
                        return Err(protocol("issuer returned a grant for another operation"));
                    }
                    // Signature, currentness and single consumption are checked by
                    // the original dispatcher at the actual physical entry.
                    Ok(signed)
                }
                (None, Some(reason)) if !reason.is_empty() && reason.len() <= 1024 => Err(
                    protocol(&format!("production effect denied by issuer: {reason}")),
                ),
                _ => Err(protocol(
                    "issuer response must contain exactly one bounded outcome",
                )),
            }
        };
        tokio::time::timeout(self.timeout, exchange)
            .await
            .map_err(|_| {
                protocol("production grant request timed out; original operation retained")
            })?
    }

    #[cfg(not(unix))]
    async fn request(
        &self,
        _binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, AgentdError> {
        Err(protocol(
            "the configured Unix grant provider is unavailable on this platform",
        ))
    }
}

impl AgentdFinalUseGrantProvider for AgentdUnixFinalUseGrantProvider {
    fn signed_grant<'a>(&'a self, binding: &'a FinalUseBinding) -> AgentdFinalUseGrantFuture<'a> {
        Box::pin(self.request(binding))
    }
}

#[derive(Serialize)]
struct GrantRequest<'a> {
    schema_version: u32,
    operation: &'static str,
    binding: &'a FinalUseBinding,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GrantResponse {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<String>,
}

fn protocol(reason: &str) -> AgentdError {
    AgentdError::Protocol(reason.to_owned())
}

#[cfg(all(test, unix))]
#[path = "production_grant_provider_tests.rs"]
mod tests;
