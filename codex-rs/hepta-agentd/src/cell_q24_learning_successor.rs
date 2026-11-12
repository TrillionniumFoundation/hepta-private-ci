//! One registered waiting service, tied to the actual aggregate and factory.
//! Notification occurs after real generation-owner installation and lane exit.

use super::*;
use crate::circuit_q24_successor::SuccessorSlot;
use crate::root_production_inputs::OriginalQ24SuccessorSession;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) async fn register_original_successor(
        &self,
        session: Arc<OriginalQ24SuccessorSession>,
        slot: &Arc<SuccessorSlot>,
    ) -> Result<(), Error> {
        let inner = Arc::clone(&self.inner);
        let weak = Arc::downgrade(slot);
        self.inner
            .in_original_prepared_lane(move |owners, _runtime, _read| {
                session
                    .require_current_successor_session()
                    .map_err(unavailable)?;
                owners
                    .factory
                    .require_successor_session(&session)
                    .map_err(unavailable)?;
                if owners.generation.is_some() || inner.successor.set(weak).is_err() {
                    return Err(Error::WrongScope);
                }
                session
                    .require_current_successor_session()
                    .map_err(unavailable)?;
                Ok(())
            })
            .await
    }

    pub(crate) async fn with_original_successor_read<T>(
        &self,
        context: Arc<crate::learning_iteration::OriginalQ24SuccessorContext>,
        work: impl FnOnce() -> Result<T, crate::AgentdError> + Send + 'static,
    ) -> Result<T, Error>
    where
        T: Send + 'static,
    {
        if !std::ptr::eq(self, context.owners().as_ref()) {
            return Err(Error::WrongScope);
        }
        self.inner
            .in_original_prepared_lane(move |_, _, read| {
                context
                    .require_original_successor_operation(read)
                    .map_err(unavailable)?;
                let result = work();
                context
                    .require_original_successor_operation(read)
                    .map_err(unavailable)?;
                result.map_err(unavailable)
            })
            .await
    }

    pub(super) fn notify_original_successor_generation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        if let Some(registered) = self.inner.successor.get() {
            let slot = registered.upgrade().ok_or(Error::Unavailable)?;
            slot.original_generation_installed(snapshot)?;
        }
        Ok(())
    }
}
