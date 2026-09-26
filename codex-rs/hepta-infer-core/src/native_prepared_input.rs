//! Original native request bytes retained by the existing inference owner.
//! This is recovery material, never a capability or a permit to repeat an effect.

use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::Error;
use super::NativeRequest;
use super::validate_digest;
use super::validate_identity;

/// The exact already-admitted Intelligence context consumed by native execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeIntelligenceInputBindingV1 {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}

/// Bounded original input stored atomically with the native reservation.
/// Historical records lacking this field remain readable, but are not silently
/// upgraded from new ambient input. No raw provider credential is stored here.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativePreparedInputV1 {
    pub schema_version: u32,
    pub prompt: String,
    pub context_query: Option<String>,
    pub agentd_socket: PathBuf,
    pub timeout_ms: u64,
    pub intelligence: Option<NativeIntelligenceInputBindingV1>,
}

impl NativePreparedInputV1 {
    /// Preserve the existing V1/V2 native input digest grammar exactly.
    /// Validation is repeated on append, replay and checkpoint recovery.
    pub fn payload_digest(&self) -> Result<String, Error> {
        if self.schema_version != 1
            || self.prompt.is_empty()
            || self.prompt.len() > 32 * 1024
            || !self.agentd_socket.is_absolute()
            || self.agentd_socket.as_os_str().len() > 4096
            || !(1..=3_600_000).contains(&self.timeout_ms)
            || self
                .context_query
                .as_ref()
                .is_some_and(|query| query.is_empty() || query.len() > 2048)
        {
            return Err(Error::InvalidIdentity("native prepared input"));
        }
        let bytes = match &self.intelligence {
            None => serde_json::to_vec(&(
                "hepta.native-request.v1",
                &self.prompt,
                &self.context_query,
                &self.agentd_socket,
                self.timeout_ms,
            )),
            Some(binding) => {
                validate_identity(&binding.run_id, "native intelligence run")?;
                validate_digest(&binding.context_digest, "native intelligence context")?;
                validate_digest(&binding.envelope_digest, "native intelligence envelope")?;
                if binding.expected_revision == 0 {
                    return Err(Error::InvalidIdentity("native intelligence revision"));
                }
                serde_json::to_vec(&(
                    "hepta.native-intelligence-request.v2",
                    &self.prompt,
                    &self.context_query,
                    &self.agentd_socket,
                    self.timeout_ms,
                    &binding.run_id,
                    binding.expected_revision,
                    &binding.context_digest,
                    &binding.envelope_digest,
                ))
            }
        }
        .map_err(|_| Error::InvalidIdentity("native prepared input encoding"))?;
        Ok(Digest32::of_bytes(&bytes).to_string())
    }

    pub(super) fn validate_request(&self, request: &NativeRequest) -> Result<(), Error> {
        if self.payload_digest()? != request.payload_digest {
            return Err(Error::Conflict);
        }
        Ok(())
    }
}
