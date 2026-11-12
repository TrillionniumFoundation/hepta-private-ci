//! One exact Training checkpoint waiting for actual independent B installation.
//! Notifications carry data only; the original aggregate supplies all owners.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;

use super::*;
use crate::OriginalCellQ24TrainingReadbackV1;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Installation {
    Awaiting,
    Installing,
    Installed,
}

struct EvaluationState {
    training: Option<LearningIterationSnapshotV1>,
    installation: Installation,
}

pub(super) struct OriginalEvaluationExchange {
    gate: Arc<SameActorPhaseGate>,
    state: Mutex<EvaluationState>,
    changed: Notify,
}

/// A once-only installation waiter retains the exact exchange and common
/// failure guard. Dropping it never reopens the original Training cut.
pub(crate) struct OriginalEvaluationInstallation<'a> {
    original: &'a OriginalEvaluationExchange,
    training: LearningIterationSnapshotV1,
    closing: CloseSameActorPhaseOnDrop,
}

impl OriginalSameActorLearningWork {
    /// This is a read-only progress observation. Cancelling it when the
    /// original NoUpdate decision arrives does not cancel the whole phase.
    pub(crate) async fn original_training_snapshot(
        &self,
    ) -> Result<LearningIterationSnapshotV1, Error> {
        self.require_original_work_entry()?;
        self.evaluation.training_snapshot().await
    }

    pub(crate) async fn wait_original_evaluation_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        original: &OriginalCellQ24TrainingReadbackV1,
    ) -> Result<(), Error> {
        let mut closing = self.original_failure_scope();
        self.require_training_context(snapshot, self.prepared.scope())?;
        OriginalCellQ24TrainingReadbackV1::require_training(
            original,
            snapshot,
            self.prepared.scope(),
        )?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation) {
            return Err(Error::WrongScope);
        }
        self.evaluation.announce_original_training(snapshot)?;
        self.evaluation.wait_installed(snapshot).await?;
        self.require_original_work_entry()?;
        closing.disarm();
        Ok(())
    }

    pub(crate) fn begin_original_evaluation_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalEvaluationInstallation<'_>, Error> {
        self.require_training_context(snapshot, self.prepared.scope())?;
        self.evaluation.begin_installation(snapshot)
    }

    /// Called inside the original owner lane, immediately before its first
    /// file effect and after its asynchronous original evidence check.
    pub(crate) fn require_original_evaluation_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        self.require_training_context(snapshot, self.prepared.scope())?;
        self.evaluation.require_installing(snapshot)
    }

    /// The sole product caller first awaits the real aggregate installation.
    /// Its owner lane has been released before this notification can occur.
    pub(crate) fn complete_original_evaluation_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        installation: OriginalEvaluationInstallation<'_>,
    ) -> Result<(), Error> {
        self.require_training_context(snapshot, self.prepared.scope())?;
        self.evaluation
            .complete_installation(snapshot, installation)
    }
}

impl OriginalEvaluationExchange {
    pub(super) fn new(gate: Arc<SameActorPhaseGate>) -> Self {
        Self {
            gate,
            state: Mutex::new(EvaluationState {
                training: None,
                installation: Installation::Awaiting,
            }),
            changed: Notify::new(),
        }
    }

    fn require_entry(&self, snapshot: &LearningIterationSnapshotV1) -> Result<(), Error> {
        self.gate
            .require_open()
            .map_err(|_| Error::CommitUncertain)?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| {
                self.gate.close();
                Error::OwnerUnavailable("clock")
            })?
            .as_secs();
        if now >= snapshot.request.envelope.expiry_unix_seconds {
            self.gate.close();
            return Err(Error::DeadlineExceeded);
        }
        Ok(())
    }

    fn locked(&self) -> Result<MutexGuard<'_, EvaluationState>, Error> {
        self.state.lock().map_err(|_| {
            self.gate.close();
            Error::CommitUncertain
        })
    }

    fn announce_original_training(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        self.require_entry(snapshot)?;
        let mut state = self.locked()?;
        self.require_entry(snapshot)?;
        match &state.training {
            None => state.training = Some(snapshot.clone()),
            Some(retained) if retained == snapshot => {}
            Some(_) => {
                self.gate.close();
                return Err(Error::WrongScope);
            }
        }
        drop(state);
        self.changed.notify_waiters();
        Ok(())
    }

    async fn training_snapshot(&self) -> Result<LearningIterationSnapshotV1, Error> {
        loop {
            self.gate
                .require_open()
                .map_err(|_| Error::CommitUncertain)?;
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let snapshot = self.locked()?.training.clone();
            if let Some(snapshot) = snapshot {
                self.require_entry(&snapshot)?;
                return Ok(snapshot);
            }
            tokio::select! {
                _ = self.gate.cancelled() => return Err(Error::CommitUncertain),
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    self.gate.deadline().instant(),
                )) => {
                    self.gate.close();
                    return Err(Error::CommitUncertain);
                }
                _ = &mut notified => {}
            }
        }
    }

    fn begin_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<OriginalEvaluationInstallation<'_>, Error> {
        let closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_entry(snapshot)?;
        let mut state = self.locked()?;
        self.require_entry(snapshot)?;
        if state.training.as_ref() != Some(snapshot) || state.installation != Installation::Awaiting
        {
            return Err(Error::WrongScope);
        }
        state.installation = Installation::Installing;
        drop(state);
        Ok(OriginalEvaluationInstallation {
            original: self,
            training: snapshot.clone(),
            closing,
        })
    }

    fn require_installing(&self, snapshot: &LearningIterationSnapshotV1) -> Result<(), Error> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_entry(snapshot)?;
        let state = self.locked()?;
        self.require_entry(snapshot)?;
        if state.training.as_ref() != Some(snapshot)
            || state.installation != Installation::Installing
        {
            return Err(Error::WrongScope);
        }
        drop(state);
        closing.disarm();
        Ok(())
    }

    fn complete_installation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        mut installation: OriginalEvaluationInstallation<'_>,
    ) -> Result<(), Error> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.require_entry(snapshot)?;
        if !std::ptr::eq(self, installation.original) || &installation.training != snapshot {
            return Err(Error::WrongScope);
        }
        let mut state = self.locked()?;
        self.require_entry(snapshot)?;
        if state.training.as_ref() != Some(snapshot)
            || state.installation != Installation::Installing
        {
            return Err(Error::WrongScope);
        }
        state.installation = Installation::Installed;
        drop(state);
        self.changed.notify_waiters();
        installation.closing.disarm();
        closing.disarm();
        Ok(())
    }

    async fn wait_installed(&self, snapshot: &LearningIterationSnapshotV1) -> Result<(), Error> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        loop {
            self.require_entry(snapshot)?;
            let notified = self.changed.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            let installed = {
                let state = self.locked()?;
                if state.training.as_ref() != Some(snapshot) {
                    return Err(Error::WrongScope);
                }
                state.installation == Installation::Installed
            };
            if installed {
                self.require_entry(snapshot)?;
                closing.disarm();
                return Ok(());
            }
            tokio::select! {
                _ = self.gate.cancelled() => return Err(Error::CommitUncertain),
                _ = tokio::time::sleep_until(tokio::time::Instant::from_std(
                    self.gate.deadline().instant(),
                )) => return Err(Error::CommitUncertain),
                _ = &mut notified => {}
            }
        }
    }
}

#[cfg(test)]
#[path = "same_actor_q24_phase_learning_evaluation_tests.rs"]
mod tests;
