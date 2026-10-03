//! Admit an exact protected context through the original Round command turn.
use super::*;
use codex_hepta_agent_components::types::Digest32;

impl AgentdClient {
    /// Returns runtime generation; spawn and model generations remain separate.
    /// A disconnected caller cannot cancel an already queued owner command. An
    /// ambiguous failure must be observed through the original prepared context.
    pub async fn refresh_parameter_input_context_v2(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        path: std::path::PathBuf,
        pin: Digest32,
    ) -> Result<u64, AgentdError> {
        if pin.is_zero() || !path.is_absolute() {
            return Err(AgentdError::Invalid("Root context source/pin".into()));
        }
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let context_source = path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("context path UTF-8".into()))?
            .to_owned();
        let context_digest = pin.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::RefreshParameterInputContextV2 {
                    round_hex: round_hex.clone(),
                    context_source: context_source.clone(),
                    context_digest: context_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::ParameterInputContextRefreshedV2 {
                round_hex: actual_round,
                context_source: actual_source,
                context_digest: actual_pin,
            } if actual_round == round_hex
                && actual_source == context_source
                && actual_pin == context_digest =>
            {
                Ok(response.current_generation)
            }
            payload => unexpected(payload),
        }
    }
}
