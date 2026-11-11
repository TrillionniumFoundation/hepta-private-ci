//! Narrow Model material operations borrowing the same original trainer lane.
//! These synchronous methods perform bounded blocking I/O. The host must call
//! them from its bounded blocking lane, never an async executor worker. A Busy
//! lane or uncertain acknowledgement is not permission to retry admitted work.
//! No trainer, signing owner, descriptor or general callback is exposed.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCellQ24TrainingCompletionV1;
use super::OriginalCellQ24TrainingStageV1;
use super::Owners;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::CellQ24TrainingOwnerV1;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    /// Consume the host's original Model file and witness after the original
    /// Training completion. NoUpdate refuses before Model file initialization.
    /// Call only from the host's bounded blocking lane.
    pub fn create_model_owner<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        self.in_model_lane(|training, _| {
            CellQ24ModelProposalOwnerV1::create(file, witness, training, self.dataset.clone())
                .map_err(Error::from)
        })
    }

    /// Recover only the supplied original Model owner. Training and Generator
    /// custody remain in this lane; neither owner is reopened or reconstructed.
    /// Call only from the host's bounded blocking lane.
    pub fn recover_model_owner<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        self.in_model_lane(|training, _| {
            CellQ24ModelProposalOwnerV1::recover(file, witness, training, self.dataset.clone())
                .map_err(Error::from)
        })
    }

    /// Commit or read the original Model material using the retained Generator
    /// receipt and signature. Missing may claim once; Pending stays unresolved.
    /// Call only from the host's bounded blocking lane.
    pub fn commit_model_or_readback<MW: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<MW>,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.in_model_lane(|training, completed| {
            require_original_training(inputs, completed)?;
            CellQ24ModelProposalOwnerV1::commit_or_readback(model, training, inputs)
                .map_err(Error::from)
        })
    }

    /// Read without claiming, fitting or signing. Missing and Pending remain
    /// distinct errors; current original evidence must still validate.
    /// Call only from the host's bounded blocking lane.
    pub fn read_model_proposal<MW: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<MW>,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.in_model_lane(|training, completed| {
            require_original_training(inputs, completed)?;
            CellQ24ModelProposalOwnerV1::readback(model, training, inputs).map_err(Error::from)
        })
    }

    fn in_model_lane<T>(
        &self,
        work: impl FnOnce(
            &mut CellQ24TrainingOwnerV1<TW>,
            &OriginalCellQ24TrainingCompletionV1,
        ) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let _permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut owners = self.owners.try_lock().map_err(|_| Error::CommitUncertain)?;
        let Owners { training, receipts } = &mut *owners;
        let training: &mut CellQ24TrainingOwnerV1<TW> = training;
        training.require_original_dataset_scope(&receipts.config.dataset, &receipts.config.scope)?;
        let original = owners.read_original_completion()?;
        let result = work(&mut owners.training, &original);
        // The Model operation can block. Re-read both original owners before
        // returning even an error; never renew a signature or retry a claim.
        let current = owners
            .read_original_completion()
            .map_err(|_| Error::CommitUncertain)?;
        if current.receipt != original.receipt || current.attestation != original.attestation {
            return Err(Error::CommitUncertain);
        }
        result
    }
}

fn require_original_training(
    inputs: &CellQ24ModelProposalInputsV1<'_, impl FinalHoldoutCasStoreV1>,
    completed: &OriginalCellQ24TrainingCompletionV1,
) -> Result<(), Error> {
    if inputs.training_cut.receipts.last() != Some(&completed.receipt)
        || inputs.training_attestation != &completed.attestation
    {
        return Err(Error::Binding("exact retained Training receipt and attestation"));
    }
    Ok(())
}
