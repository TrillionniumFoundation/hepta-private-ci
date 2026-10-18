//! Temporary factual preparation before the unique final context installation.
use super::*;
use codex_hepta_agent_components::plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::types::Digest32;

impl AgentdClient {
    /// Returns runtime generation and original complete facts, without swapping
    /// the owner's installed context, proposing, signing or dispatching a model.
    pub async fn prepare_parameter_input_from_context_v2(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        context_path: std::path::PathBuf,
        context_pin: Digest32,
        search_path: std::path::PathBuf,
        search_pin: Digest32,
    ) -> Result<
        (
            u64,
            crate::AgentdPlasticityAdmissionInputV1,
            PlasticityAdmissionEvidenceV1,
            crate::ParameterPreparationBaselineV2,
        ),
        AgentdError,
    > {
        if context_pin.is_zero()
            || search_pin.is_zero()
            || !context_path.is_absolute()
            || !search_path.is_absolute()
        {
            return Err(AgentdError::Invalid(
                "protected preparation sources/pins".into(),
            ));
        }
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let context_source = context_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("context path UTF-8".into()))?
            .to_owned();
        let context_digest = context_pin.to_string();
        let search_source = search_path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("search path UTF-8".into()))?
            .to_owned();
        let search_digest = search_pin.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PrepareParameterInputFromContextV2 {
                    round_hex: round_hex.clone(),
                    context_source: context_source.clone(),
                    context_digest: context_digest.clone(),
                    search_source: search_source.clone(),
                    search_digest: search_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::PreparedParameterInputFromContextV2 {
                round_hex: actual_round,
                context_source: actual_context,
                context_digest: actual_context_pin,
                search_source: actual_search,
                search_digest: actual_search_pin,
                query,
                admission_hex,
                baseline,
            } if actual_round == round_hex
                && actual_context == context_source
                && actual_context_pin == context_digest
                && actual_search == search_source
                && actual_search_pin == search_digest
                && baseline.baseline.context_source == context_source
                && baseline.baseline.context_digest == context_digest =>
            {
                let predecessor = baseline.proposal_registry_predecessor;
                let digest: Digest32 = predecessor.parse().map_err(|e| {
                    AgentdError::Protocol(format!("actual proposal predecessor: {e}"))
                })?;
                if digest.to_string() != predecessor {
                    return Err(AgentdError::Protocol(
                        "noncanonical actual proposal predecessor".into(),
                    ));
                }
                let (input, evidence, baseline) = super::parameter_preparation::decode_prepared(
                    &round,
                    query,
                    admission_hex,
                    baseline.baseline,
                    &self.expected_agent_id,
                )?;
                Ok((
                    response.current_generation,
                    input,
                    evidence,
                    crate::ParameterPreparationBaselineV2 {
                        baseline,
                        proposal_registry_predecessor: predecessor,
                    },
                ))
            }
            payload => unexpected(payload),
        }
    }
}
