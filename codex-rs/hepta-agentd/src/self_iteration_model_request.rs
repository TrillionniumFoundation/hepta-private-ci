//! Original model request preimages shared by the caller and protected inspector.
//! Pure construction/digests do not reserve quota, dispatch models or grant use.
use super::*;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::StableId;

pub fn self_iteration_model_request_digest_v1(request: &SelfIterationModelRequestV1) -> Digest32 {
    round::model::request_digest(request)
}

pub fn self_iteration_generator_model_request_v1(
    round: &AgentdSelfIterationRoundV1,
    envelope: &IterationEnvelopeV1,
    objective_prompt: &str,
    actual_baseline: &str,
) -> Result<SelfIterationModelRequestV1, AgentdError> {
    envelope.validate().map_err(invalid)?;
    let execution = self_iteration_envelope_digest_v1(envelope);
    let request = model_request(
        Some(round),
        SelfIterationModelRoleV1::Generator,
        execution,
        None,
        round.deadline_ms(),
        generator_prompt(objective_prompt, actual_baseline, execution)?,
    )?;
    request
        .validate(round.admitted_at_ms())
        .map_err(|error| invalid(error.to_string()))?;
    Ok(request)
}

pub(super) fn generator_prompt(
    objective_prompt: &str,
    actual_baseline: &str,
    execution: Digest32,
) -> Result<String, AgentdError> {
    if objective_prompt.is_empty()
        || objective_prompt.len() > 2048
        || actual_baseline.is_empty()
        || actual_baseline.len() > 2048
    {
        return Err(invalid(
            "self-iteration objective or baseline prompt budget",
        ));
    }
    Ok(format!(
        "Propose a bounded durable Neuron generation change and its rollback.\nObjective: {objective_prompt}\nActual baseline and permitted mutations: {actual_baseline}\nEnvelope: {execution}\nNo acceptance or signing authority is granted."
    ))
}

pub(super) fn model_request(
    round: Option<&AgentdSelfIterationRoundV1>,
    role: SelfIterationModelRoleV1,
    execution: Digest32,
    candidate: Option<Digest32>,
    deadline_ms: u64,
    prompt: String,
) -> Result<SelfIterationModelRequestV1, AgentdError> {
    let request_id = if let Some(round) = round {
        if round.execution_envelope_digest() != execution || round.deadline_ms() != deadline_ms {
            return Err(invalid(
                "model request differs from original admitted round",
            ));
        }
        round.model_request_id(role, candidate)?
    } else {
        let identity = Digest32::of_parts(&[
            b"hepta.self-iteration.model-request.v1",
            execution.as_array(),
            candidate.unwrap_or(Digest32::ZERO).as_array(),
            &[role as u8],
        ]);
        StableId::new(format!("iteration.{identity}"))
            .map_err(|error| invalid(error.to_string()))?
    };
    Ok(SelfIterationModelRequestV1 {
        request_id,
        role,
        envelope_digest: execution,
        candidate_digest: candidate,
        prompt,
        deadline_ms,
        maximum_response_bytes: 8192,
    })
}
