//! Consume a Root-retained whole independent E preparation result once.
use super::*;

impl AgentdSelfIterationHandleV1 {
    pub async fn complete_preparation(
        &self,
        round: AgentdSelfIterationRoundV1,
        terminal: AgentdSelfIterationPreparationTerminalV1,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::CompletePreparation(round, terminal, response),
            receive,
        )
        .await
    }
}
