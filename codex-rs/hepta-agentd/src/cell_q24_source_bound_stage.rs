//! Ordinary Training entry requiring the actual retained source capability.
//! This type consumes the original Stage; it never borrows a legacy batch,
//! exposes a trainer, provisions custody, or accepts caller-selected labels.

use std::fs::File;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCellQ24TrainingCompletionV1;
use super::OriginalCellQ24TrainingStageV1;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::CellQ24TrainingOwnerV1;

pub struct SourceBoundCellQ24TrainingStageV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    original: OriginalCellQ24TrainingStageV1<TW, RW>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    SourceBoundCellQ24TrainingStageV1<TW, RW>
{
    /// Consume the same original Stage and check its private live capability
    /// in its original blocking lane. A byte-identical legacy batch is refused.
    /// This transfers no writer, private key or general execution callback.
    pub async fn from_original_stage(
        original: OriginalCellQ24TrainingStageV1<TW, RW>,
    ) -> Result<Self, Error> {
        original
            .in_lane(|owners| {
                CellQ24TrainingOwnerV1::require_original_source_capture(&mut owners.training)?;
                Ok(())
            })
            .await?;
        Ok(Self { original })
    }

    pub async fn execute_training(
        &self,
        dataset: &LearningIterationSnapshotV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        OriginalCellQ24TrainingStageV1::execute_training(&self.original, dataset, cancellation).await
    }

    pub async fn readback(
        &self,
        dataset: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        OriginalCellQ24TrainingStageV1::readback(&self.original, dataset).await
    }

    pub async fn receipt_attestation(
        &self,
        dataset: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        OriginalCellQ24TrainingStageV1::receipt_attestation(&self.original, dataset, expected).await
    }

    /// Synchronous original-lane I/O; call from the host's bounded blocking
    /// lane. Busy and lost ACKs never authorize another admitted operation.
    pub fn create_model_owner<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        OriginalCellQ24TrainingStageV1::create_model_owner(&self.original, file, witness)
    }

    pub fn recover_model_owner<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        OriginalCellQ24TrainingStageV1::recover_model_owner(&self.original, file, witness)
    }

    pub fn commit_model_or_readback(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<impl AnchorWitnessStore>,
        inputs: &CellQ24ModelProposalInputsV1<'_, impl FinalHoldoutCasStoreV1>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        OriginalCellQ24TrainingStageV1::commit_model_or_readback(&self.original, model, inputs)
    }

    /// Same original trainer, signature owner and Model journal. Both live
    /// data and Material predecessor signatures are checked before and after.
    pub fn read_model_proposal(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<impl AnchorWitnessStore>,
        inputs: &CellQ24ModelProposalInputsV1<'_, impl FinalHoldoutCasStoreV1>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        OriginalCellQ24TrainingStageV1::read_model_proposal(&self.original, model, inputs)
    }
}
