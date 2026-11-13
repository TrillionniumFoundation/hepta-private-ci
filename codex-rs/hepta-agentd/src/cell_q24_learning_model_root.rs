//! Model and Selector work on one already-held original Trainer operation.
//! Only Root's actual B observation crosses the boundary; native qualification
//! remains in the same Root custodian used by the original Model factory.

use super::*;
use crate::OriginalRootIndependentBEvaluationReadbackV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;
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
        let result = self.model_root_action_from_original_b(
            inner, runtime, &evidence, &before, snapshot, action,
        );
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

    /// Borrow the original B observation already enclosed by its caller's
    /// actual Root before/after reads. Model and Selector still enter their
    /// original Root custody and verify the native execution independently.
    pub(super) fn model_root_action_from_original_b(
        &mut self,
        inner: &Q24StageState,
        runtime: &Handle,
        evidence: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        observed: &OriginalRootIndependentBEvaluationReadbackV1,
        snapshot: &LearningIterationSnapshotV1,
        action: model::Action,
    ) -> Result<(LearningIterationReceiptV1, Option<SignedLearningEvidenceV1>), Error> {
        inner.require_snapshot(snapshot)?;
        evidence.require_current_training_source()?;
        if !snapshot.receipts.starts_with(&evidence.snapshot().receipts)
            || snapshot.receipts.get(evidence.snapshot().receipts.len()) != Some(observed.receipt())
        {
            return Err(Error::WrongScope);
        }
        let Self { factory, local, .. } = self;
        let factory: &mut AgentdRootQ24ModelFactoryV1 = factory;
        let local: &mut OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore> = local;
        let result = match action {
            model::Action::CommitProposal => runtime
                .block_on(factory.commit_from_original_b(evidence, observed))
                .map(|value| (value.learning_receipt().clone(), None))
                .map_err(unavailable),
            model::Action::ReadProposal => runtime
                .block_on(factory.read_from_original_b(evidence, observed))
                .map(|value| (value.learning_receipt().clone(), None))
                .map_err(unavailable),
            model::Action::CommitDecision => runtime
                .block_on(
                    local.attest_original_root_decision(factory, evidence, observed, snapshot),
                )
                .map(|(receipt, signed)| (receipt, Some(signed)))
                .map_err(unavailable),
            model::Action::ReadDecision => runtime
                .block_on(local.read_original_root_decision(factory, evidence, observed, snapshot))
                .map(|(receipt, signed)| (receipt, Some(signed)))
                .map_err(unavailable),
        };
        evidence.require_current_training_source()?;
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
