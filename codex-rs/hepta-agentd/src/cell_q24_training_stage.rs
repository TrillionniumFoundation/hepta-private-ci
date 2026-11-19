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
use crate::cell_composed_q24::OriginalQ24DatasetReadV1;
use crate::cell_composed_q24::OriginalQ24OwnerReadV1;
#[cfg(target_os = "linux")]
use crate::cell_q24_training_source::OriginalCellQ24TrainingSourceOperationV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

#[path = "cell_q24_training_stage_construction.rs"]
mod construction;

#[cfg(target_os = "linux")]
#[path = "cell_q24_training_stage_operation.rs"]
mod operation;
#[cfg(target_os = "linux")]
pub(crate) use operation::OriginalQ24TrainingOperationEvidenceV1;
#[cfg(target_os = "linux")]
pub(crate) use operation::OriginalQ24TrainingOperationV1;

#[path = "cell_q24_training_model_lane.rs"]
mod model_lane;
#[path = "cell_q24_training_source_lane.rs"]
mod source_lane;
#[cfg(target_os = "linux")]
use source_lane::SourceLaneCancellation;
#[cfg(target_os = "linux")]
use source_lane::SourceLaneCancellationState;
use source_lane::SourceLaneProof;

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
    #[cfg(target_os = "linux")]
    #[error("original Candidate material: {0}")]
    CandidateMaterial(#[from] crate::OriginalCellQ24CandidateMaterialErrorV1),
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
    #[cfg(target_os = "linux")]
    source_fenced: bool,
}

