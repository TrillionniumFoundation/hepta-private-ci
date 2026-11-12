//! Exactly one resident continuation reaches these effect edges. Readiness
//! waits are reads; only an actual Ready is followed by Observer dispatch.

use std::time::Duration;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;

use super::Error;
use super::Origin;
use super::OriginalCellQ24NoUpdateStageOwnersV1;
use super::auth;
use super::state::Continuation;
use crate::OriginalCellQ24MaterialCommandClientV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCircuitCompletionReadinessClientV1;
use crate::OriginalCircuitNextUseCommandClientV1;
use crate::OriginalCircuitSelectionCommandClientV1;
use crate::RootResidentLearningEffectGateV3;

impl OriginalCellQ24NoUpdateStageOwnersV1 {
    pub(super) async fn execute_original_stage(
        &self, snapshot: &LearningIterationSnapshotV1, stage: Stage,
    ) -> Result<LearningIterationReceiptV1, Error> {
        let started_at = auth::now()?;
        auth::require_snapshot(&self.material, snapshot)?;
        if self.origin != Origin::Fresh
            || LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage() != Some(stage)
        {
            return Err(Error::WrongScope);
        }
        auth::stage_index(stage)?;
        let gate = self.root.as_ref().ok_or(Error::OwnerUnavailable("fresh resident continuation"))?;
        let before_readback = RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.material.scope).await;
        before_readback?;
        let mut state = self.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        if !snapshot.receipts.is_empty() {
            state.read_prefix(self, snapshot).await?;
        }
        match stage {
            Stage::Experience | Stage::Dataset => {}
            Stage::Training => state.ensure_trainer(self).await?,
            Stage::Selection => state.ensure_selector(self).await?,
            Stage::NextUse => {
                state.ensure_next_use(self).await?;
                state.ensure_readiness(self)?;
            }
            Stage::Evaluation | Stage::Proposal =>
                return Err(Error::OwnerUnavailable("original Candidate requires its separate route")),
        }
        let ready = if stage == Stage::NextUse {
            Some(self.await_completed_c(snapshot, &mut state).await?)
        } else {
            None
        };
        // These original reads may take time. Root's actual grant/registry
        // check therefore occurs again afterward, immediately before dispatch.
        let before_dispatch = RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.material.scope).await;
        before_dispatch?;
        let fresh = auth::require_material(&self.material, self.initial_binding)?;
        auth::require_clock(started_at, fresh)?;
        auth::verify_prefix(&self.material, snapshot, &state, fresh)?;
        let result = match stage {
            Stage::Experience => {
                let original = OriginalCellQ24MaterialCommandClientV1::execute(&state.experience)
                    .await.map_err(auth::material_failure);
                original.and_then(|value| {
                    state.record_material(self, &value)?;
                    Ok(value.receipt().clone())
                })
            }
            Stage::Dataset => {
                let original = OriginalCellQ24MaterialCommandClientV1::execute(&state.dataset)
                    .await.map_err(auth::material_failure);
                original.and_then(|value| {
                    state.record_material(self, &value)?;
                    Ok(value.receipt().clone())
                })
            }
            Stage::Training => {
                let trainer = state.trainer.as_ref().ok_or(Error::CommitUncertain)?;
                // The same resident continuation owns this cancellation flag.
                // Dropping or fencing it also cancels a queued local send; it
                // cannot undo a command already accepted by the original host.
                let dispatch = RootResidentLearningEffectGateV3::training_cancellation(gate);
                let original = OriginalCellQ24TrainingCommandClientV1::execute_training(trainer, dispatch)
                    .await.map_err(auth::trainer_failure);
                original.and_then(|value| {
                    state.record_training(self, &value)?;
                    Ok(value.receipt().clone())
                })
            }
            Stage::Selection => {
                let selector = state.selector.as_ref().ok_or(Error::CommitUncertain)?;
                let original = OriginalCircuitSelectionCommandClientV1::execute_selection(selector)
                    .await.map_err(auth::selector_failure);
                original.and_then(|value| {
                    state.record_selection(self, &value)?;
                    Ok(value.receipt().clone())
                })
            }
            Stage::NextUse => {
                let observer = state.next_use.as_ref().ok_or(Error::CommitUncertain)?;
                let original = OriginalCircuitNextUseCommandClientV1::attest_completed_task(observer)
                    .await.map_err(auth::next_use_failure);
                original.and_then(|value| {
                    if ready.as_ref() != Some(&value.receipt().observation) {
                        return Err(Error::CommitUncertain);
                    }
                    state.record_next_use(self, &value)?;
                    Ok(value.receipt().clone())
                })
            }
            Stage::Evaluation | Stage::Proposal =>
                Err(Error::OwnerUnavailable("original Candidate requires its separate route")),
        };
        // A post-effect loss of Root authority cannot be called NoEffect and
        // cannot reopen an execution bit. Preserve the operation as uncertain.
        let after_dispatch = RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.material.scope).await;
        if after_dispatch.is_err() {
            return Err(Error::CommitUncertain);
        }
        let fresh = auth::require_material(&self.material, self.initial_binding)?;
        auth::require_clock(started_at, fresh)?;
        auth::verify_prefix(&self.material, snapshot, &state, fresh)?;
        let receipt = result?;
        auth::require_receipt_position(snapshot, &receipt)?;
        let index = auth::stage_index(stage)?;
        let original = state.records.get(index).ok_or(Error::CommitUncertain)?;
        auth::verify_receipt(&self.material, &receipt, &original.1, fresh)?;
        Ok(receipt)
    }

    async fn await_completed_c(
        &self, snapshot: &LearningIterationSnapshotV1, state: &mut Continuation,
    ) -> Result<LearningIterationObservationV1, Error> {
        let gate = self.root.as_ref().ok_or(Error::OwnerUnavailable("fresh resident C wait"))?;
        for _ in 0..128 {
            RootResidentLearningEffectGateV3::require_current(gate, snapshot, &self.material.scope).await?;
            let readiness = state.readiness.as_ref().ok_or(Error::CommitUncertain)?;
            let current = OriginalCircuitCompletionReadinessClientV1::read_current(readiness)
                .await.map_err(|_| Error::OwnerUnavailable("original C readiness CURRENT"))?;
            if let Some(ready) = current {
                // Refresh every original predecessor after the wait. Keeping S
                // in memory never supplies a later Trainer/Selector CURRENT.
                state.read_prefix(self, snapshot).await?;
                return Ok(ready.observation().clone());
            }
            // The outer original admission Instant bounds this entire future.
            // Root cancellation drops it; no new session or dispatch is born.
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
        Err(Error::OwnerUnavailable("original C readiness frame budget"))
    }
}
