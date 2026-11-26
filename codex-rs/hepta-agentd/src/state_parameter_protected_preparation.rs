use super::*;
use crate::plasticity_runtime::parameter_preparation::ProtectedParameterPreparationV2;
use codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1;
use codex_hepta_agent_components::types::Digest32;

impl AgentdState {
    pub(crate) async fn prepare_parameter_input_from_context_payload(
        &self,
        round_hex: String,
        context_source: String,
        context_digest: String,
        search_source: String,
        search_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_admission_query::decode_hex(&round_hex)?,
        )?;
        let expected_round = round.clone();
        let generation = self.current_generation()?;
        let source =
            |path: &str, digest: &str| -> Result<(std::path::PathBuf, Digest32), AgentdError> {
                let path = std::path::PathBuf::from(path);
                let pin: Digest32 = digest
                    .parse()
                    .map_err(|e| AgentdError::Invalid(format!("preparation pin: {e}")))?;
                if !path.is_absolute() || pin.is_zero() || pin.to_string() != digest {
                    return Err(AgentdError::Protocol(
                        "protected preparation source/pin".into(),
                    ));
                }
                Ok((path, pin))
            };
        let request = ProtectedParameterPreparationV2 {
            round,
            context: source(&context_source, &context_digest)?,
            search: source(&search_source, &search_digest)?,
        };
        let iteration = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("original Round owner unavailable".into()))?;
        let handle = self
            .plasticity_runtime_handle()
            .ok_or_else(|| AgentdError::Invalid("original plasticity owner unavailable".into()))?;
        let (input, evidence, baseline) = handle
            .prepare_parameter_input_from_context_v2(iteration, request)
            .await
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        if self.current_generation()? != generation
            || iteration
                .inspect_current_round()
                .await?
                .is_none_or(|view| view.status.round != expected_round)
        {
            return Err(AgentdError::GenerationFenced(
                "protected preparation original Round/runtime changed".into(),
            ));
        }
        crate::parameter_admission_query::validate_response(&input, &evidence)?;
        Ok(crate::AgentdPayload::PreparedParameterInputFromContextV2 {
            round_hex,
            context_source,
            context_digest,
            search_source,
            search_digest,
            query: crate::parameter_admission_query::query(&input)?,
            baseline,
            admission_hex: crate::client::encode_hex(
                &encode_untrusted_plasticity_admission_v1(&evidence)
                    .map_err(|e| AgentdError::Invalid(e.to_string()))?,
            ),
        })
    }
}
