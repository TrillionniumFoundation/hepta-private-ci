//! Known no-candidate completion shares the original round journal and quota.
//! No fake frozen digest, candidate record or passing flag is manufactured.
use super::*;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RejectedProposal {
    pub(super) reason: AgentdSelfIterationProposalRejectionV1,
    #[serde(with = "super::super::codec::digest")]
    request: Digest32,
    #[serde(with = "super::super::codec::digest")]
    output: Digest32,
    #[serde(with = "super::super::codec::digest")]
    native: Digest32,
}
impl RejectedProposal {
    pub(super) fn validate(&self, current: &RoundState) -> Result<(), AgentdError> {
        let stage = current
            .stages
            .first()
            .ok_or_else(|| invalid("rejected proposal lacks actual G"))?;
        if !current.terminal
            || current.candidate_effects != Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
            || current.frozen.is_some()
            || current.stages.len() != 1
            || stage.role != SelfIterationModelRoleV1::Generator as u8
            || stage.request != self.request
            || stage
                .output
                .as_ref()
                .map(|value| Digest32::of_bytes(value.as_bytes()))
                != Some(self.output)
            || stage.native_run != Some(self.native)
            || self.native.is_zero()
            || self.output.is_zero()
        {
            return Err(invalid(
                "no-candidate rejection differs from durable actual G",
            ));
        }
        Ok(())
    }
}
impl RoundJournal {
    pub(in crate::self_iteration) fn reject_before_candidate_effects(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
        assessment: &SelfIterationModelAssessmentV1,
        reason: AgentdSelfIterationProposalRejectionV1,
    ) -> Result<(), AgentdError> {
        let current = self.current_mut(permit)?;
        if assessment.role != SelfIterationModelRoleV1::Generator
            || assessment.request_id
                != permit.model_request_id(SelfIterationModelRoleV1::Generator, None)?
            || assessment.envelope_digest != permit.execution
            || assessment.candidate_digest.is_some()
            || assessment.authority.grants_any()
            || current.candidate_effects != Some(AgentdSelfIterationCandidateEffectsV1::NotStarted)
            || current.frozen.is_some()
            || current.stages.len() != 1
        {
            return Err(invalid(
                "proposal rejection is not an exact pre-candidate G terminal",
            ));
        }
        let stage = current
            .stages
            .first()
            .ok_or_else(|| invalid("G never admitted"))?;
        if stage.output.as_deref() != Some(assessment.model_output.as_str())
            || stage.native_run != Some(assessment.native_run_digest)
        {
            return Err(invalid(
                "proposal rejection cannot retire an unknown actual G",
            ));
        }
        let rejection = RejectedProposal {
            reason,
            request: stage.request,
            output: Digest32::of_bytes(assessment.model_output.as_bytes()),
            native: assessment.native_run_digest,
        };
        if current
            .rejected_proposal
            .as_ref()
            .is_some_and(|previous| previous != &rejection)
            || current.terminal && current.rejected_proposal.is_none()
        {
            return Err(invalid("original proposal rejection changed"));
        }
        current.terminal = true;
        current.rejected_proposal = Some(rejection);
        Ok(())
    }
}
