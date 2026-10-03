//! Same original profile and factual inputs on both sides of the finite read.
use crate::AgentdError;
use crate::AgentdPlasticityAdmissionInputV1;
use crate::ParameterAdmissionQueryV1;
use codex_hepta_agent_components::plasticity::PlasticityAdmissionEvidenceV1;
use codex_hepta_agent_components::plasticity::decode_untrusted_parameter_generator_profile_v3;
use codex_hepta_agent_components::plasticity::encode_untrusted_parameter_generator_profile_v3;
use codex_hepta_agent_components::plasticity::generate_parameter_candidates_v3;
use codex_hepta_agent_components::plasticity::validate_parameter_admission_binding_v1;
use codex_hepta_agent_components::types::Generation;

pub(crate) fn decode_hex(value: &str) -> Result<Vec<u8>, AgentdError> {
    decode_hex_bounded(value, crate::MAX_CONTROL_FRAME_BYTES as usize)
}

pub(crate) fn decode_hex_bounded(
    value: &str,
    maximum_encoded_bytes: usize,
) -> Result<Vec<u8>, AgentdError> {
    if value.is_empty() || value.len() > maximum_encoded_bytes || !value.len().is_multiple_of(2) {
        return Err(AgentdError::Protocol(
            "parameter admission whole hex bound".into(),
        ));
    }
    let mut bytes = Vec::with_capacity(value.len() / 2);
    for pair in value.as_bytes().chunks_exact(2) {
        let nibble = |c| match c {
            b'0'..=b'9' => Ok(c - b'0'),
            b'a'..=b'f' => Ok(c - b'a' + 10),
            _ => Err(AgentdError::Protocol(
                "parameter admission lowercase hex".into(),
            )),
        };
        bytes.push((nibble(pair[0])? << 4) | nibble(pair[1])?);
    }
    Ok(bytes)
}

pub(crate) fn query(
    input: &AgentdPlasticityAdmissionInputV1,
) -> Result<ParameterAdmissionQueryV1, AgentdError> {
    let profile = encode_untrusted_parameter_generator_profile_v3(&input.generator_profile)
        .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    let query = ParameterAdmissionQueryV1 {
        baseline_id: input.baseline_id.to_string(),
        objective_digest: input.objective_digest.to_string(),
        profile_hex: crate::client::encode_hex(&profile),
        baseline_generation: input.baseline_generation.get(),
        candidate_generation: input.candidate_generation.get(),
        dataset_digest: input.dataset_digest.to_string(),
        update_rule_digest: input.update_rule_digest.to_string(),
        modulator_digest: input.modulator_digest.to_string(),
        modulator_broadcast_digest: input.modulator_broadcast_digest.to_string(),
        eligibility_digest: input.eligibility_digest.to_string(),
    };
    if decode_query(&query)? != *input {
        return Err(AgentdError::Invalid(
            "parameter admission generated inputs changed".into(),
        ));
    }
    Ok(query)
}

pub(crate) fn decode_query(
    query: &ParameterAdmissionQueryV1,
) -> Result<AgentdPlasticityAdmissionInputV1, AgentdError> {
    let profile = decode_untrusted_parameter_generator_profile_v3(&decode_hex(&query.profile_hex)?)
        .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    let generated = generate_parameter_candidates_v3(profile.clone())
        .map_err(|e| AgentdError::Invalid(e.to_string()))?;
    Ok(AgentdPlasticityAdmissionInputV1 {
        baseline_id: codex_hepta_agent_components::types::StableId::new(&query.baseline_id)
            .map_err(invalid)?,
        objective_digest: query.objective_digest.parse().map_err(invalid)?,
        generator_profile: profile,
        generated,
        baseline_generation: Generation::new(query.baseline_generation).map_err(invalid)?,
        candidate_generation: Generation::new(query.candidate_generation).map_err(invalid)?,
        dataset_digest: query.dataset_digest.parse().map_err(invalid)?,
        update_rule_digest: query.update_rule_digest.parse().map_err(invalid)?,
        modulator_digest: query.modulator_digest.parse().map_err(invalid)?,
        modulator_broadcast_digest: query.modulator_broadcast_digest.parse().map_err(invalid)?,
        eligibility_digest: query.eligibility_digest.parse().map_err(invalid)?,
    })
}

pub(crate) fn validate_response(
    input: &AgentdPlasticityAdmissionInputV1,
    admission: &PlasticityAdmissionEvidenceV1,
) -> Result<(), AgentdError> {
    validate_parameter_admission_binding_v1(&input.generator_profile, &input.generated, admission)
        .map_err(|e| AgentdError::Protocol(e.to_string()))?;
    if admission.baseline_id != input.baseline_id
        || admission.objective_digest != input.objective_digest
        || admission.baseline_generation != input.baseline_generation
        || admission.candidate_generation != input.candidate_generation
        || admission.dataset_digest != input.dataset_digest
        || admission.update_rule_digest != input.update_rule_digest
        || admission.modulator_digest != input.modulator_digest
        || admission.modulator_broadcast_digest != input.modulator_broadcast_digest
        || admission.eligibility_digest != input.eligibility_digest
    {
        return Err(AgentdError::Protocol(
            "parameter admission factual response changed".into(),
        ));
    }
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
