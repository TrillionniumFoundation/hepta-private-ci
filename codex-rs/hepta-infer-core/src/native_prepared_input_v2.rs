//! Versioned original request input retained by the native journal owner.
//! These bytes permit reconciliation only; they grant no authority to dispatch.

use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::NativeRequest;
use super::validate_digest;
use super::validate_identity;

/// Data-only copy of all fields in the admitted AgentRunSnapshot. Declaration
/// order is also the existing native V3 JSON digest order. The host converts
/// every field explicitly; no current-daemon lookup can fill a missing field.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeRunSnapshotV2 {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: String,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeIntelligenceInputBindingV2 {
    pub snapshot: NativeRunSnapshotV2,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

/// Version 2 retains the complete V3 Intelligence request, unlike the historical
/// V1 prepared-input record's run-id-only V2 digest. There is no implicit upgrade
/// between those formats, and digest-only records remain without retained input.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreparedInputV2 {
    pub schema_version: u32,
    pub prompt: String,
    pub context_query: Option<String>,
    pub agentd_socket: PathBuf,
    /// Matches the existing driver's as_millis digest conversion. A positive
    /// sub-millisecond Duration can encode zero; driver configuration remains
    /// responsible for its existing nonzero Duration check.
    pub timeout_ms: u64,
    pub intelligence: Option<NativeIntelligenceInputBindingV2>,
}

impl NativePreparedInputV2 {
    pub fn payload_digest(&self) -> Result<String, Error> {
        if self.schema_version != 2
            || self.prompt.is_empty()
            || self.prompt.len() > 32 * 1024
            || !self.agentd_socket.is_absolute()
            || self.timeout_ms > 3_600_000
            || self
                .context_query
                .as_ref()
                .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err(Error::InvalidIdentity("native prepared input v2"));
        }
        let bytes = match &self.intelligence {
            None => serde_json::to_vec(&(
                "hepta.native-request.v1",
                &self.prompt,
                &self.context_query,
                &self.agentd_socket,
                u128::from(self.timeout_ms),
            )),
            Some(binding) => {
                let snapshot = &binding.snapshot;
                validate_identity(&snapshot.run_id, "native intelligence run")?;
                for digest in [
                    &snapshot.request_digest,
                    &snapshot.objective_digest,
                    &snapshot.body_digest,
                    &snapshot.artifact_set_digest,
                    &snapshot.fence_digest,
                    &binding.context_digest,
                    &binding.envelope_digest,
                ] {
                    validate_digest(digest, "native intelligence binding")?;
                }
                if binding.expected_revision == 0
                    || snapshot.authority_epoch == 0
                    || snapshot.generation == 0
                    || snapshot.deadline_ms == 0
                {
                    return Err(Error::InvalidIdentity("native intelligence snapshot"));
                }
                serde_json::to_vec(&(
                    "hepta.native-intelligence-request.v3",
                    &self.prompt,
                    &self.context_query,
                    &self.agentd_socket,
                    u128::from(self.timeout_ms),
                    snapshot,
                    binding.expected_revision,
                    &binding.context_digest,
                    &binding.envelope_digest,
                ))
            }
        }
        .map_err(|_| Error::InvalidIdentity("native prepared input v2 encoding"))?;
        Ok(Digest32::of_bytes(&bytes).to_string())
    }

    pub(super) fn validate_request(&self, request: &NativeRequest) -> Result<(), Error> {
        if self.payload_digest()? != request.payload_digest {
            return Err(Error::Conflict);
        }
        Ok(())
    }
}
