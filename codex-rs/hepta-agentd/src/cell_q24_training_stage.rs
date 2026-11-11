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
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::AnchorWitnessStore;
use tokio::sync::Semaphore;

use super::OriginalCellQ24TrainingReceiptErrorV1;
use super::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::AgentdIdentity;
use crate::CellQ24TrainingOutcomeV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::CellQ24TrainingOwnerV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::OriginalCellQ24DatasetErrorV1;
use crate::OriginalCellQ24DatasetV1;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;

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
    #[error("original Dataset source: {0}")]
    Source(#[from] OriginalCellQ24DatasetErrorV1),
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

/// Actual material and its original read capabilities. This context provisions no
/// file, witness, key or role and cannot authenticate an arbitrary batch.
pub struct OriginalCellQ24TrainingSourceV1<W: AnchorWitnessStore> {
    pub material: Arc<OriginalCellQ24DatasetV1>,
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub source: Arc<CircuitTaskSourceReadbackV1<W>>,
    pub identity: AgentdIdentity,
}

impl<W: AnchorWitnessStore> Clone for OriginalCellQ24TrainingSourceV1<W> {
    fn clone(&self) -> Self {
        Self {
            material: Arc::clone(&self.material),
            ledger: Arc::clone(&self.ledger),
            source: Arc::clone(&self.source),
            identity: self.identity.clone(),
        }
    }
}

impl<W: AnchorWitnessStore> OriginalCellQ24TrainingSourceV1<W> {
    fn require_current(&self, dataset: &LearningIterationSnapshotV1) -> Result<(), Error> {
        let profile = self.material.profile();
        let request = &dataset.request;
        if profile.principal_id != request.principal_id
            || profile.agent_id.as_str() != request.agent_id.as_str()
            || profile.cell_id != request.cell_id
            || profile.objective_digest != request.envelope.objective_digest
            || profile.selected_bundle
                != request
                    .selected_bundle
                    .digest()
                    .map_err(|_| Error::Binding("original selected bundle"))?
        {
            return Err(Error::Binding("original Dataset and training request"));
        }
        self.material
            .require_request_source(&request.source_run_id, request.completed_task_receipt)?;
        let ledger = self.ledger.try_lock().map_err(|_| Error::CommitUncertain)?;
        self.material
            .revalidate(&ledger, &self.source, &self.identity)?;
        Ok(())
    }
}

enum TrainingPreparation {
    Completed(OriginalCellQ24TrainingCompletionV1),
    Unattested(CellQ24TrainingOutcomeV1),
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
        self.in_lane(move |owners| {
            let prepared = owners.prepare_training(&cancellation)?;
            owners.complete_training(prepared)
        })
        .await
    }

    /// Consume the actual source-derived batch. Both source checks and the
    /// original owner operation run in the same non-queuing blocking lane.
    /// A source withdrawn during a fit withholds its result; the original job
    /// remains retained and must never be repeated under a fresh identity.
    pub async fn execute_training_from_original_dataset<W: AnchorWitnessStore + Send + 'static>(
        &self,
        dataset: &LearningIterationSnapshotV1,
        source: OriginalCellQ24TrainingSourceV1<W>,
        cancellation: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        self.in_lane(move |owners| {
            source.require_current(&owners.receipts.config.dataset)?;
            CellQ24TrainingOwnerV1::require_original_batch(
                &owners.training,
                source.material.batch(),
            )?;
            let prepared = owners.prepare_training(&cancellation)?;
            // A native completion is not permission to sign after source withdrawal.
            source.require_current(&owners.receipts.config.dataset)?;
            let completed = owners.complete_training(prepared)?;
            source.require_current(&owners.receipts.config.dataset)?;
            Ok(completed)
        })
        .await
    }

    /// Cold readback under the same current source contract. Missing or Pending
    /// remains unresolved, and this method never fits, claims or signs.
    pub async fn readback_from_original_dataset<W: AnchorWitnessStore + Send + 'static>(
        &self,
        dataset: &LearningIterationSnapshotV1,
        source: OriginalCellQ24TrainingSourceV1<W>,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        self.require_dataset(dataset)?;
        self.in_lane(move |owners| {
            source.require_current(&owners.receipts.config.dataset)?;
            CellQ24TrainingOwnerV1::require_original_batch(
                &owners.training,
                source.material.batch(),
            )?;
            let completed = owners.read_original_completion()?;
            source.require_current(&owners.receipts.config.dataset)?;
            Ok(completed)
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

    /// Observe only the exact retained receipt through current original source
    /// custody. This does not sign, renew or change an attestation.
    pub async fn receipt_attestation_from_original_dataset<
        W: AnchorWitnessStore + Send + 'static,
    >(
        &self,
        dataset: &LearningIterationSnapshotV1,
        source: OriginalCellQ24TrainingSourceV1<W>,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        let completed = self.readback_from_original_dataset(dataset, source).await?;
        if &completed.receipt != expected {
            return Err(Error::Binding("exact original Training receipt"));
        }
        Ok(completed.attestation)
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
    fn prepare_training(
        &mut self,
        cancellation: &AtomicBool,
    ) -> Result<TrainingPreparation, Error> {
        let owners = self;
        match owners.receipts.journal.read(&owners.receipts.saved) {
            Ok(_) => owners
                .read_original_completion()
                .map(TrainingPreparation::Completed),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => {
                let training: &mut CellQ24TrainingOwnerV1<TW> = &mut owners.training;
                let receipts: &mut OriginalCellQ24TrainingReceiptOwnerV1<RW> = &mut owners.receipts;
                let retained_outcome = match training.readback() {
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
                    None => training.fit_or_readback(cancellation)?,
                };
                Ok(TrainingPreparation::Unattested(outcome))
            }
            Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
        }
    }

    fn complete_training(
        &mut self,
        prepared: TrainingPreparation,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        match prepared {
            TrainingPreparation::Completed(completed) => Ok(completed),
            TrainingPreparation::Unattested(outcome) => {
                let (receipt, attestation) = self
                    .receipts
                    .attest_original_completion(&mut self.training)?;
                Ok(OriginalCellQ24TrainingCompletionV1 {
                    outcome,
                    receipt,
                    attestation,
                })
            }
        }
    }

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
