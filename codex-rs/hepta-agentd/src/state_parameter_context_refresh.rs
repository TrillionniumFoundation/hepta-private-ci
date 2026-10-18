use super::*;
use codex_hepta_agent_components::types::Digest32;

impl AgentdState {
    pub(crate) async fn refresh_parameter_input_context_payload(
        &self,
        round_hex: String,
        context_source: String,
        context_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_admission_query::decode_hex(&round_hex)?,
        )?;
        let pin: Digest32 = context_digest
            .parse()
            .map_err(|e| AgentdError::Invalid(format!("context pin: {e}")))?;
        let path = std::path::PathBuf::from(&context_source);
        if pin.is_zero() || pin.to_string() != context_digest || !path.is_absolute() {
            return Err(AgentdError::Protocol("protected context source/pin".into()));
        }
        let generation = self.current_generation()?;
        let iteration = self.self_iteration_handle.get().ok_or_else(|| {
            AgentdError::Invalid("original iteration context owner unavailable".into())
        })?;
        let plasticity = self.plasticity_runtime_handle().ok_or_else(|| {
            AgentdError::Invalid("original plasticity input owner unavailable".into())
        })?;
        plasticity
            .refresh_input_context_for_round_v2(iteration, round.clone(), path, pin)
            .await
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        // Explicit Round is checked in the same original command turn before
        // loading and replacing context. Final observations grant no new effect.
        if self.current_generation()? != generation
            || iteration
                .inspect_current_round()
                .await?
                .is_none_or(|current| current.status.round != round)
        {
            return Err(AgentdError::GenerationFenced(
                "context refresh original Round/runtime changed".into(),
            ));
        }
        Ok(crate::AgentdPayload::ParameterInputContextRefreshedV2 {
            round_hex,
            context_source,
            context_digest,
        })
    }
}
