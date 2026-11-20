//! Synchronous observation of the actual installed successor. A scheduling
//! hint is never an admission or a replacement for a current Source operation.

use super::*;

impl SuccessorSlot {
    pub(crate) fn original_generation_ready_hint(&self) -> bool {
        if self.closed.is_cancelled() {
            return false;
        }
        self.state.lock().is_ok_and(|state| {
            state.phase == Phase::Ready && state.generation && state.installed.is_some()
        })
    }

    /// The caller must already be inside its real, registered aggregate's
    /// fresh Source operation. Check again after its effect, never across an
    /// asynchronous wait. Errors retain the original wait's close behavior.
    pub(crate) fn require_original_generation_ready(
        self: &Arc<Self>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningError> {
        let mut close = CloseOnDrop::new(self);
        self.require_open()
            .map_err(|_| LearningError::Unavailable)?;
        remaining(snapshot.request.envelope.expiry_unix_seconds)?;
        {
            let state = self.state.lock().map_err(|_| LearningError::Unavailable)?;
            let original = state.decision.as_ref().ok_or(LearningError::WrongScope)?;
            if snapshot.request != original.request
                || snapshot.owners != original.owners
                || !snapshot.receipts.starts_with(&original.receipts)
            {
                return Err(LearningError::WrongScope);
            }
            if state.phase != Phase::Ready
                || !state.generation
                || state.installed.is_none()
                || self.closed.is_cancelled()
            {
                return Err(LearningError::Unavailable);
            }
        }
        self.require_open()
            .map_err(|_| LearningError::Unavailable)?;
        remaining(snapshot.request.envelope.expiry_unix_seconds)?;
        close.disarm();
        Ok(())
    }
}
