//! Read through the one installed writer owner; no fresh writer or store.
use super::*;
impl AgentdState {
    pub(crate) async fn resolve_parameter_admission(
        &self,
        query: crate::ParameterAdmissionQueryV1,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let input = crate::parameter_admission_query::decode_query(&query)?;
        let producer = self.plasticity_runtime.get().ok_or_else(|| {
            AgentdError::Invalid("original plasticity runtime unavailable".into())
        })?;
        let admission = producer
            .runtime_handle()
            .resolve_parameter_admission(input.clone())
            .await
            .map_err(|e| AgentdError::Invalid(format!("original parameter admission: {e}")))?;
        crate::parameter_admission_query::validate_response(&input, &admission)?;
        let bytes =
            codex_hepta_agent_components::plasticity::encode_untrusted_plasticity_admission_v1(
                &admission,
            )
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        Ok(crate::AgentdPayload::ParameterAdmissionV1 {
            query,
            admission_hex: crate::client::encode_hex(&bytes),
        })
    }
}
