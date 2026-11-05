//! Bounded raw-packet transport for the versioned PoN effect method.
//!
//! Admission proves complete framing and payload identity, not authorization.
//! The ordinary effect owner still verifies the PQ grant and owns dispatch.

use std::sync::Arc;

use codex_hepta_contracts::Sha256Digest;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;

use crate::AGENTD_OVERLOAD_RETRY_AFTER_MS;
use crate::AgentdError;
use crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES;
use crate::NeuralCognitiveExecutionV1;

pub(crate) const PACKET_CONNECTION_CAPACITY: usize = 2;

/// Complete immutable packet bytes with a reservation retained through provider
/// execution, including an execution thread that outlives its control future.
pub(crate) struct AdmittedEffectPacketV1 {
    wire_payload: Vec<u8>,
    retention: Arc<OwnedSemaphorePermit>,
    execution: NeuralCognitiveExecutionV1,
}

impl AdmittedEffectPacketV1 {
    /// Read one exact packet and the client's write-side EOF. The caller owns
    /// the absolute deadline; progress never extends that deadline here.
    pub(crate) async fn read(
        reader: &mut (impl AsyncRead + Unpin),
        wire_len: u32,
        expected_digest: &Sha256Digest,
        permits: Arc<Semaphore>,
        execution: &NeuralCognitiveExecutionV1,
    ) -> Result<Self, AgentdError> {
        execution.check().map_err(AgentdError::Protocol)?;
        let wire_len = usize::try_from(wire_len)
            .ok()
            .filter(|length| *length > 0 && *length <= MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES)
            .ok_or_else(|| {
                AgentdError::Invalid("automation effect packet length is invalid".to_string())
            })?;
        let retention = Arc::new(permits.try_acquire_owned().map_err(|_| {
            AgentdError::Overloaded {
                retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS,
            }
        })?);
        let mut wire_payload = vec![0_u8; wire_len];
        reader.read_exact(&mut wire_payload).await?;
        let mut trailing = [0_u8; 1];
        if reader.read(&mut trailing).await? != 0 {
            return Err(AgentdError::Protocol(
                "automation effect packet has trailing bytes".to_string(),
            ));
        }
        if Sha256Digest::for_bytes(&wire_payload) != *expected_digest {
            return Err(AgentdError::Invalid(
                "automation effect packet digest mismatch".to_string(),
            ));
        }
        execution.check().map_err(AgentdError::Protocol)?;
        Ok(Self {
            wire_payload,
            retention,
            execution: execution.clone(),
        })
    }

    pub(crate) fn wire_payload(&self) -> &[u8] {
        &self.wire_payload
    }

    pub(crate) fn retention(&self) -> Arc<OwnedSemaphorePermit> {
        Arc::clone(&self.retention)
    }

    pub(crate) fn execution(&self) -> &NeuralCognitiveExecutionV1 {
        &self.execution
    }
}

#[cfg(test)]
#[path = "control_packet_tests.rs"]
mod tests;
