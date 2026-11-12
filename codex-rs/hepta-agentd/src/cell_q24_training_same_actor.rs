//! Original Training work with the same phase's actual handle custody.
//! The old unscoped constructor and lane keep their existing contract.

use super::*;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    pub(crate) async fn from_original_same_actor_owners(
        training: CellQ24TrainingOwnerV1<TW>,
        receipts: OriginalCellQ24TrainingReceiptOwnerV1<RW>,
        phase: Arc<OriginalSameActorLearningWork>,
    ) -> Result<Self, Error> {
        let mut closing = phase.original_failure_scope();
        phase
            .require_training_context(&receipts.config.dataset, &receipts.config.scope)
            .map_err(|_| Error::Binding("original phase Training scope"))?;
        let stage = Self {
            dataset: receipts.config.dataset.clone(),
            owners: Arc::new(Mutex::new(Owners { training, receipts })),
            lane: Arc::new(Semaphore::new(1)),
            same_actor_work: Some(Arc::clone(&phase)),
        };
        stage
            .in_lane(|owners| {
                super::super::validate_config(&owners.receipts.config, &owners.receipts.key)?;
                match owners.receipts.journal.read(&owners.receipts.saved) {
                    Ok(_) => owners.read_original_completion().map(|_| ()),
                    Err(LearningOriginalOwnerErrorV1::Store(
                        ProductEvaluationExecutionStoreErrorV1::Missing,
                    )) => Ok(()),
                    Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
                }
            })
            .await?;
        phase
            .require_original_work_entry()
            .map_err(|_| Error::CommitUncertain)?;
        closing.disarm();
        Ok(stage)
    }

    pub(super) async fn execute_original_same_actor_training(
        &self,
        dataset: &LearningIterationSnapshotV1,
        cancellation: Arc<AtomicBool>,
        phase: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, Error> {
        let mut closing = phase.original_failure_scope();
        self.require_dataset(dataset)?;
        let for_work = Arc::clone(phase);
        let completed = self.in_lane(
            move |owners| match owners.receipts.journal.read(&owners.receipts.saved) {
                Ok(_) => owners.read_original_completion(),
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
                    let now = super::super::now()
                        .map_err(OriginalCellQ24TrainingReceiptErrorV1::from)?;
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
                    // The original witness read and native owner lock have
                    // completed. A closed phase cannot start a new fit.
                    for_work
                        .require_original_work_entry()
                        .map_err(|_| Error::CommitUncertain)?;
                    let outcome = match retained_outcome {
                        Some(outcome) => outcome,
                        None => training.fit_or_readback(&cancellation)?,
                    };
                    // An admitted fit may finish after cancellation. Its real
                    // durable outcome is retained; no new receipt is started.
                    for_work
                        .require_original_work_entry()
                        .map_err(|_| Error::CommitUncertain)?;
                    let (receipt, attestation) = receipts.attest_original_completion(training)?;
                    Ok(OriginalCellQ24TrainingCompletionV1 {
                        outcome,
                        receipt,
                        attestation,
                    })
                }
                Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
            },
        ).await?;
        phase
            .require_original_work_entry()
            .map_err(|_| Error::CommitUncertain)?;
        closing.disarm();
        Ok(completed)
    }

    pub(super) async fn in_original_same_actor_training_lane<T: Send + 'static>(
        &self,
        phase: &Arc<OriginalSameActorLearningWork>,
        work: impl FnOnce(&mut Owners<TW, RW>) -> Result<T, Error> + Send + 'static,
    ) -> Result<T, Error> {
        let mut closing = phase.original_failure_scope();
        phase
            .require_original_work_entry()
            .map_err(|_| Error::CommitUncertain)?;
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::Busy)?;
        let owners = Arc::clone(&self.owners);
        let for_work = Arc::clone(phase);
        let job = {
            let admission = phase
                .reserve_original_blocking()
                .map_err(|_| Error::CommitUncertain)?;
            let handle = tokio::task::spawn_blocking(move || {
                let _permit = permit;
                let mut closing = for_work.original_failure_scope();
                let mut owners = owners.try_lock().map_err(|_| Error::CommitUncertain)?;
                let training: &CellQ24TrainingOwnerV1<TW> = &owners.training;
                training.require_original_dataset_scope(
                    &owners.receipts.config.dataset,
                    &owners.receipts.config.scope,
                )?;
                for_work
                    .require_training_context(
                        &owners.receipts.config.dataset,
                        &owners.receipts.config.scope,
                    )
                    .map_err(|_| Error::CommitUncertain)?;
                let result = work(&mut owners)?;
                for_work
                    .require_original_work_entry()
                    .map_err(|_| Error::CommitUncertain)?;
                closing.disarm();
                Ok(result)
            });
            admission.retain_original_handle(handle)
        };
        let result = phase
            .receive_original_job(job)
            .await
            .map_err(|_| Error::CommitUncertain)?;
        if result.is_ok() {
            closing.disarm();
        }
        result
    }
}
