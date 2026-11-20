//! The actual ordinary historical route. Generic stage ports retain their
//! original behavior; only the same Root/Q24 assembly can select this executor.

use super::historical_context::OriginalHistoricalStageContextV1;
use super::*;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::cell_q24_learning_stage_owners::OriginalHistoricalRestoreModeV1;
use crate::cell_q24_learning_stage_owners::OriginalHistoricalWorkV1;

impl LearningIterationRuntimeBootstrapV1 {
    // This is only the direct predecessor of a real historical Stage operation.
    // Recovery keeps the original complete wait and separate ConfirmRecovery.
    async fn wait_original_historical_successor_stage(
        &self,
        state: &AgentdState,
        snapshot: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        let Some(slot) = &self.successor else {
            return Ok(());
        };
        if !super::historical_context::original_stage_needs_successor(snapshot, stage) {
            return Ok(());
        }
        // A Ready hint only selects scheduling. The actual Stage operation
        // below revalidates the same registered slot and all admissions before
        // and after its effect; no Source observation survives this branch.
        if stage == LearningIterationStageV1::NextUse && slot.original_generation_ready_hint() {
            self.require_frozen_scope(&snapshot.request)?;
            return Ok(());
        }
        self.require_stage_admission(state)?;
        self.require_frozen_scope(&snapshot.request)?;
        // Keep the original pre-wait authorization and bounded, cancellable
        // wait. Its post-wait admission is performed by the immediately
        // following real Stage operation, under a fresh physical Source pair.
        slot.wait_original_generation(snapshot).await
    }

    pub(super) async fn process_original_historical(
        &self,
        state: Arc<AgentdState>,
        request: LearningIterationRequestV1,
        mode: LearningIterationModeV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        let context =
            OriginalHistoricalStageContextV1::from_original_bootstrap(self, Arc::clone(&state))?;
        let original: &Arc<OriginalCellQ24LearningStageOwnersV1> = self
            .original_q24
            .as_ref()
            .ok_or(LearningIterationRuntimeErrorV1::WrongScope)?;
        if request != original.prepared().initial().request {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        let restore = match &mode {
            LearningIterationModeV1::Submit => OriginalHistoricalRestoreModeV1::Submit,
            LearningIterationModeV1::Readback => OriginalHistoricalRestoreModeV1::Readback,
        };
        let mut current = original
            .run_original_historical_stage(
                Arc::clone(&context),
                OriginalHistoricalWorkV1::Restore(restore),
            )
            .await?;
        if let Some(prefix) = current.generation_prefix.take() {
            if self.successor.is_none() {
                return Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                    "original C recovery handoff",
                ));
            }
            let next = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?
                .next_stage()
                .ok_or(LearningIterationRuntimeErrorV1::WrongScope)?;
            // Only the actual Root-restored and authenticated prefix reaches
            // the original C slot. No owner lane is held across this wait.
            self.wait_original_successor_stage(&state, &prefix, next)
                .await?;
            current = original
                .run_original_historical_stage(
                    Arc::clone(&context),
                    OriginalHistoricalWorkV1::ConfirmRecovery(current.snapshot),
                )
                .await?;
        }
        if matches!(mode, LearningIterationModeV1::Readback) {
            return Ok(current.snapshot);
        }
        loop {
            let Some(stage) =
                LearningIterationCoordinatorV1::from_snapshot(current.snapshot.clone())?
                    .next_stage()
            else {
                return Ok(current.snapshot);
            };
            self.wait_original_historical_successor_stage(&state, &current.snapshot, stage)
                .await?;
            let operation = original.run_original_historical_stage(
                Arc::clone(&context),
                OriginalHistoricalWorkV1::Stage {
                    snapshot: current.snapshot,
                    stage,
                },
            );
            current = if stage == LearningIterationStageV1::Training {
                tokio::time::timeout(
                    Duration::from_millis(request.budget.maximum_training_milliseconds),
                    operation,
                )
                .await
                .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)??
            } else {
                operation.await?
            };
        }
    }
}
