use super::*;

impl AgentdSelfIterationHandleV1 {
    /// Discover the original cold reservation without substituting a new Goal
    /// or CURRENT model. None is not proof that other legacy effects are absent.
    pub async fn inspect_current_round(
        &self,
    ) -> Result<Option<AgentdSelfIterationCurrentRoundV1>, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::InspectCurrentRound(response), receive)
            .await
    }
}
impl SelfIterationOwner {
    pub(super) fn inspect_current_round(
        &self,
    ) -> Result<Option<AgentdSelfIterationCurrentRoundV1>, AgentdError> {
        match &self.journal.rounds {
            Some(rounds) => rounds.current_status(),
            None if self.journal.pending() => {
                Err(invalid("legacy pending candidate requires exact recovery"))
            }
            None => Ok(None),
        }
    }
}
