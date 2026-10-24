//! Obtain the original Root token from the same authenticated checkpoint lane.

use super::*;
use crate::AgentdProtectedCheckpointInputs;
use codex_hepta_memory::CognitiveCheckpointCommand;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::CognitiveCheckpointStatus;
use std::sync::Arc;

impl AgentdUnixCognitiveCheckpointTransport {
    /// Consume this sole Root-authenticated lane and obtain its real Current
    /// receipt. `expected` comes from the trusted sealed Root handoff; a local
    /// DB/hash cannot substitute for it. The opaque token is copied only from
    /// the original ReadHead ACK and is never derived from public head JSON.
    ///
    /// Failure drops this lane, with no retry, reconnect or owner fallback.
    /// Success retains this exact stream for original protected recovery and
    /// whole-owner binding, which independently rechecks Current before writes.
    pub async fn into_protected_inputs(
        self,
        expected: CognitiveCheckpointHead,
    ) -> Result<AgentdProtectedCheckpointInputs<Self>, ObjectiveSenderCheckpointError> {
        if expected.schema_version != 1 || expected.publisher_epoch == 0
            || expected.counter == 0 || expected.counter == u64::MAX
            || expected.phase != CognitiveCheckpointPhase::Current || expected.proposal.is_some()
            || expected.last_current.owner_agent_id != expected.owner_agent_id
            || expected.last_current.profile != "hepta:cognitive:exact-current-cut:v1"
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        let sequence = expected.last_mutation_sequence.checked_add(1)
            .ok_or(ObjectiveSenderCheckpointError::Refused)?;
        let request = CognitiveCheckpointRequest {
            schema_version: 1,
            operation: "runtime.cognitive.checkpoint.v1".into(),
            request_id: format!("{:016x}{sequence:016x}", expected.publisher_epoch),
            command: CognitiveCheckpointCommand::ReadHead,
            expected: None, proposal: None,
        };
        let bytes = serde_json::to_vec(&request).map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        let raw = self.exchange(&bytes).await?;
        let response: CognitiveCheckpointResponse = serde_json::from_slice(&raw)
            .map_err(|_| ObjectiveSenderCheckpointError::Unavailable)?;
        if response.schema_version != 1 || response.request_id != request.request_id {
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        match response.status {
            CognitiveCheckpointStatus::Refused => return Err(ObjectiveSenderCheckpointError::Refused),
            CognitiveCheckpointStatus::Unknown => return Err(ObjectiveSenderCheckpointError::Unavailable),
            CognitiveCheckpointStatus::Ack => {}
        }
        if response.reason.is_some() {
            return Err(ObjectiveSenderCheckpointError::Unavailable);
        }
        let receipt = CognitiveCheckpointReceipt {
            head: response.head.ok_or(ObjectiveSenderCheckpointError::Unavailable)?,
            token: response.token.ok_or(ObjectiveSenderCheckpointError::Unavailable)?,
        };
        if receipt.head != expected || receipt.token.publisher_epoch != expected.publisher_epoch
            || receipt.token.counter != expected.counter
        {
            return Err(ObjectiveSenderCheckpointError::Refused);
        }
        Ok(AgentdProtectedCheckpointInputs {
            deadline: self.timeout, transport: Arc::new(self), current_receipt: receipt,
        })
    }
}
