//! Candidate effects are debited under the original owner and current trust.
use super::*;
impl SelfIterationOwner {
    pub(super) fn begin_candidate_effects(
        &mut self,
        round: AgentdSelfIterationRoundV1,
        assessment: SelfIterationModelAssessmentV1,
        now: u64,
    ) -> Result<AgentdSelfIterationCandidateConstructionAdmissionV1, AgentdError> {
        if !self.trust.is_current_at(now) {
            return Err(invalid(
                "candidate effects lack current original learning trust",
            ));
        }
        let mut rounds = self
            .journal
            .rounds
            .clone()
            .ok_or_else(|| invalid("round not reserved"))?;
        let result = rounds.begin_candidate_effects(&round, &assessment, now)?;
        self.journal.persist_rounds(rounds)?;
        Ok(result)
    }
}
