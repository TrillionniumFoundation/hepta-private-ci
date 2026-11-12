//! One borrowed historical operation owns the entire stage, including its
//! actual Root checkpoint. Nothing here can manufacture a source capability.

use super::*;
use crate::cell_composed_q24::OriginalPreparedReadV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationV1;
use crate::learning_iteration::historical_context::OriginalHistoricalStageAdmissionV1;
use crate::learning_iteration::historical_context::OriginalHistoricalStageContextV1;

#[path = "cell_q24_learning_historical_receipts.rs"]
mod receipts;

pub(crate) enum OriginalHistoricalRestoreModeV1 {
    Submit,
    Readback,
}

pub(crate) enum OriginalHistoricalWorkV1 {
    Restore(OriginalHistoricalRestoreModeV1),
    ConfirmRecovery(LearningIterationSnapshotV1),
    Stage {
        snapshot: LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    },
}

pub(crate) struct OriginalHistoricalResultV1 {
    pub(crate) snapshot: LearningIterationSnapshotV1,
    // This is only an authenticated, already-checkpointed prefix. It does not
    // validate the deferred C receipts or grant permission to execute them.
    pub(crate) generation_prefix: Option<LearningIterationSnapshotV1>,
}

pub(super) struct OriginalQ24StageOperationV1<'frame, 'owners, 'read, 'source> {
    inner: &'frame Q24StageState,
    owners: &'frame mut Q24StageOwners,
    runtime: &'frame Handle,
    training: &'frame mut OriginalQ24TrainingOperationV1<
        'owners,
        'read,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    >,
    read: &'source OriginalPreparedReadV1<'source>,
    context: &'frame OriginalHistoricalStageContextV1,
}

impl<'frame, 'owners, 'read, 'source> OriginalQ24StageOperationV1<'frame, 'owners, 'read, 'source> {
    pub(super) fn from_original(
        inner: &'frame Q24StageState,
        owners: &'frame mut Q24StageOwners,
        runtime: &'frame Handle,
        training: &'frame mut OriginalQ24TrainingOperationV1<
            'owners,
            'read,
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        >,
        read: &'source OriginalPreparedReadV1<'source>,
        context: &'frame OriginalHistoricalStageContextV1,
    ) -> Result<Self, Error> {
        OriginalPreparedReadV1::require_prepared(read, &inner.prepared).map_err(unavailable)?;
        context.require_in_operation(read, OriginalHistoricalStageAdmissionV1::ReadOnly)?;
        Ok(Self {
            inner,
            owners,
            runtime,
            training,
            read,
            context,
        })
    }
}

impl OriginalQ24StageOperationV1<'_, '_, '_, '_> {
    pub(super) fn run(
        &mut self,
        work: OriginalHistoricalWorkV1,
    ) -> Result<OriginalHistoricalResultV1, Error> {
        match work {
            OriginalHistoricalWorkV1::Restore(mode) => self.restore(mode),
            OriginalHistoricalWorkV1::ConfirmRecovery(expected) => {
                let actual = self.runtime.block_on(
                    self.context
                        .restore_checkpoint(&self.inner.prepared.initial().request),
                )?;
                if actual.as_ref() != Some(&expected) {
                    return Err(Error::CommitUncertain);
                }
                self.inner.require_snapshot(&expected)?;
                for receipt in &expected.receipts {
                    self.authenticate_receipt(&expected, receipt)?;
                }
                Ok(OriginalHistoricalResultV1 {
                    snapshot: expected,
                    generation_prefix: None,
                })
            }
            OriginalHistoricalWorkV1::Stage { snapshot, stage } => self.execute(snapshot, stage),
        }
    }

