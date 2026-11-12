//! Bind the actual Learning work once, before any post-A assembly effect.

use super::*;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

impl SameActorTaskRoute {
    pub(super) fn original_learning_work(
        &self,
    ) -> Result<Arc<OriginalSameActorLearningWork>, AgentdError> {
        let work = self
            .learning_work
            .get()
            .ok_or_else(poisoned_route)?
            .lock()
            .map_err(|_| poisoned_route())?
            .as_ref()
            .cloned()
            .ok_or_else(poisoned_route)?;
        work.require_identity_and_gate(&self.identity, &self.gate)?;
        Ok(work)
    }

    pub(crate) fn attach_original_learning_work(
        &self,
        work: Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        let result = (|| {
            work.require_identity_and_gate(&self.identity, &self.gate)?;
            let state = self.state.lock().map_err(|_| poisoned_route())?;
            self.gate.require_open().map_err(phase_error)?;
            if state.closed
                || !matches!(state.phase, Phase::AwaitingC)
                || state.tickets != 0
                || self.learning_work.get().is_some()
            {
                return Err(AgentdError::GenerationFenced(
                    "original learning work requires the once-only post-A task phase".into(),
                ));
            }
            self.learning_work.set(Mutex::new(Some(work))).map_err(|_| {
                AgentdError::GenerationFenced("original learning work was already attached".into())
            })?;
            Ok(())
        })();
        if result.is_err() {
            self.close();
        }
        result
    }
}
