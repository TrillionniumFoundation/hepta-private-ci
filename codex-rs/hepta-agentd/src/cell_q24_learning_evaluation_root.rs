//! The original aggregate retains only B's opaque Root reader. The historical
//! executor calls the synchronous entry with its already held Trainer borrow;
//! the generic adapter opens that same real source operation explicitly.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;

use super::*;
use crate::OriginalRootIndependentBEvaluationClientV1;
use crate::OriginalRootIndependentBEvaluationReadbackV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationV1;

pub(super) enum OriginalRootBEvaluationActionV1 {
    Complete,
    Readback,
}

impl OriginalCellQ24LearningStageOwnersV1 {
    /// Install before iteration starts. A route can only originate in the
    /// actual original Root session; this never creates B owners or executes B.
    pub(crate) async fn install_root_independent_evaluation(
        &self,
        original: Arc<OriginalRootIndependentBEvaluationClientV1>,
    ) -> Result<(), Error> {
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(move |owners, _, _| {
                if owners.evaluation.is_some() || owners.root_evaluation.is_some() {
                    return Err(Error::WrongScope);
                }
                original.require_initial(inner.prepared.initial(), inner.prepared.scope())?;
                owners.root_evaluation = Some(original);
                Ok(())
            })
            .await
    }
}

impl Q24StageOwners {
    /// This entry never enters another Prepared/Trainer operation. Its caller
    /// already holds both original capabilities for the complete stage.
    pub(super) fn complete_original_root_evaluation(
        &mut self,
        evidence: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
        action: OriginalRootBEvaluationActionV1,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        if self.evaluation.is_some() {
            return Err(Error::WrongScope);
        }
        let original: &OriginalRootIndependentBEvaluationClientV1 = self
            .root_evaluation
            .as_deref()
            .ok_or(Error::OwnerUnavailable("original Root B handoff"))?;
        match action {
            OriginalRootBEvaluationActionV1::Complete => Err(Error::WrongScope),
            OriginalRootBEvaluationActionV1::Readback => {
                original.read_from_original_training(evidence, scope)
            }
        }
    }

    /// First execution needs the same live original Generator operation. A
    /// readonly evidence borrow alone cannot sign the newly realized B plan.
    pub(super) fn execute_original_root_evaluation(
        &mut self,
        operation: &mut OriginalQ24TrainingOperationV1<
            '_,
            '_,
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        >,
        evidence: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        if self.evaluation.is_some() {
            return Err(Error::WrongScope);
        }
        let original: &OriginalRootIndependentBEvaluationClientV1 = self
            .root_evaluation
            .as_deref()
            .ok_or(Error::OwnerUnavailable("original Root B handoff"))?;
        original.complete_from_original_training(evidence, scope, |challenge| {
            OriginalQ24TrainingOperationV1::attest_original_root_b_plan(operation, challenge)
        })
    }

    pub(super) fn original_root_evaluation_action(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        snapshot: &LearningIterationSnapshotV1,
        action: OriginalRootBEvaluationActionV1,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        inner.require_snapshot(snapshot)?;
        CellQ24PreparedLearningV1::with_original_prepared_operation(&inner.prepared, |read| {
            training.with_original_training_operation(&inner.dataset_cut, read, |original| {
                let evidence =
                    OriginalQ24TrainingOperationV1::read_original_training_evidence(original)?;
                let training_cut = evidence.snapshot();
                if !snapshot.receipts.starts_with(&training_cut.receipts)
                    || (matches!(action, OriginalRootBEvaluationActionV1::Complete)
                        && snapshot != training_cut)
                {
                    return Err(Error::WrongScope);
                }
                let observed = match action {
                    OriginalRootBEvaluationActionV1::Complete => self
                        .execute_original_root_evaluation(
                            original,
                            &evidence,
                            inner.prepared.scope(),
                        ),
                    OriginalRootBEvaluationActionV1::Readback => self
                        .complete_original_root_evaluation(
                            &evidence,
                            inner.prepared.scope(),
                            OriginalRootBEvaluationActionV1::Readback,
                        ),
                }?;
                if snapshot
                    .receipts
                    .get(training_cut.receipts.len())
                    .is_some_and(|retained| retained != observed.receipt())
                {
                    return Err(Error::WrongScope);
                }
                Ok(observed)
            })
        })
        .map_err(unavailable)?
    }

    pub(super) fn evaluation_receipt(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        runtime: &Handle,
        snapshot: &LearningIterationSnapshotV1,
        action: OriginalRootBEvaluationActionV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        if self.root_evaluation.is_some() {
            let observed =
                self.original_root_evaluation_action(inner, training, snapshot, action)?;
            return Ok((observed.receipt().clone(), observed.attestation().clone()));
        }
        let evaluation: &mut OriginalCellQ24EvaluationStageV1 = self
            .evaluation
            .as_mut()
            .ok_or(Error::OwnerUnavailable("original B handoff"))?;
        match action {
            OriginalRootBEvaluationActionV1::Complete => {
                runtime.block_on(evaluation.complete(snapshot, /*read_only*/ false))
            }
            OriginalRootBEvaluationActionV1::Readback => {
                runtime.block_on(evaluation.complete(snapshot, /*read_only*/ true))
            }
        }
    }

    pub(super) fn original_evaluation_manifest(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<codex_hepta_neuron::CellBackendManifestV2, Error> {
        if self.root_evaluation.is_some() {
            // The actual Root re-reads the native execution, physical files and
            // learning checkpoint before releasing this opaque observation.
            let observed = self.original_root_evaluation_action(
                inner,
                training,
                snapshot,
                OriginalRootBEvaluationActionV1::Readback,
            )?;
            return Ok(observed.manifest().clone());
        }
        let evaluation: &mut OriginalCellQ24EvaluationStageV1 = self
            .evaluation
            .as_mut()
            .ok_or(Error::OwnerUnavailable("original B handoff"))?;
        let before = evaluation.read_execution()?;
        let manifest = before.plan().record().candidate.manifest.clone();
        if evaluation.read_execution()? != before {
            return Err(Error::CommitUncertain);
        }
        Ok(manifest)
    }
}
