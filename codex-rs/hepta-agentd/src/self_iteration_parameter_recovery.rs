//! Completed-only factory path shares original receipt and candidate validation.
use super::*;
use codex_hepta_agent_components::types::StableId;
impl<C: AgentdGovernedParameterGenerationCompilerV1>
    AgentdGovernedParameterCandidateAssemblerV1<C>
{
    pub(super) async fn recover_governed_completed(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<Option<AgentdSelfIterationCandidateV1>, AgentdError> {
        let Some(request) = self.compiler.recovery_request(&envelope, proposal).await? else {
            return Ok(None);
        };
        let expected_proposal = request.proposal_id.clone();
        let expected_generation = request.admission.candidate_generation.get();
        if request.admission.objective_digest != envelope.objective_digest {
            return Err(invalid("parameter recovery objective binding"));
        }
        let Some(receipt) = self
            .producer
            .observe_completed_parameter(request)
            .await
            .map_err(|error| invalid(format!("governed completed observation: {error}")))?
        else {
            return Ok(None);
        };
        validate_receipt(&receipt, &expected_proposal, expected_generation)?;
        let Some(candidate) = self
            .compiler
            .materialize_completed(envelope.clone(), proposal, &receipt)
            .await?
        else {
            return Ok(None);
        };
        validate_candidate(&candidate, &envelope, &receipt, expected_generation)?;
        Ok(Some(candidate))
    }
}
pub(super) fn validate_receipt(
    receipt: &ParameterPlasticityProductReceiptV1,
    expected_proposal: &StableId,
    expected_generation: u64,
) -> Result<(), AgentdError> {
    if receipt.disposition != ParameterPlasticityDispositionV1::UpdateCandidates
        || receipt.proposal.proposal_id != *expected_proposal
        || receipt.proposal.candidate_generation.get() != expected_generation
        || receipt.proposal.authority.grants_any()
        || receipt.registry.authority.grants_any()
        || receipt.composition_digest.is_zero()
        || receipt.registry.proposal_digest != receipt.proposal.proposal_digest
        || receipt.registry.sequence != receipt.committed_registry_anchor.sequence
        || receipt.registry.frame_digest != receipt.committed_registry_anchor.frame_digest
    {
        return Err(invalid(
            "parameter proposal has no anchored admissible update",
        ));
    }
    Ok(())
}
pub(super) fn validate_candidate(
    candidate: &AgentdSelfIterationCandidateV1,
    envelope: &IterationEnvelopeV1,
    receipt: &ParameterPlasticityProductReceiptV1,
    expected_generation: u64,
) -> Result<(), AgentdError> {
    if &candidate.envelope != envelope
        || candidate.successor.generation().map_err(control_error)? != expected_generation
        || candidate.base_generation != receipt.proposal.baseline_generation.get()
        || candidate.governed_proposal_digest != receipt.proposal.proposal_digest
        || candidate.governed_anchor_digest != receipt.committed_registry_anchor.frame_digest
        || candidate.governed_composition_digest != receipt.composition_digest
        || !receipt.proposal.candidates.iter().any(|value| {
            value.candidate_id == candidate.candidate.candidate_id
                && value.kind == ParameterCandidateKindV2::Update
        })
    {
        return Err(invalid(
            "compiled generation changed governed parameter proposal",
        ));
    }
    self_iteration_frozen_candidate_payload_v1(candidate)?;
    Ok(())
}
