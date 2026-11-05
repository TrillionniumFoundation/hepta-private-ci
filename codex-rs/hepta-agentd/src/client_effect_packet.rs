//! Explicit raw packet transport for the ordinary automation effect owner.

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::Instant;
use tokio::time::timeout_at;

use crate::AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AutomationEffectSnapshot;
use crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES;
use crate::MAX_CONTROL_FRAME_BYTES;

use super::AgentdClient;
use super::unexpected;

impl AgentdClient {
    /// Send one complete digest-bound packet under a separately advertised
    /// capability. A transport error never triggers fallback or redispatch;
    /// reconcile the original operation when its outcome is unknown.
    pub async fn automation_execute_effect_packet_v1(
        &self,
        intent: AuthorizedEffectIntent,
        wire_payload: &[u8],
        signed_grant: SignedFinalUseGrant,
        command_id: String,
    ) -> Result<AutomationEffectSnapshot, AgentdError> {
        let deadline = Instant::now() + self.timeout;
        if wire_payload.is_empty() || wire_payload.len() > MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES {
            return Err(AgentdError::Invalid(
                "automation packet payload is empty or too large".to_string(),
            ));
        }
        if Sha256Digest::for_bytes(wire_payload) != intent.payload_digest {
            return Err(AgentdError::Invalid(
                "automation packet does not match its authorized payload digest".to_string(),
            ));
        }
        let wire_len = u32::try_from(wire_payload.len()).map_err(|_| {
            AgentdError::Invalid("automation packet length cannot be represented".to_string())
        })?;
        let request = AgentdRequest::automation_execute_effect_packet_v1(
            self.request_id(),
            self.spawn_generation,
            intent,
            wire_len,
            signed_grant,
            command_id,
        );
        let mut header = serde_json::to_vec(&request)?;
        header.push(b'\n');
        if header.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdError::Protocol(
                "agentd packet header exceeded frame bound".to_string(),
            ));
        }
        // Capability discovery and both connections share this one absolute
        // deadline, including the full body, EOF and bounded response.
        timeout_at(
            deadline,
            codex_uds::guard_future_before_deadline(deadline.into_std(), async {
                let capabilities = self.capabilities().await?;
                if !capabilities.capabilities.iter().any(|capability| {
                    capability.id == AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT_PACKET_V1
                        && capability.major == 1
                }) {
                    return Err(AgentdError::Protocol(
                        "agentd does not advertise automation packet v1 control".to_string(),
                    ));
                }
                let stream = UnixStream::connect(&self.socket_path).await?;
                let (reader, mut writer) = tokio::io::split(stream);
                writer.write_all(&header).await?;
                writer.write_all(wire_payload).await?;
                writer.shutdown().await?;
                let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
                let mut response_bytes = Vec::new();
                reader.read_until(b'\n', &mut response_bytes).await?;
                match self
                    .decode_response(request.request_id, &response_bytes)?
                    .payload
                {
                    AgentdPayload::AutomationEffect(receipt) => Ok(receipt),
                    payload => unexpected(payload),
                }
            }),
        )
        .await
        .ok()
        .flatten()
        .unwrap_or_else(|| {
            Err(AgentdError::Protocol(
                "agentd packet request timed out; reconcile the original effect before retrying"
                    .to_string(),
            ))
        })
    }
}

#[cfg(test)]
#[path = "client_effect_packet_tests.rs"]
mod tests;
