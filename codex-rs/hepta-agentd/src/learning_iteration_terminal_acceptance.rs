//! Only an owned same-session acceptance request enters this blocking job.
//! The historical stage borrow never leaves its original operation or lane.

use super::*;

impl RegisteredHistoricalLearningSourceV1 {
    pub(super) async fn accept_original_terminal(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        state: &AgentdState,
    ) -> Result<(), AgentdError> {
        require_complete(self, snapshot)?;
        require_ready(state).map_err(refused)?;
        if state.identity() != &self.identity || Instant::now() >= self.end {
            return Err(refused("original terminal recipient or deadline differs"));
        }
        let original = self
            .terminal_acceptance
            .try_lock()
            .map_err(|_| refused("original terminal acceptance busy"))?
            .take()
            .ok_or_else(|| refused("original terminal acceptance already consumed"))?;
        // This owned job is awaited without cancellation detaching it. Root's
        // existing frame and original session deadlines still bound the call.
        let accepted = tokio::task::spawn_blocking(move || {
            crate::root_completed_learning_history::OriginalCompletedLearningAcceptanceV1::accept(
                original,
            )
        })
        .await
        .map_err(refused)??;
        require_ready(state).map_err(refused)?;
        if state.identity() != &self.identity
            || Instant::now() >= self.end
            || accepted.initial != self.prepared.initial().head_digest.to_string()
            || accepted.frozen_scope != self.prepared.scope().binding().to_string()
            || accepted.terminal_head != snapshot.head_digest.to_string()
        {
            return Err(refused("original terminal Root acceptance differs"));
        }
        Ok(())
    }
}
