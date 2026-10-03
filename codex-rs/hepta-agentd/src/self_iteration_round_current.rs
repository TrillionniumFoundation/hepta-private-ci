//! Cold current-round discovery uses the same original journal reservation.
use super::*;

/// Original current facts, including model tasks that outlive a rejected
/// candidate. This observation grants no admission or result-use authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdSelfIterationCurrentRoundV1 {
    pub status: AgentdSelfIterationRoundStatusV1,
    pub has_pending_model_requests: bool,
}
impl AgentdSelfIterationCurrentRoundV1 {
    /// Current policy, time, quota and owner admission still govern a new round.
    pub fn can_admit_next_round(&self) -> bool {
        self.status.terminal && !self.has_pending_model_requests
    }
}
impl RoundJournal {
    pub(in crate::self_iteration) fn current_status(
        &self,
    ) -> Result<Option<AgentdSelfIterationCurrentRoundV1>, AgentdError> {
        self.validate()?;
        let Some(current) = &self.current else {
            return Ok(None);
        };
        let goal = StableId::new(&current.permit.goal).map_err(|e| invalid(e.to_string()))?;
        Ok(Some(AgentdSelfIterationCurrentRoundV1 {
            status: self.status(&goal, current.permit.policy)?,
            has_pending_model_requests: current.stages.iter().any(ModelStage::pending),
        }))
    }
}
