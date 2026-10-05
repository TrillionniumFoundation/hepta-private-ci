//! Reserve candidate effects in the same original durable round, before prepare.
use super::*;
impl RoundJournal {
    pub(in crate::self_iteration) fn begin_candidate_effects(
        &mut self,
        permit: &AgentdSelfIterationRoundV1,
        assessment: &SelfIterationModelAssessmentV1,
        now: u64,
    ) -> Result<AgentdSelfIterationCandidateConstructionAdmissionV1, AgentdError> {
        if now < self.watermark_ms || now >= permit.deadline_ms() {
            return Err(invalid("candidate effects admission clock"));
        }
        let current = self.current_mut(permit)?;
        let generator = current
            .stages
            .first()
            .ok_or_else(|| invalid("candidate effects lack admitted G"))?;
        if current.terminal
            || current.rejected_proposal.is_some()
            || assessment.role != SelfIterationModelRoleV1::Generator
            || assessment.request_id
                != permit.model_request_id(SelfIterationModelRoleV1::Generator, None)?
            || assessment.envelope_digest != permit.execution
            || assessment.candidate_digest.is_some()
            || assessment.authority.grants_any()
            || generator.output.as_deref() != Some(assessment.model_output.as_str())
            || generator.native_run != Some(assessment.native_run_digest)
        {
            return Err(invalid("candidate effects differ from original actual G"));
        }
        match current.candidate_effects {
            Some(AgentdSelfIterationCandidateEffectsV1::NotStarted) => {
                current.candidate_effects = Some(AgentdSelfIterationCandidateEffectsV1::Started);
                Ok(AgentdSelfIterationCandidateConstructionAdmissionV1::Fresh)
            }
            _ => Ok(AgentdSelfIterationCandidateConstructionAdmissionV1::Pending),
        }
    }
}
