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
use super::SourceLaneProof;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::CellQ24ModelProposalReceiptV1;
use crate::CellQ24TrainingOwnerV1;
#[cfg(target_os = "linux")]
use crate::cell_q24_training_source::OriginalCellQ24TrainingSourceOperationV1;

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
        self.in_model_lane(|training, _, _source| {
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
        self.in_model_lane(|training, _, _source| {
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
        self.in_model_lane(|training, completed, _source| {
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
        self.in_model_lane(|training, completed, _source| {
            require_original_training(inputs, completed)?;
            CellQ24ModelProposalOwnerV1::readback(model, training, inputs).map_err(Error::from)
        })
    }

    /// Material only: no fit, signature, journal claim, or publication.
    /// Only the SourceBound facade calls this same original occupied lane.
    #[cfg(target_os = "linux")]
    pub(crate) fn read_candidate_material(
        &self,
    ) -> Result<crate::OriginalCellQ24CandidateMaterialV1, Error> {
        self.in_model_lane(|training, completed, source| {
            SourceLaneProof::require_original(source, training)?;
            let candidate = match CellQ24TrainingOwnerV1::readback(training)? {
                crate::CellQ24TrainingOutcomeV1::Candidate(candidate) => *candidate,
                crate::CellQ24TrainingOutcomeV1::NoUpdate { .. } => {
                    return Err(crate::OriginalCellQ24CandidateMaterialErrorV1::NoCandidate.into());
                }
            };
            Ok(
                crate::OriginalCellQ24CandidateMaterialV1::from_original_candidate(
                    &self.dataset,
                    candidate,
                    completed.receipt.clone(),
                    completed.attestation.clone(),
                )?,
            )
        })
    }

    /// The remote material was read outside this lane. Fresh authentication
    /// follows Native and witness I/O before the original Model header is made.
    #[cfg(target_os = "linux")]
    pub(crate) fn create_model_from_current_evaluation<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
        training_cut: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        training_attestation: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
        material: &crate::OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        self.in_model_lane(|training, completed, _source| {
            require_current_training(training_cut, training_attestation, completed)?;
            CellQ24ModelProposalOwnerV1::create_from_current_material(
                file,
                witness,
                training,
                self.dataset.clone(),
                training_cut,
                training_attestation,
                material,
            )
            .map_err(Error::from)
        })
    }

    /// Explicit original-host deployment recovery; never called by a Model
    /// command readback. Preserve the original minimum-anchor suffix semantics.
    #[cfg(target_os = "linux")]
    pub(crate) fn recover_model_from_current_evaluation<MW: AnchorWitnessStore>(
        &self,
        file: File,
        witness: MW,
        training_cut: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        training_attestation: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
        material: &crate::OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalOwnerV1<MW>, Error> {
        self.in_model_lane(|training, completed, _source| {
            require_current_training(training_cut, training_attestation, completed)?;
            CellQ24ModelProposalOwnerV1::recover_from_current_material(
                file,
                witness,
                training,
                self.dataset.clone(),
                training_cut,
                training_attestation,
                material,
            )
            .map_err(Error::from)
        })
    }

    /// The caller completed its original Evaluation read before entering this
    /// lane. Only pure material verification and original owner I/O run here.
    #[cfg(target_os = "linux")]
    pub(crate) fn commit_model_from_current_evaluation<MW: AnchorWitnessStore>(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<MW>,
        training_cut: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        training_attestation: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
        material: &crate::OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.in_model_lane(|training, completed, _source| {
            require_current_training(training_cut, training_attestation, completed)?;
            CellQ24ModelProposalOwnerV1::commit_current_material_or_readback(
                model,
                training,
                training_cut,
                training_attestation,
                material,
            )
            .map_err(Error::from)
        })
    }

    /// Re-enter the same lane after the independent Evaluator read. Missing,
    /// Pending, changed source or a different original signature remain errors.
    #[cfg(target_os = "linux")]
    pub(crate) fn read_model_from_current_evaluation<MW: AnchorWitnessStore>(
        &self,
        model: &mut CellQ24ModelProposalOwnerV1<MW>,
        training_cut: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        training_attestation: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
        material: &crate::OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        self.in_model_lane(|training, completed, _source| {
            require_current_training(training_cut, training_attestation, completed)?;
            CellQ24ModelProposalOwnerV1::read_current_material(
                model,
                training,
                training_cut,
                training_attestation,
                material,
            )
            .map_err(Error::from)
        })
    }

    fn in_model_lane<T>(
        &self,
        work: impl FnOnce(
            &mut CellQ24TrainingOwnerV1<TW>,
            &OriginalCellQ24TrainingCompletionV1,
            &SourceLaneProof<'_>,
        ) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let _permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let mut owners = self.owners.try_lock().map_err(|_| Error::CommitUncertain)?;
        #[cfg(target_os = "linux")]
        if owners.source_fenced
            || self
                .source_abandoned
                .load(std::sync::atomic::Ordering::Acquire)
        {
            return Err(Error::CommitUncertain);
        }
        let Owners {
            training, receipts, ..
        } = &mut *owners;
        let training: &mut CellQ24TrainingOwnerV1<TW> = training;
        training
            .require_original_dataset_scope(&receipts.config.dataset, &receipts.config.scope)?;
        #[cfg(target_os = "linux")]
        let source = training.original_source_for_operation()?;
        #[cfg(target_os = "linux")]
        let mut operation = source
            .as_ref()
            .map(|source| crate::OriginalCellQ24TrainingSourceV1::begin_source_operation(source))
            .transpose()
            .map_err(crate::CellQ24TrainingOwnerErrorV1::from)?;
        let original = owners.read_original_completion()?;
        let result = {
            #[cfg(target_os = "linux")]
            let proof = SourceLaneProof::from_operation(operation.as_ref());
            #[cfg(not(target_os = "linux"))]
            let proof = SourceLaneProof::legacy();
            work(&mut owners.training, &original, &proof)
        };
        // The actual Model effect remains inside the same original lane.
        // Source after reads cannot return a cached completion or a new lease.
        #[cfg(target_os = "linux")]
        let source_bound = source.is_some();
        #[cfg(target_os = "linux")]
        if let (Some(source), Some(operation)) = (source.as_ref(), operation.as_mut()) {
            if OriginalCellQ24TrainingSourceOperationV1::read_after_native(operation, source).is_err() {
                owners.source_fenced = true;
                return Err(Error::CommitUncertain);
            }
        }
        let current = owners.read_original_completion().map_err(|_| {
            #[cfg(target_os = "linux")]
            if source_bound {
                owners.source_fenced = true;
            }
            Error::CommitUncertain
        })?;
        #[cfg(target_os = "linux")]
        if source_bound {
            if owners
                .require_retained_attestation_current(&current)
                .is_err()
            {
                owners.source_fenced = true;
                return Err(Error::CommitUncertain);
            }
        }
        if current.receipt != original.receipt || current.attestation != original.attestation {
            #[cfg(target_os = "linux")]
            if source_bound {
                owners.source_fenced = true;
            }
            return Err(Error::CommitUncertain);
        }
        #[cfg(target_os = "linux")]
        if let (Some(source), Some(operation)) = (source.as_ref(), operation) {
            if self
                .source_abandoned
                .load(std::sync::atomic::Ordering::Acquire)
            {
                owners.source_fenced = true;
                return Err(Error::CommitUncertain);
            }
            OriginalCellQ24TrainingSourceOperationV1::finish(operation, source).map_err(|_| {
                owners.source_fenced = true;
                Error::CommitUncertain
            })?;
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
        return Err(Error::Binding(
            "exact retained Training receipt and attestation",
        ));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn require_current_training(
    cut: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
    attestation: &codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    completed: &OriginalCellQ24TrainingCompletionV1,
) -> Result<(), Error> {
    if cut.receipts.last() != Some(&completed.receipt) || attestation != &completed.attestation {
        return Err(Error::Binding(
            "exact retained Training receipt and attestation",
        ));
    }
    Ok(())
}
