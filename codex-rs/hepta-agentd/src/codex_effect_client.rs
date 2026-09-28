//! The existing authenticated Agentd transport is the only caller of this port.
use super::*;
use crate::CodexEffectBinding;
use crate::CodexEffectDecision;
use crate::CodexEffectReceipt;

impl AgentdClient {
    pub async fn run_enter_effect(
        &self,
        binding: CodexEffectBinding,
    ) -> Result<CodexEffectReceipt, AgentdError> {
        self.codex_effect(binding, None).await
    }

    pub async fn run_abort_before_effect(
        &self,
        binding: CodexEffectBinding,
        reason: String,
    ) -> Result<CodexEffectReceipt, AgentdError> {
        self.codex_effect(binding, Some(reason)).await
    }

    async fn codex_effect(
        &self,
        binding: CodexEffectBinding,
        reason: Option<String>,
    ) -> Result<CodexEffectReceipt, AgentdError> {
        binding.validate().map_err(AgentdError::Invalid)?;
        if binding.generation != self.spawn_generation {
            return Err(AgentdError::Protocol(
                "effect binding generation mismatch".to_string(),
            ));
        }
        let decision = if reason.is_some() {
            CodexEffectDecision::AbortedBeforeEffect
        } else {
            CodexEffectDecision::Entered
        };
        let method = match &reason {
            Some(reason) => crate::AgentdMethod::RunAbortBeforeEffect {
                binding: binding.clone(),
                reason: reason.clone(),
            },
            None => crate::AgentdMethod::RunEnterEffect {
                binding: binding.clone(),
            },
        };
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method,
            })
            .await?;
        let AgentdPayload::CodexEffect(receipt) = response.payload else {
            return unexpected(response.payload);
        };
        if receipt.binding != binding
            || receipt.decision != decision
            || receipt.reason != reason
            || receipt.owner_revision != binding.expected_revision + 1
        {
            return Err(AgentdError::Protocol(
                "Codex effect acknowledgement binding mismatch".to_string(),
            ));
        }
        Ok(receipt)
    }
}
