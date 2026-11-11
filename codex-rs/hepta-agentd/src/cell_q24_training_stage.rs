//! A bounded consumer of the original native trainer and Generator receipt owner.
//! The host transfers both typed owners; this adapter provisions no custody and
//! does not implement the other learning stages or assemble Root startup.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;
use tokio::sync::Semaphore;

use super::OriginalCellQ24TrainingReceiptErrorV1;
use super::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::CellQ24ModelProposalErrorV1;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::CellQ24TrainingOwnerV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "cell_q24_training_model_lane.rs"]
mod model_lane;

#[cfg(target_os = "linux")]
#[path = "cell_q24_source_bound_stage.rs"]
mod source_bound;
#[cfg(target_os = "linux")]
pub use source_bound::SourceBoundCellQ24TrainingStageV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingStageErrorV1 {
    #[error("original training lane is already occupied")]
    Busy,
    #[error("original training request expired before new work")]
    DeadlineExceeded,
    #[error("original training lane completion is uncertain")]
    CommitUncertain,
    #[error("original training stage binding: {0}")]
    Binding(&'static str),
    #[error("original native training: {0}")]
    Training(#[from] CellQ24TrainingOwnerErrorV1),
    #[error("original training receipt: {0}")]
    Receipt(#[from] OriginalCellQ24TrainingReceiptErrorV1),
    #[error("original model material: {0}")]
    ModelProposal(#[from] CellQ24ModelProposalErrorV1),
}

type Error = OriginalCellQ24TrainingStageErrorV1;

/// Original retained bytes and their existing receipt, not a publication grant.
pub struct OriginalCellQ24TrainingCompletionV1 {
    pub outcome: CellQ24TrainingOutcomeV1,
    pub receipt: LearningIterationReceiptV1,
    pub attestation: SignedLearningEvidenceV1,
}

struct Owners<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    training: CellQ24TrainingOwnerV1<TW>,
    receipts: OriginalCellQ24TrainingReceiptOwnerV1<RW>,
}

pub struct OriginalCellQ24TrainingStageV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    dataset: LearningIterationSnapshotV1,
    owners: Arc<Mutex<Owners<TW, RW>>>,
    lane: Arc<Semaphore>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    /// Consume already authorized owners. No descriptor, key or trust is opened.
    pub async fn from_original_owners(
        training: CellQ24TrainingOwnerV1<TW>,
        receipts: OriginalCellQ24TrainingReceiptOwnerV1<RW>,
    ) -> Result<Self, Error> {
        let stage = Self {
            dataset: receipts.config.dataset.clone(),
            owners: Arc::new(Mutex::new(Owners { training, receipts })),
            lane: Arc::new(Semaphore::new(/*permits*/ 1)),
        };
        stage
            .in_lane(|owners| {
                super::validate_config(&owners.receipts.config, &owners.receipts.key)?;
                match owners.receipts.journal.read(&owners.receipts.saved) {
                    Ok(_) => owners.read_original_completion().map(|_| ()),
                    Err(LearningOriginalOwnerErrorV1::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing,
                    )) => Ok(()),
                    Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
                }
            })
            .await?;
        Ok(stage)
    }

    /// Only a genuinely missing receipt may enter the original trainer. Pending
    /// remains unresolved; an existing completion never fits or signs again.
    /// Dropping this future does not stop a running blocking operation or free
    /// its lane. The host can set cancellation; any admitted Pending stays so.
    pub async fn execute_training(
        &self,
        dataset: &LearningIterationSnapshotV1,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        let operation_started_at =
            super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
        let (completed, new_work_started_at) = self
            .in_lane(
                move |owners| match owners.receipts.journal.read(&owners.receipts.saved) {
                    Ok(_) => owners
                        .read_original_completion()
                        .map(|completed| (completed, None)),
                    Err(LearningOriginalOwnerErrorV1::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing,
                    )) => {
                        let training: &mut CellQ24TrainingOwnerV1<TW> = &mut owners.training;
                        let receipts: &mut OriginalCellQ24TrainingReceiptOwnerV1<RW> =
                            &mut owners.receipts;
                        let retained_outcome = match training.readback() {
                            Ok(outcome) => Some(outcome),
                            Err(CellQ24TrainingOwnerErrorV1::Store(
                                ProductEvaluationExecutionStoreErrorV1::Missing,
                            )) => None,
                            Err(error) => return Err(error.into()),
                        };
                        // Readback can block on the original witness. Check time
                        // after that I/O, before any new training or receipt claim.
                        let now =
                            super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                        receipts
                            .config
                            .verifier
                            .require_signer_binding(
                                LearningEvidenceRoleV1::Generator,
                                &receipts.config.signer,
                                now,
                            )
                            .map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                        if now >= receipts.config.dataset.request.envelope.expiry_unix_seconds
                            || now < operation_started_at
                        {
                            return Err(Error::DeadlineExceeded);
                        }
                        let outcome = match retained_outcome {
                            Some(outcome) => outcome,
                            None => training.fit_or_readback(&cancellation)?,
                        };
                        #[cfg(target_os = "linux")]
                        training.require_live_source_if_captured()?;
                        let fresh_now =
                            super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                        if fresh_now < now
                            || fresh_now
                                >= receipts.config.dataset.request.envelope.expiry_unix_seconds
                        {
                            return Err(Error::DeadlineExceeded);
                        }
                        let (receipt, attestation) =
                            receipts.attest_original_completion(training)?;
                        Ok((
                            OriginalCellQ24TrainingCompletionV1 {
                                outcome,
                                receipt,
                                attestation,
                            },
                            Some(operation_started_at),
                        ))
                    }
                    Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
                },
            )
            .await?;
        if let Some(started_at) = new_work_started_at {
            let fresh_now = super::now().map_err(|_| Error::CommitUncertain)?;
            if fresh_now < started_at || fresh_now >= dataset.request.envelope.expiry_unix_seconds {
                // Native or receipt commit may already be durable. Preserve
                // that uncertainty; never return a successful late NoUpdate.
                return Err(Error::CommitUncertain);
            }
        }
        Ok(completed)
    }

    /// Re-read both original CURRENTs and the exact retained signature window.
    pub async fn readback(
        &self,
        dataset: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        self.in_lane(Owners::read_original_completion).await
    }

    /// The caller supplies only an equality check, never bytes to be signed.
    pub async fn receipt_attestation(
        &self,
        dataset: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let completed = self.readback(dataset).await?;
        if &completed.receipt != expected {
            return Err(Error::Binding("exact original Training receipt"));
        }
        Ok(completed.attestation)
    }

    fn require_dataset(&self, dataset: &LearningIterationSnapshotV1) -> Result<(), Error> {
        if dataset != &self.dataset {
            return Err(Error::Binding("exact original Dataset cut"));
        }
        Ok(())
    }

    async fn in_lane<T: Send + 'static>(
        &self,
        work: impl FnOnce(&mut Owners<TW, RW>) -> Result<T, Error> + Send + 'static,
    ) -> Result<T, Error> {
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let owners = Arc::clone(&self.owners);
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut owners = owners.try_lock().map_err(|_| Error::CommitUncertain)?;
            let Owners { training, receipts } = &mut *owners;
            let training: &mut CellQ24TrainingOwnerV1<TW> = training;
            training
                .require_original_dataset_scope(&receipts.config.dataset, &receipts.config.scope)?;
            #[cfg(target_os = "linux")]
            training.require_live_source_if_captured()?;
            let result = work(&mut owners);
            // Work or its acknowledgement may already have happened. A failed
            // tail read cannot return a candidate, NoUpdate, or fresh signature.
            #[cfg(target_os = "linux")]
            owners
                .training
                .require_live_source_if_captured()
                .map_err(|_| Error::CommitUncertain)?;
            result
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }
}

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore> Owners<TW, RW> {
    fn read_original_completion(&mut self) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        let training: &mut CellQ24TrainingOwnerV1<TW> = &mut self.training;
        let (receipt, attestation) = self.receipts.readback(training)?;
        let outcome = training.readback()?;
        Ok(OriginalCellQ24TrainingCompletionV1 {
            outcome,
            receipt,
            attestation,
        })
    }
}
