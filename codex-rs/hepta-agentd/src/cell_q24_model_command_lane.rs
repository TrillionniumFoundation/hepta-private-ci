//! Private Model adapter in the original Trainer command owner. All remote
//! Evaluator reads stay in the host outside these original lane operations.
use super::super::model_command::OriginalCellQ24ModelCommandErrorV1 as Error;
use super::super::model_command::context::Context;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::OriginalCellEvaluationModelMaterialV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use std::fs::File;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingCommandOwnerV1<TW, RW>
{
    pub(in super::super) async fn read_original_model_training(
        &self,
        dataset: &crate::OriginalCellQ24MaterialCommandReceiptV1,
    ) -> Result<OriginalCellQ24TrainingCommandReceiptV1, Error> {
        if dataset.snapshot() != &self.context.dataset {
            return Err(Error::Binding("same original Model Dataset"));
        }
        let completed =
            SourceBoundCellQ24TrainingStageV1::readback(&self.stage, &self.context.dataset).await?;
        Ok(super::super::wire::authenticate_receipt(
            &self.context,
            completed.receipt,
            completed.attestation,
            super::super::now()?,
        )?)
    }
    pub(in super::super) fn create_original_model(
        &self,
        file: File,
        witness: FileAnchorWitnessStore,
        context: &Context,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>, Error> {
        self.require_model_context(context)?;
        Ok(
            SourceBoundCellQ24TrainingStageV1::create_model_from_current_evaluation(
                &self.stage,
                file,
                witness,
                &context.training_cut,
                context.training.attestation(),
                material,
            )?,
        )
    }
    pub(in super::super) fn recover_original_model(
        &self,
        file: File,
        witness: FileAnchorWitnessStore,
        context: &Context,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>, Error> {
        self.require_model_context(context)?;
        Ok(
            SourceBoundCellQ24TrainingStageV1::recover_model_from_current_evaluation(
                &self.stage,
                file,
                witness,
                &context.training_cut,
                context.training.attestation(),
                material,
            )?,
        )
    }
    pub(in super::super) fn commit_original_model(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>,
        context: &Context,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.require_model_context(context)?;
        Ok(
            SourceBoundCellQ24TrainingStageV1::commit_model_from_current_evaluation(
                &self.stage,
                model,
                &context.training_cut,
                context.training.attestation(),
                material,
            )?,
        )
    }
    pub(in super::super) fn read_original_model(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<FileAnchorWitnessStore>,
        context: &Context,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.require_model_context(context)?;
        Ok(
            SourceBoundCellQ24TrainingStageV1::read_model_from_current_evaluation(
                &self.stage,
                model,
                &context.training_cut,
                context.training.attestation(),
                material,
            )?,
        )
    }
    fn require_model_context(&self, context: &Context) -> Result<(), Error> {
        if self.context.dataset != *context.dataset.snapshot()
            || self.context.scope != context.material.scope
            || self.context.verifier.trust_digest() != context.material.verifier.trust_digest()
            || self.context.verifier.scope_digest() != context.material.verifier.scope_digest()
            || self.context.verifier.objective_digest()
                != context.material.verifier.objective_digest()
        {
            return Err(Error::Binding("same original SourceBound Model lane"));
        }
        Ok(())
    }
}
