//! The first result is original runtime generation, never model/spawn generation.
use super::*;
use codex_hepta_agent_components::plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::plasticity::decode_untrusted_plasticity_admission_v1;
use codex_hepta_agent_components::types::Digest32;
impl AgentdClient {
    pub async fn prepare_parameter_input_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        path: std::path::PathBuf,
        pin: Digest32,
    ) -> Result<
        (
            u64,
            crate::AgentdPlasticityAdmissionInputV1,
            PlasticityAdmissionEvidenceV1,
            crate::ParameterPreparationBaselineV1,
        ),
        AgentdError,
    > {
        if pin.is_zero() || !path.is_absolute() {
            return Err(AgentdError::Invalid("Root search source/pin".into()));
        }
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let search_source = path
            .to_str()
            .ok_or_else(|| AgentdError::Invalid("search path UTF-8".into()))?
            .to_owned();
        let search_digest = pin.to_string();
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PrepareParameterInputV1 {
                    round_hex: round_hex.clone(),
                    search_source: search_source.clone(),
                    search_digest: search_digest.clone(),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::PreparedParameterInputV1 {
                round_hex: actual_round,
                search_source: actual_source,
                search_digest: actual_pin,
                query,
                admission_hex,
                baseline,
            } if actual_round == round_hex
                && actual_source == search_source
                && actual_pin == search_digest =>
            {
                let (input, evidence, baseline) = decode_prepared(
                    &round,
                    query,
                    admission_hex,
                    baseline,
                    &self.expected_agent_id,
                )?;
                Ok((response.current_generation, input, evidence, baseline))
            }
            payload => unexpected(payload),
        }
    }
}

pub(super) fn decode_prepared(
    round: &crate::AgentdSelfIterationRoundV1,
    query: crate::ParameterAdmissionQueryV1,
    admission_hex: String,
    baseline: crate::ParameterPreparationBaselineV1,
    agent: &AgentId,
) -> Result<
    (
        crate::AgentdPlasticityAdmissionInputV1,
        PlasticityAdmissionEvidenceV1,
        crate::ParameterPreparationBaselineV1,
    ),
    AgentdError,
> {
    let input = crate::parameter_admission_query::decode_query(&query)?;
    let evidence = decode_untrusted_plasticity_admission_v1(
        &crate::parameter_admission_query::decode_hex(&admission_hex)?,
    )
    .map_err(|e| AgentdError::Protocol(e.to_string()))?;
    crate::parameter_admission_query::validate_response(&input, &evidence)?;
    if input.generated.candidates.len() > round.candidate_admissions() as usize
        || baseline.registry_head_digest != evidence.artifact_registry_head_digest.to_string()
    {
        return Err(AgentdError::Protocol(
            "prepared original Round/frontier/CURRENT binding".into(),
        ));
    }
    validate_prepared_baseline(&baseline, &input, agent)?;
    Ok((input, evidence, baseline))
}

fn validate_prepared_baseline(
    baseline: &crate::ParameterPreparationBaselineV1,
    input: &crate::AgentdPlasticityAdmissionInputV1,
    agent: &AgentId,
) -> Result<(), AgentdError> {
    if baseline.agent_id != agent.as_str()
        || baseline.artifact_id != input.baseline_id.as_str()
        || baseline.model_generation != input.baseline_generation.get()
        || baseline.model_content_digest
            != input.generator_profile.selected_artifact_digest.to_string()
        || !std::path::Path::new(&baseline.material_source).is_absolute()
        || !std::path::Path::new(&baseline.context_source).is_absolute()
    {
        return Err(AgentdError::Protocol(
            "prepared baseline full binding".into(),
        ));
    }
    codex_hepta_agent_components::types::StableId::new(baseline.model_id.clone())
        .map_err(|e| AgentdError::Protocol(e.to_string()))?;
    for value in [
        &baseline.runtime_configuration_digest,
        &baseline.body_digest,
        &baseline.registry_head_digest,
        &baseline.material_digest,
        &baseline.context_digest,
    ] {
        let digest: Digest32 = value
            .parse()
            .map_err(|e| AgentdError::Protocol(format!("prepared baseline digest: {e}")))?;
        if digest.is_zero() || digest.to_string() != *value {
            return Err(AgentdError::Protocol(
                "prepared baseline canonical digest".into(),
            ));
        }
    }
    Ok(())
}
