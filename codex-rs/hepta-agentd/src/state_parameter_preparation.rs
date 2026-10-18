use super::*;
use codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1;
impl AgentdState {
    pub(crate) async fn prepare_parameter_input_payload(
        &self,
        round_hex: String,
        search_source: String,
        search_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_admission_query::decode_hex(&round_hex)?,
        )?;
        if crate::client::encode_hex(&round.canonical_bytes()?) != round_hex {
            return Err(AgentdError::Protocol("noncanonical original Round".into()));
        }
        let handle = self.plasticity_runtime_handle().ok_or_else(|| {
            AgentdError::Invalid("original plasticity input owner unavailable".into())
        })?;
        let (input, evidence, baseline) = handle
            .prepare_parameter_input_v1(
                round,
                std::path::PathBuf::from(&search_source),
                search_digest
                    .parse()
                    .map_err(|e| AgentdError::Invalid(format!("search pin: {e}")))?,
            )
            .await
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        crate::parameter_admission_query::validate_response(&input, &evidence)?;
        Ok(crate::AgentdPayload::PreparedParameterInputV1 {
            round_hex,
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
