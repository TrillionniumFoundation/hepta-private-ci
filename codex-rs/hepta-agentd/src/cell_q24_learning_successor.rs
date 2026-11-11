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
        self.inner.in_lane(move |owners, _training, _runtime| {
            session.require_current_successor_session().map_err(unavailable)?;
            owners.factory.require_successor_session(&session).map_err(unavailable)?;
            if owners.generation.is_some() || inner.successor.set(weak).is_err() {
                return Err(Error::WrongScope);
            }
            Ok(())
        }).await
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
