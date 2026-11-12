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
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::CellQ24TrainingOwnerV1;
use crate::cell_composed_q24::OriginalQ24DatasetReadV1;
use crate::cell_composed_q24::OriginalQ24OwnerReadV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[cfg(target_os = "linux")]
#[path = "cell_q24_training_stage_operation.rs"]
mod operation;
#[cfg(target_os = "linux")]
pub(crate) use operation::OriginalQ24TrainingOperationEvidenceV1;
#[cfg(target_os = "linux")]
pub(crate) use operation::OriginalQ24TrainingOperationV1;

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
    /// Preflight an explicitly transferred pair before an aggregate can sign
    /// or fit. Mixed genesis recovery does not waive the real Dataset cut.
    #[cfg(target_os = "linux")]
    pub(crate) fn require_original_pair(
        training: &CellQ24TrainingOwnerV1<TW>,
        receipts: &OriginalCellQ24TrainingReceiptOwnerV1<RW>,
        dataset: &LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        if &receipts.config.dataset != dataset || &receipts.config.scope != scope {
            return Err(Error::Binding("exact original training pair Dataset"));
        }
        super::validate_config(&receipts.config, &receipts.key)?;
        training.require_original_dataset_provenance()?;
        training.require_original_dataset_scope(dataset, scope)?;
        Ok(())
    }

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
        self.in_lane(move |owners| {
            owners.execute_original_training_with_source(&cancellation, &OriginalQ24OwnerReadV1)
        })
        .await
    }

    /// Re-read both original CURRENTs and the exact retained signature window.
    pub async fn readback(
        &self,
        dataset: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        self.in_lane(Owners::read_original_completion).await
    }

    /// Read the already completed original HQ24T002 owners in the same lane.
    /// This separate path refuses legacy batches without changing their old
    /// readback contract. Missing and Pending cannot fit or first-attest here.
    #[cfg(target_os = "linux")]
    pub(crate) async fn read_original_dataset_completion(
        &self,
        dataset: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        self.in_lane(|owners| {
            let training: &CellQ24TrainingOwnerV1<TW> = &owners.training;
            training.require_original_dataset_provenance()?;
            let completed = owners.read_original_completion()?;
            let training: &CellQ24TrainingOwnerV1<TW> = &owners.training;
            training.require_original_dataset_provenance()?;
            Ok(completed)
        })
        .await
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

    /// Used only inside the concrete ordinary aggregate's bounded blocking
    /// lane. Keep this same trainer and its existing fit semaphore exclusively
    /// held while the original Root Model factory performs its async readback.
    /// No trainer reference or replacement owner escapes the closure.
    #[cfg(target_os = "linux")]
    pub(crate) fn with_original_trainer<T>(
        &self,
        dataset: &LearningIterationSnapshotV1,
        work: impl FnOnce(
            &mut CellQ24TrainingOwnerV1<TW>,
        ) -> Result<T, crate::LearningIterationRuntimeErrorV1>,
    ) -> Result<T, crate::LearningIterationRuntimeErrorV1> {
        self.require_dataset(dataset)
            .map_err(|_| crate::LearningIterationRuntimeErrorV1::WrongScope)?;
        let _permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| crate::LearningIterationRuntimeErrorV1::CommitUncertain)?;
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| crate::LearningIterationRuntimeErrorV1::CommitUncertain)?;
        let scope = owners.receipts.config.scope.clone();
        let training: &mut CellQ24TrainingOwnerV1<TW> = &mut owners.training;
        training
            .require_original_dataset_provenance()
            .map_err(|_| {
                crate::LearningIterationRuntimeErrorV1::OwnerUnavailable("original training source")
            })?;
        training
            .require_original_dataset_scope(dataset, &scope)
            .map_err(|_| crate::LearningIterationRuntimeErrorV1::WrongScope)?;
        let result = work(training)?;
        training
            .require_original_dataset_provenance()
            .map_err(|_| {
                crate::LearningIterationRuntimeErrorV1::OwnerUnavailable("original training source")
            })?;
        Ok(result)
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
            let training: &CellQ24TrainingOwnerV1<TW> = &owners.training;
            training.require_original_dataset_scope(
                &owners.receipts.config.dataset,
                &owners.receipts.config.scope,
            )?;
            work(&mut owners)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?
    }
}

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore> Owners<TW, RW> {
    fn execute_original_training_with_source(
        &mut self,
        cancellation: &AtomicBool,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        match self.receipts.journal.read(&self.receipts.saved) {
            Ok(_) => self.read_original_completion_with_source(source),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {
                let training: &mut CellQ24TrainingOwnerV1<TW> = &mut self.training;
                let receipts: &mut OriginalCellQ24TrainingReceiptOwnerV1<RW> = &mut self.receipts;
                let retained_outcome =
                    match CellQ24TrainingOwnerV1::readback_with_source(training, source) {
                        Ok(outcome) => Some(outcome),
                        Err(CellQ24TrainingOwnerErrorV1::Store(
                            ProductEvaluationExecutionStoreErrorV1::Missing,
                        )) => None,
                        Err(error) => return Err(error.into()),
                    };
                // Readback can block on the original witness. Check time
                // after that I/O, before any new training or receipt claim.
                let now = super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                receipts
                    .config
                    .verifier
                    .require_signer_binding(
                        LearningEvidenceRoleV1::Generator,
                        &receipts.config.signer,
                        now,
                    )
                    .map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                if now >= receipts.config.dataset.request.envelope.expiry_unix_seconds {
                    return Err(Error::DeadlineExceeded);
                }
                let outcome = match retained_outcome {
                    Some(outcome) => outcome,
                    None => training.fit_or_readback_with_source(cancellation, source)?,
                };
                let (receipt, attestation) =
                    receipts.attest_completion_with_source(training, source)?;
                Ok(OriginalCellQ24TrainingCompletionV1 {
                    outcome,
                    receipt,
                    attestation,
                })
            }
            Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
        }
    }

    fn read_original_completion(&mut self) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.read_original_completion_with_source(&OriginalQ24OwnerReadV1)
    }

    fn read_original_completion_with_source(
        &mut self,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        let training: &mut CellQ24TrainingOwnerV1<TW> = &mut self.training;
        let (receipt, attestation) = OriginalCellQ24TrainingReceiptOwnerV1::readback_with_source(
            &mut self.receipts,
            training,
            source,
        )?;
        let outcome = CellQ24TrainingOwnerV1::readback_with_source(training, source)?;
        Ok(OriginalCellQ24TrainingCompletionV1 {
            outcome,
            receipt,
            attestation,
        })
    }
}
