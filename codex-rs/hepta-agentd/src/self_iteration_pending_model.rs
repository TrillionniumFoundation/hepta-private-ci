//! A real Generator model turn while installation awaits actual model/data
//! inputs. It returns advisory text and cannot call freeze, select or apply.

use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelPortV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1;
use codex_hepta_agent_components::types::StableId;

use super::*;

pub struct AgentdSelfIterationPendingProposalV1 {
    pub readiness: AgentdSelfIterationArtifactReadinessV1,
    pub assessment: SelfIterationModelAssessmentV1,
}

pub async fn assess_self_iteration_pending_inputs_v1<M: SelfIterationModelPortV1>(
    model: &mut M,
    envelope: &IterationEnvelopeV1,
    objective_prompt: &str,
    readiness: &AgentdSelfIterationArtifactReadinessV1,
) -> Result<AgentdSelfIterationPendingProposalV1, AgentdError> {
    envelope.validate().map_err(invalid)?;
    if objective_prompt.is_empty() || objective_prompt.len() > 2 * 1024 {
        return Err(invalid("pending proposal objective prompt budget"));
    }
    let deadline_ms = envelope
        .expiry_unix_seconds
        .checked_mul(1_000)
        .ok_or_else(|| invalid("pending proposal deadline overflow"))?;
    let now = super::cycle::now_ms()?;
    if deadline_ms <= now || deadline_ms > now.saturating_add(3_600_000) {
        return Err(invalid("pending proposal deadline"));
    }
    let context = match readiness {
        AgentdSelfIterationArtifactReadinessV1::PendingInputs {
            descriptor_digest,
            manifest_missing,
            missing,
        } => {
            format!(
                "Installed descriptor: {descriptor_digest:?}; manifest missing: {manifest_missing}; missing actual inputs: {missing:?}"
            )
        }
        AgentdSelfIterationArtifactReadinessV1::InputsVerifiedAwaitingOwnerQualification {
            descriptor_digest,
            ..
        } => {
            format!(
                "Installed descriptor: {descriptor_digest}; checksummed input files still await actual generation-owner parsing and independent Eval qualification."
            )
        }
    };
    let envelope_digest = super::cycle::envelope_digest(envelope);
    // Separate identity from a fully assembled cycle. Becoming ready must not
    // reuse an earlier native request with a changed Generator prompt.
    let identity = Digest32::of_parts(&[
        b"hepta.self-iteration.pending-model-proposal.v1",
        envelope_digest.as_array(),
        context.as_bytes(),
    ]);
    let request = SelfIterationModelRequestV1 {
        request_id: StableId::new(format!("iteration.pending.{identity}"))
            .map_err(|error| invalid(error.to_string()))?,
        role: SelfIterationModelRoleV1::Generator,
        envelope_digest,
        candidate_digest: None,
        prompt: format!(
            "Propose a bounded change and a concrete qualification plan for the future governed parameter owner.\nObjective: {objective_prompt}\nActual input readiness: {context}\nThere is no ready candidate to apply. Do not claim training, calibration, holdout measurements or independent acceptance. No private chat or repository fixture is an installed dataset. This turn is advisory and grants no signing, activation or result-use authority."
        ),
        deadline_ms,
        maximum_response_bytes: 8 * 1024,
    };
    request
        .validate(now)
        .map_err(|error| invalid(error.to_string()))?;
    let assessment = model
        .assess(request.clone())
        .await
        .map_err(|error| invalid(format!("pending Generator model turn: {error}")))?;
    assessment
        .validate(&request)
        .map_err(|error| invalid(error.to_string()))?;
    Ok(AgentdSelfIterationPendingProposalV1 {
        readiness: readiness.clone(),
        assessment,
    })
}

#[cfg(test)]
#[path = "self_iteration_pending_model_tests.rs"]
mod tests;
