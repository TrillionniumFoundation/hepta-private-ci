//! Finite Root read through the original authenticated control client.
use super::*;
use codex_hepta_agent_components::plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::plasticity::decode_untrusted_plasticity_admission_v1;

impl AgentdClient {
    /// Read all original current seven-owner facts without proposing. The first
    /// result is runtime generation; `send` separately verifies spawn and peer.
    /// These facts require the independent original Observer signature.
    pub async fn resolve_parameter_admission_v1(
        &self,
        input: crate::AgentdPlasticityAdmissionInputV1,
    ) -> Result<(u64, PlasticityAdmissionEvidenceV1), AgentdError> {
        let query = crate::parameter_admission_query::query(&input)?;
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::ResolveParameterAdmissionV1 {
                    query: query.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::ParameterAdmissionV1 {
                query: actual,
                admission_hex,
            } if actual == query => {
                let admission = decode_untrusted_plasticity_admission_v1(
                    &crate::parameter_admission_query::decode_hex(&admission_hex)?,
                )
                .map_err(|e| AgentdError::Protocol(e.to_string()))?;
                crate::parameter_admission_query::validate_response(&input, &admission)?;
                Ok((response.current_generation, admission))
            }
            payload => unexpected(payload),
        }
    }
}
