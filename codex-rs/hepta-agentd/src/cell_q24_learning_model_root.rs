//! Model and Selector work on one already-held original Trainer operation.
//! Only Root's actual B observation crosses the boundary; native qualification
//! remains in the same Root custodian used by the original Model factory.

use super::*;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationV1;

impl Q24StageOwners {
    pub(super) fn model_root_action_in_operation(
        &mut self,
        inner: &Q24StageState,
        runtime: &Handle,
        original: &mut OriginalQ24TrainingOperationV1<
            '_,
            '_,
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        >,
        snapshot: &LearningIterationSnapshotV1,
        action: model::Action,
    ) -> Result<(LearningIterationReceiptV1, Option<SignedLearningEvidenceV1>), Error> {
        inner.require_snapshot(snapshot)?;
        let evidence = OriginalQ24TrainingOperationV1::read_original_training_evidence(original)?;
        if !snapshot.receipts.starts_with(&evidence.snapshot().receipts) {
            return Err(Error::WrongScope);
        }
        let before = self.complete_original_root_evaluation(
            &evidence,
            inner.prepared.scope(),
            OriginalRootBEvaluationActionV1::Readback,
        )?;
        if snapshot.receipts.get(evidence.snapshot().receipts.len()) != Some(before.receipt()) {
            return Err(Error::WrongScope);
        }
        let Self { factory, local, .. } = self;
        let factory: &mut AgentdRootQ24ModelFactoryV1 = factory;
        let local: &mut OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore> = local;
        let result = match action {
            model::Action::CommitProposal => runtime
                .block_on(factory.commit_from_original_b(&evidence, &before))
                .map(|value| (value.learning_receipt().clone(), None))
                .map_err(unavailable),
            model::Action::ReadProposal => runtime
                .block_on(factory.read_from_original_b(&evidence, &before))
                .map(|value| (value.learning_receipt().clone(), None))
                .map_err(unavailable),
            model::Action::CommitDecision => runtime
                .block_on(
                    local.attest_original_root_decision(factory, &evidence, &before, snapshot),
                )
                .map(|(receipt, signed)| (receipt, Some(signed)))
                .map_err(unavailable),
            model::Action::ReadDecision => runtime
                .block_on(local.read_original_root_decision(factory, &evidence, &before, snapshot))
                .map(|(receipt, signed)| (receipt, Some(signed)))
                .map_err(unavailable),
        };
        let after = self.complete_original_root_evaluation(
            &evidence,
            inner.prepared.scope(),
            OriginalRootBEvaluationActionV1::Readback,
        )?;
        if !before.same_original_observation(&after) {
            return Err(Error::CommitUncertain);
        }
        result
    }

    pub(super) fn original_root_model_action(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        runtime: &Handle,
        snapshot: &LearningIterationSnapshotV1,
        action: model::Action,
    ) -> Result<(LearningIterationReceiptV1, Option<SignedLearningEvidenceV1>), Error> {
        CellQ24PreparedLearningV1::with_original_prepared_operation(&inner.prepared, |read| {
            training.with_original_training_operation(&inner.dataset_cut, read, |original| {
                self.model_root_action_in_operation(inner, runtime, original, snapshot, action)
            })
        })
        .map_err(unavailable)?
    }
}
