use std::sync::Arc;
use std::sync::atomic::Ordering;

use crate::state::TaskTerminalizationKind;
use codex_features::Feature;

use super::session::Session;

impl Session {
    /// Captures a recovery token only for the exact idle model-turn candidate.
    pub(crate) async fn recovery_epoch_if_idle(&self, turn_id: &str) -> Option<u64> {
        if !self.enabled(Feature::HeptaTurnRecovery)
            || self.shutdown_started()
            || self.has_pending_task_terminalization()
        {
            return None;
        }
        let active_turn = self.active_turn.lock().await;
        if active_turn.is_some() {
            return None;
        }
        let epoch = self.turn_epoch.load(Ordering::Acquire);
        let persistence_failure_generation = self.rollout_persistence_failure_generation();
        self.recovery_candidate
            .lock()
            .unwrap_or_else(|error| panic!("recovery candidate mutex poisoned: {error:?}"))
            .as_ref()
            .filter(|candidate| {
                candidate.turn_id == turn_id
                    && candidate.epoch == epoch
                    && candidate.persistence_failure_generation == persistence_failure_generation
            })
            .map(|candidate| candidate.epoch)
    }

    /// Waits for the current task's terminalizer before observing recovery authority.
    ///
    /// TurnAborted is emitted before recovery publication and owner retirement.
    /// Snapshot the exact completion and epoch under the active-turn lock so a
    /// request in that interval cannot wait for, or recover, a later attempt
    /// that happens to reuse the interrupted turn ID. This never waits for a
    /// running task, start reservation, or suspension owner.
    pub(crate) async fn recovery_epoch_after_terminalization(&self, turn_id: &str) -> Option<u64> {
        if !self.enabled(Feature::HeptaTurnRecovery) || self.shutdown_started() {
            return None;
        }
        let (observed_epoch, completion) = {
            let active_turn = self.active_turn.lock().await;
            if self.shutdown_started() || self.has_pending_start_transition() {
                return None;
            }
            let epoch = self.turn_epoch.load(Ordering::Acquire);
            let registry = self
                .pending_task_terminalization_completions
                .lock()
                .unwrap_or_else(|error| {
                    panic!("task terminalization completion registry mutex poisoned: {error:?}")
                });
            let completion = if let Some(turn) = active_turn.as_ref() {
                let owner = turn.task_terminalization.as_ref()?;
                if turn.task.is_some()
                    || turn.start_reservation.is_some()
                    || turn.start_transition.is_some()
                    || owner.turn_context.sub_id != turn_id
                    || owner.attach_epoch != epoch
                    || !matches!(
                        owner.kind,
                        TaskTerminalizationKind::Finish | TaskTerminalizationKind::Abort
                    )
                {
                    return None;
                }
                Some(
                    registry
                        .iter()
                        .find(|(identity, completion, kind, _, _, _, owner_turn_id)| {
                            Arc::ptr_eq(identity, &owner.identity)
                                && Arc::ptr_eq(completion, &owner.completion)
                                && *kind == owner.kind
                                && owner_turn_id == turn_id
                        })
                        .map(|(_, completion, _, _, _, _, _)| Arc::clone(completion))?,
                )
            } else {
                // The active slot can be clear while this epoch's recovery
                // publication still owns its registry fence. Snapshot that
                // completion and epoch together; any subsequent owner-admitted
                // pending task changes the epoch and invalidates this observer.
                // Reject ambiguous owners rather than choosing by turn ID.
                match registry.as_slice() {
                    [] => None,
                    [(_, completion, kind, _, _, _, owner_turn_id)]
                        if owner_turn_id == turn_id
                            && matches!(
                                *kind,
                                TaskTerminalizationKind::Finish | TaskTerminalizationKind::Abort
                            ) =>
                    {
                        Some(Arc::clone(completion))
                    }
                    _ => return None,
                }
            };
            (epoch, completion)
        };

        if let Some(completion) = completion {
            completion.wait().await;
        }
        if self.has_pending_admission_fence() {
            return None;
        }
        self.recovery_epoch_if_idle(turn_id)
            .await
            .filter(|epoch| *epoch == observed_epoch)
    }
}
