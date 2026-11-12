//! The original Training cut enters a bounded independent-B installation wait.
//! No aggregate lane is retained while the host supplies its actual B owners.

use super::*;
use crate::OriginalCellQ24EvaluationInputsV1;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(crate) async fn wait_original_same_actor_evaluation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<bool, Error> {
        let Some(phase) = &self.inner.same_actor_work else {
            return Ok(false);
        };
        let mut closing = phase.original_failure_scope();
        OriginalCellQ24LearningStageOwnersV1::require_original_same_actor_work(self, phase)?;
        self.inner.require_snapshot(snapshot)?;
        // This reads the original native Trainer under the original lane.
        // The await has returned and released that lane before publication of
        // this progress notification or any wait for independent B inputs.
        let original: OriginalCellQ24TrainingReadbackV1 =
            OriginalCellQ24LearningStageOwnersV1::original_training_readback(
                self,
                snapshot.clone(),
            )
            .await?;
        OriginalSameActorLearningWork::wait_original_evaluation_installation(
            phase,
            snapshot,
            &original,
        )
        .await?;
        closing.disarm();
        Ok(true)
    }

    pub(crate) async fn install_original_same_actor_evaluation(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        original: OriginalCellQ24EvaluationInputsV1,
    ) -> Result<(), Error> {
        let phase = self.inner.same_actor_work.as_ref().ok_or(Error::WrongScope)?;
        let mut closing = phase.original_failure_scope();
        OriginalCellQ24LearningStageOwnersV1::require_original_same_actor_work(self, phase)?;
        self.inner.require_snapshot(snapshot)?;
        let installation =
            OriginalSameActorLearningWork::begin_original_evaluation_installation(phase, snapshot)?;
        OriginalCellQ24LearningStageOwnersV1::install_independent_evaluation(self, original).await?;
        // Installation retains the actual supplied inputs. The original
        // Evaluation complete path must still validate its independent roles,
        // signed evidence, holdout and complete costs before any B receipt.
        OriginalSameActorLearningWork::complete_original_evaluation_installation(
            phase,
            snapshot,
            installation,
        )?;
        closing.disarm();
        Ok(())
    }
}