pub struct OriginalCellQ24TrainingStageV1<TW: AnchorWitnessStore, RW: AnchorWitnessStore> {
    dataset: LearningIterationSnapshotV1,
    owners: Arc<Mutex<Owners<TW, RW>>>,
    lane: Arc<Semaphore>,
    #[cfg(target_os = "linux")]
    source_abandoned: Arc<AtomicBool>,
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
            owners: Arc::new(Mutex::new(Owners {
                training,
                receipts,
                #[cfg(target_os = "linux")]
                source_fenced: false,
            })),
            lane: Arc::new(Semaphore::new(/*permits*/ 1)),
            #[cfg(target_os = "linux")]
            source_abandoned: Arc::new(AtomicBool::new(false)),
        };
        stage
            .in_lane(|owners, _source| {
                owners.require_original_initial_receipts(&OriginalQ24OwnerReadV1)
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
            .in_lane(move |owners, _source| {
                owners.execute_original_training_with_source_at(
                    &cancellation,
                    &OriginalQ24OwnerReadV1,
                    operation_started_at,
                )
            })
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
        self.in_lane(|owners, _source| owners.read_original_completion())
            .await
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
        self.in_lane(|owners, _source| {
            let training: &mut CellQ24TrainingOwnerV1<TW> = &mut owners.training;
            training.require_original_dataset_provenance()?;
            let completed = owners.read_original_completion()?;
            let training: &mut CellQ24TrainingOwnerV1<TW> = &mut owners.training;
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
        if owners.source_fenced
            || self
                .source_abandoned
                .load(std::sync::atomic::Ordering::Acquire)
        {
            return Err(crate::LearningIterationRuntimeErrorV1::CommitUncertain);
        }
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
        work: impl FnOnce(&mut Owners<TW, RW>, &SourceLaneProof<'_>) -> Result<T, Error>
        + Send
        + 'static,
    ) -> Result<T, Error> {
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let owners = Arc::clone(&self.owners);
        #[cfg(target_os = "linux")]
        let mut cancellation = SourceLaneCancellation::new(Arc::clone(&self.source_abandoned));
        #[cfg(target_os = "linux")]
        let worker_cancellation = SourceLaneCancellation::worker(&cancellation);
        let completed = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut owners = owners.try_lock().map_err(|_| Error::CommitUncertain)?;
            #[cfg(target_os = "linux")]
            if owners.source_fenced
                || SourceLaneCancellationState::stage_is_fenced(&worker_cancellation)
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
            if source.is_some() {
                SourceLaneCancellationState::bind_source(&worker_cancellation)?;
            }
            #[cfg(target_os = "linux")]
            let operation = source
                .as_ref()
                .map(|source| {
                    crate::OriginalCellQ24TrainingSourceV1::begin_source_operation(source)
                })
                .transpose()
                .map_err(CellQ24TrainingOwnerErrorV1::from)?;
            let result = {
                #[cfg(target_os = "linux")]
                let proof = SourceLaneProof::from_operation(operation.as_ref());
                #[cfg(not(target_os = "linux"))]
                let proof = SourceLaneProof::legacy();
                work(&mut owners, &proof)
            };
            // Work or its acknowledgement may already have happened. Read each
            // original Source channel once after work, then physically reread
            // Native and Generator before consuming the borrowed operation.
            #[cfg(target_os = "linux")]
            if let (Some(source), Some(mut operation)) = (source.as_ref(), operation) {
                if OriginalCellQ24TrainingSourceOperationV1::read_after_native(
                    &mut operation,
                    source,
                )
                .is_err()
                {
                    owners.source_fenced = true;
                    return Err(Error::CommitUncertain);
                }
                if owners.require_captured_tail_current().is_err()
                    || SourceLaneCancellationState::require_live(&worker_cancellation).is_err()
                {
                    owners.source_fenced = true;
                    return Err(Error::CommitUncertain);
                }
                OriginalCellQ24TrainingSourceOperationV1::finish(operation, source).map_err(
                    |_| {
                        owners.source_fenced = true;
                        Error::CommitUncertain
                    },
                )?;
            }
            result
        })
        .await
        .map_err(|_| Error::CommitUncertain);
        #[cfg(target_os = "linux")]
        SourceLaneCancellation::joined(&mut cancellation);
        completed?
    }
}

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore> Owners<TW, RW> {
    fn execute_original_training_with_source(
        &mut self,
        cancellation: &AtomicBool,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        let operation_started_at =
            super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
        let (completed, new_work_started_at) = self.execute_original_training_with_source_at(
            cancellation,
            source,
            operation_started_at,
        )?;
        if let Some(started_at) = new_work_started_at {
            let fresh_now = super::now().map_err(|_| Error::CommitUncertain)?;
            if fresh_now < started_at
                || fresh_now
                    >= self
                        .receipts
                        .config
                        .dataset
                        .request
                        .envelope
                        .expiry_unix_seconds
            {
                return Err(Error::CommitUncertain);
            }
        }
        Ok(completed)
    }

    fn execute_original_training_with_source_at(
        &mut self,
        cancellation: &AtomicBool,
        source: &impl OriginalQ24DatasetReadV1,
        operation_started_at: u64,
    ) -> Result<(OriginalCellQ24TrainingCompletionV1, Option<u64>), Error> {
        match self.receipts.journal.read(&self.receipts.saved) {
            Ok(_) => self
                .read_original_completion_with_source(source)
                .map(|completed| (completed, None)),
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
                if now >= receipts.config.dataset.request.envelope.expiry_unix_seconds
                    || now < operation_started_at
                {
                    return Err(Error::DeadlineExceeded);
                }
                let outcome = match retained_outcome {
                    Some(outcome) => outcome,
                    None => training.fit_or_readback_with_source(cancellation, source)?,
                };
                #[cfg(target_os = "linux")]
                training.require_live_source_if_captured()?;
                let fresh_now =
                    super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
                if fresh_now < now
                    || fresh_now >= receipts.config.dataset.request.envelope.expiry_unix_seconds
                {
                    return Err(Error::DeadlineExceeded);
                }
                let (receipt, attestation) =
                    receipts.attest_completion_with_source(training, source)?;
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

    /// A source RPC can block after work finishes. Re-read both original owners
    /// after that RPC without claiming Missing or retrying Pending.
    #[cfg(target_os = "linux")]
    fn require_captured_tail_current(&mut self) -> Result<(), Error> {
        self.training.require_original_dataset_scope(
            &self.receipts.config.dataset,
            &self.receipts.config.scope,
        )?;
        match self.receipts.journal.read(&self.receipts.saved) {
            Ok(_) => {
                let completed = self.read_original_completion()?;
                self.require_retained_attestation_current(&completed)?;
            }
            Err(
                LearningOriginalOwnerErrorV1::Store(
                    ProductEvaluationExecutionStoreErrorV1::Missing,
                )
                | LearningOriginalOwnerErrorV1::Pending,
            ) => {}
            Err(error) => return Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
        }
        Ok(())
    }

    /// Verify retained signature bytes at fresh time without extending them.
    #[cfg(target_os = "linux")]
    fn require_retained_attestation_current(
        &self,
        completed: &OriginalCellQ24TrainingCompletionV1,
    ) -> Result<(), Error> {
        let payload = codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(
            &completed.receipt,
        )
        .map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
        self.receipts
            .config
            .verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &completed.attestation,
                &payload,
                super::now().map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?,
            )
            .map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
        Ok(())
    }
}