    fn restore(
        &mut self,
        mode: OriginalHistoricalRestoreModeV1,
    ) -> Result<OriginalHistoricalResultV1, Error> {
        let initial = self.inner.prepared.initial();
        let restored = self
            .runtime
            .block_on(self.context.restore_checkpoint(&initial.request))?;
        let Some(snapshot) = restored else {
            if matches!(mode, OriginalHistoricalRestoreModeV1::Readback) {
                return Err(Error::CommitUncertain);
            }
            self.context
                .require_in_operation(self.read, OriginalHistoricalStageAdmissionV1::NewWork)?;
            let committed = self.runtime.block_on(
                self.context
                    .commit_checkpoint(codex_hepta_types::Digest32::ZERO, initial),
            )?;
            if committed != initial.head_digest {
                return Err(Error::CommitUncertain);
            }
            return Ok(OriginalHistoricalResultV1 {
                snapshot: initial.clone(),
                generation_prefix: None,
            });
        };
        self.inner.require_snapshot(&snapshot)?;
        let mut prefix = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        for receipt in &snapshot.receipts {
            if self.owners.generation.is_none() && generation_receipt(receipt) {
                // No owner lane is held across the later C wait. The runtime
                // must confirm this exact original Root cut and verify every
                // deferred original receipt after actual Generation install.
                return Ok(OriginalHistoricalResultV1 {
                    snapshot: snapshot.clone(),
                    generation_prefix: Some(prefix.snapshot().clone()),
                });
            }
            self.authenticate_receipt(&snapshot, receipt)?;
            prefix.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        Ok(OriginalHistoricalResultV1 {
            snapshot,
            generation_prefix: None,
        })
    }

    fn execute(
        &mut self,
        snapshot: LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> Result<OriginalHistoricalResultV1, Error> {
        self.inner.require_snapshot(&snapshot)?;
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot)?;
        if coordinator.next_stage() != Some(stage) {
            return Err(Error::WrongScope);
        }
        self.context
            .require_in_operation(self.read, OriginalHistoricalStageAdmissionV1::NewWork)?;
        if let Some(decision) = coordinator.snapshot().receipts.iter().find(|receipt| {
            matches!(
                receipt.observation,
                LearningIterationObservationV1::LocalDecisionV2(_)
            )
        }) {
            self.authenticate_receipt(coordinator.snapshot(), decision)?;
        }
        let receipt = self.execute_stage(coordinator.snapshot(), stage)?;
        self.authenticate_receipt(coordinator.snapshot(), &receipt)?;
        self.context
            .require_in_operation(self.read, OriginalHistoricalStageAdmissionV1::NewWork)?;
        self.inner
            .prepared
            .scope()
            .validate_observation(&receipt.observation)?;
        let previous = coordinator.snapshot().head_digest;
        coordinator.record(receipt, self.context.current_time()?)?;
        let committed = self.runtime.block_on(
            self.context
                .commit_checkpoint(previous, coordinator.snapshot()),
        )?;
        if committed != coordinator.snapshot().head_digest {
            return Err(Error::CommitUncertain);
        }
        self.context
            .require_in_operation(self.read, OriginalHistoricalStageAdmissionV1::NewWork)
            .map_err(|_| Error::CommitUncertain)?;
        Ok(OriginalHistoricalResultV1 {
            snapshot: coordinator.snapshot().clone(),
            generation_prefix: None,
        })
    }

    fn execute_stage(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> Result<LearningIterationReceiptV1, Error> {
        match stage {
            LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset => {
                Ok(self.source_receipt(stage)?.0)
            }
            LearningIterationStageV1::Training => {
                if snapshot != &self.inner.dataset_cut {
                    return Err(Error::WrongScope);
                }
                Ok(self
                    .training
                    .execute_original_training(&self.inner.cancelled)?
                    .receipt)
            }
            LearningIterationStageV1::Evaluation => {
                let original =
                    OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
                if original.snapshot() != snapshot {
                    return Err(Error::WrongScope);
                }
                Ok(self
                    .owners
                    .complete_original_root_evaluation(
                        &original,
                        self.inner.prepared.scope(),
                        OriginalRootBEvaluationActionV1::Complete,
                    )?
                    .receipt()
                    .clone())
            }
            LearningIterationStageV1::Proposal => Ok(self
                .owners
                .model_root_action_in_operation(
                    self.inner,
                    self.runtime,
                    self.training,
                    snapshot,
                    model::Action::CommitProposal,
                )?
                .0),
            LearningIterationStageV1::Selection
                if snapshot.receipts.last().is_some_and(|receipt| {
                    receipt.observation.stage() == LearningIterationStageV1::Proposal
                }) =>
            {
                Ok(self
                    .owners
                    .model_root_action_in_operation(
                        self.inner,
                        self.runtime,
                        self.training,
                        snapshot,
                        model::Action::CommitDecision,
                    )?
                    .0)
            }
            LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse => {
                let (selection, next_use) = self
                    .owners
                    .generation
                    .as_mut()
                    .ok_or(Error::OwnerUnavailable("original C handoff"))?;
                let original: &mut OriginalGenerationLearningReceiptOwnerV1<
                    FileAnchorWitnessStore,
                > = if stage == LearningIterationStageV1::Selection {
                    selection
                } else {
                    next_use
                };
                self.runtime
                    .block_on(original.attest_original_completion(snapshot))
                    .map(|value| value.0)
                    .map_err(unavailable)
            }
        }
    }
}

fn generation_receipt(receipt: &LearningIterationReceiptV1) -> bool {
    receipt.observation.stage() == LearningIterationStageV1::NextUse
        || (receipt.observation.stage() == LearningIterationStageV1::Selection
            && !matches!(
                receipt.observation,
                LearningIterationObservationV1::LocalDecisionV2(_)
            ))
}
