//! Concrete ordinary learning composition over original capabilities.
//! Later B and C owners enter one bounded, operation-specific handoff slot.
//! Absence is unavailable, never a fabricated receipt or a NoUpdate decision.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use tokio::runtime::Handle;
use tokio::sync::Semaphore;

use crate::AgentdRootQ24ModelFactoryV1;
use crate::CellQ24PreparedLearningV1;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::LearningIterationStageOwnerPortsV1;
use crate::OriginalCellQ24EvaluationStageV1;
use crate::OriginalCellQ24LearningOpenV1;
use crate::OriginalCellQ24LocalDecisionOwnerV1;
use crate::OriginalCellQ24SourceReceiptOwnerV1;
use crate::OriginalCellQ24TrainingInputsV1;
use crate::OriginalCellQ24TrainingStageV1;
use crate::OriginalGenerationLearningReceiptOwnerV1;
use crate::OriginalGenerationLearningRoleV1;
use crate::PreparedLearningIterationProposalV1;
use crate::cell_q24_learning_owner_error::owner_error as unavailable;

#[path = "cell_q24_learning_successor.rs"]
mod successor;

#[path = "cell_q24_learning_model_dispatch.rs"]
mod model;
#[path = "cell_q24_publication_material.rs"]
mod publication_material;
#[path = "cell_q24_training_material.rs"]
mod training_material;
#[path = "cell_q24_training_readback.rs"]
mod training_readback;
pub use model::OriginalCellQ24ModelDispatchV1;
pub use training_material::OriginalCellQ24TrainingMaterialV1;
pub use training_readback::OriginalCellQ24TrainingReadbackV1;

struct Q24StageOwners {
    experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    factory: AgentdRootQ24ModelFactoryV1,
    local: OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore>,
    evaluation: Option<OriginalCellQ24EvaluationStageV1>,
    generation: Option<(
        OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
        OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
    )>,
}

struct Q24StageState {
    prepared: Arc<CellQ24PreparedLearningV1>,
    dataset_cut: LearningIterationSnapshotV1,
    training: Arc<OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
    owners: Arc<Mutex<Q24StageOwners>>,
    lane: Arc<Semaphore>,
    cancelled: Arc<AtomicBool>,
    successor: std::sync::OnceLock<std::sync::Weak<crate::circuit_q24_successor::SuccessorSlot>>,
}

/// No public raw-receipt or callback constructor. Each resource is an original
/// concrete owner; Root checkpoint custody remains outside this aggregate.
pub struct OriginalCellQ24LearningStageOwnersV1 {
    inner: Arc<Q24StageState>,
}

struct CancelTrainingOnDrop(Arc<AtomicBool>);
impl Drop for CancelTrainingOnDrop {
    fn drop(&mut self) {
        self.0.store(true, Ordering::Release);
    }
}

/// Dropping the waiting task cannot stop a blocking owner. It permanently
/// fences this aggregate instead; the host must reopen the original resources.
struct FenceAggregateOnDrop {
    cancelled: Arc<AtomicBool>,
    armed: bool,
}
impl Drop for FenceAggregateOnDrop {
    fn drop(&mut self) {
        if self.armed {
            self.cancelled.store(true, Ordering::Release);
        }
    }
}

impl OriginalCellQ24LearningStageOwnersV1 {
    /// E/D are completed once before assembly, and replayed by the worker from
    /// those same journals. Native Training is bound to their actual timestamped
    /// Dataset cut. Recovery does not sign, fit, refreeze or create missing files.
    pub async fn from_original_owners(
        prepared: Arc<CellQ24PreparedLearningV1>,
        sources: crate::OriginalCellQ24SourceInputsV1,
        verifier: LearningEvidenceVerifierV1,
        files: OriginalCellQ24TrainingInputsV1,
        local: OriginalCellQ24LocalDecisionOwnerV1<FileAnchorWitnessStore>,
        mut factory: AgentdRootQ24ModelFactoryV1,
        mode: OriginalCellQ24LearningOpenV1,
    ) -> Result<Arc<Self>, Error> {
        factory
            .require_learning_scope(prepared.initial(), prepared.scope())
            .map_err(unavailable)?;
        factory
            .require_local_policy(local.policy_digest())
            .map_err(unavailable)?;
        factory.require_current().await.map_err(unavailable)?;
        local
            .require_context(prepared.initial(), prepared.scope())
            .map_err(unavailable)?;
        let for_open = Arc::clone(&prepared);
        let (experience, dataset, dataset_cut, training, receipts) =
            tokio::task::spawn_blocking(move || {
                for_open.revalidate_source().map_err(unavailable)?;
                let (experience, dataset) =
                    sources.open_original_source_pair(Arc::clone(&for_open), verifier, mode)?;
                let mut experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> =
                    experience;
                let mut dataset: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore> =
                    dataset;
                let completed = match mode {
                    OriginalCellQ24LearningOpenV1::Create => {
                        experience.attest_experience().map_err(unavailable)?;
                        dataset
                            .attest_dataset(&mut experience)
                            .map_err(unavailable)?
                    }
                    OriginalCellQ24LearningOpenV1::Recover => {
                        dataset.read_dataset(&mut experience).map_err(unavailable)?
                    }
                };
                let cut = completed.snapshot().clone();
                let (training, receipts) =
                    files.open_original_training_pair(&for_open, cut.clone(), mode)?;
                Ok::<_, Error>((experience, dataset, cut, training, receipts))
            })
            .await
            .map_err(|_| Error::CommitUncertain)??;
        let training = OriginalCellQ24TrainingStageV1::from_original_owners(training, receipts)
            .await
            .map_err(unavailable)?;
        prepared.revalidate_source().map_err(unavailable)?;
        factory.require_current().await.map_err(unavailable)?;
        Ok(Arc::new(Self {
            inner: Arc::new(Q24StageState {
                prepared,
                dataset_cut,
                training: Arc::new(training),
                owners: Arc::new(Mutex::new(Q24StageOwners {
                    experience,
                    dataset,
                    factory,
                    local,
                    evaluation: None,
                    generation: None,
                })),
                lane: Arc::new(Semaphore::new(/*permits*/ 1)),
                cancelled: Arc::new(AtomicBool::new(/*val*/ false)),
                successor: std::sync::OnceLock::new(),
            }),
        }))
    }

    pub(crate) fn prepared(&self) -> &CellQ24PreparedLearningV1 {
        &self.inner.prepared
    }

    pub(crate) async fn require_current(&self) -> Result<(), Error> {
        self.inner.in_lane(|_, _, _| Ok(())).await
    }

    pub async fn install_published_generation(
        &self,
        snapshot: LearningIterationSnapshotV1,
        original: crate::OriginalCellQ24GenerationHandoffV1,
    ) -> Result<(), Error> {
        self.inner.require_snapshot(&snapshot)?;
        self.require_current().await?;
        let prepared = Arc::clone(&self.inner.prepared);
        let (selection, next_use) =
            tokio::task::spawn_blocking(move || original.into_receipt_owners(&prepared))
                .await
                .map_err(|_| Error::CommitUncertain)??;
        self.install_generation(snapshot, selection, next_use).await
    }

    /// Install the actual completed B owners once, after original Training.
    /// Validate the same current native receipt and independently pinned Trainer
    /// evidence; no supplied Training snapshot or role key is accepted as proof.
    pub async fn install_evaluation(
        &self,
        mut evaluation: OriginalCellQ24EvaluationStageV1,
    ) -> Result<(), Error> {
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(
                move |owners,
                      training: &OriginalCellQ24TrainingStageV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                >,
                      runtime| {
                    if owners.evaluation.is_some() {
                        return Err(Error::WrongScope);
                    }
                    let trainer_source: &crate::OriginalCellEvaluationTrainerV1 =
                        &evaluation.trainer;
                    trainer_source.require_original_owner(
                        &inner.prepared,
                        &inner.training,
                        &inner.dataset_cut,
                        &inner.cancelled,
                    )?;
                    let completed = runtime
                        .block_on(training.readback(&inner.dataset_cut))
                        .map_err(unavailable)?;
                    let mut cut =
                        LearningIterationCoordinatorV1::from_snapshot(inner.dataset_cut.clone())?;
                    cut.record(
                        completed.receipt.clone(),
                        completed.receipt.observed_unix_seconds,
                    )?;
                    evaluation.require_training(cut.snapshot(), inner.prepared.scope())?;
                    runtime.block_on(
                        evaluation.require_original_training_evidence(&completed.attestation),
                    )?;
                    owners.evaluation = Some(evaluation);
                    Ok(())
                },
            )
            .await
    }

    pub async fn install_independent_evaluation(
        &self,
        original: crate::OriginalCellQ24EvaluationInputsV1,
    ) -> Result<(), Error> {
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(
                move |owners,
                      training: &OriginalCellQ24TrainingStageV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                >,
                      runtime| {
                    if owners.evaluation.is_some() {
                        return Err(Error::WrongScope);
                    }
                    let trainer_source: &crate::OriginalCellEvaluationTrainerV1 = &original.trainer;
                    trainer_source.require_original_owner(
                        &inner.prepared,
                        &inner.training,
                        &inner.dataset_cut,
                        &inner.cancelled,
                    )?;
                    let completed = runtime
                        .block_on(training.readback(&inner.dataset_cut))
                        .map_err(unavailable)?;
                    let mut cut =
                        LearningIterationCoordinatorV1::from_snapshot(inner.dataset_cut.clone())?;
                    cut.record(
                        completed.receipt.clone(),
                        completed.receipt.observed_unix_seconds,
                    )?;
                    let mut evaluation: OriginalCellQ24EvaluationStageV1 = original
                        .into_stage(cut.snapshot().clone(), inner.prepared.scope().clone())?;
                    evaluation.require_training(cut.snapshot(), inner.prepared.scope())?;
                    runtime.block_on(
                        evaluation.require_original_training_evidence(&completed.attestation),
                    )?;
                    owners.evaluation = Some(evaluation);
                    Ok(())
                },
            )
            .await
    }

    /// The pair retains the published actor and exact ordinary successor intent.
    /// All predecessor receipts are reread from their original owners before
    /// accepting this slot. No publication, FinalUse or task is manufactured.
    pub async fn install_generation(
        &self,
        snapshot: LearningIterationSnapshotV1,
        mut selection: OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
        mut next_use: OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
    ) -> Result<(), Error> {
        let installed_snapshot = snapshot.clone();
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(
                move |owners,
                      training: &OriginalCellQ24TrainingStageV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                >,
                      runtime| {
                    if owners.generation.is_some() {
                        return Err(Error::WrongScope);
                    }
                    inner.require_snapshot(&snapshot)?;
                    selection
                        .require_context(
                            inner.prepared.initial(),
                            inner.prepared.scope(),
                            OriginalGenerationLearningRoleV1::Selection,
                        )
                        .map_err(unavailable)?;
                    next_use
                        .require_context(
                            inner.prepared.initial(),
                            inner.prepared.scope(),
                            OriginalGenerationLearningRoleV1::NextUse,
                        )
                        .map_err(unavailable)?;
                    for retained in &snapshot.receipts {
                        let observed = match &retained.observation {
                            LearningIterationObservationV1::Selection { .. } => Some(
                                runtime
                                    .block_on(selection.readback(&snapshot))
                                    .map_err(unavailable)?
                                    .0,
                            ),
                            LearningIterationObservationV1::NextUse { .. }
                            | LearningIterationObservationV1::RetainedModelNextUse { .. } => Some(
                                runtime
                                    .block_on(next_use.readback(&snapshot))
                                    .map_err(unavailable)?
                                    .0,
                            ),
                            _ => {
                                owners.require_receipt(
                                    &inner, training, runtime, &snapshot, retained,
                                )?;
                                None
                            }
                        };
                        if observed.as_ref().is_some_and(|receipt| receipt != retained) {
                            return Err(Error::WrongScope);
                        }
                    }
                    runtime
                        .block_on(selection.observe_original_selection(&snapshot))
                        .map_err(unavailable)?;
                    owners.generation = Some((selection, next_use));
                    Ok(())
                },
            )
            .await?;
        self.notify_original_successor_generation(&installed_snapshot)
    }
}

impl Q24StageState {
    fn require_snapshot(&self, snapshot: &LearningIterationSnapshotV1) -> Result<(), Error> {
        if snapshot.request != self.prepared.initial().request
            || snapshot.owners != self.prepared.initial().owners
        {
            return Err(Error::WrongScope);
        }
        self.prepared
            .scope()
            .validate_snapshot(snapshot)
            .map_err(|_| Error::WrongScope)?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        Ok(())
    }

    async fn in_lane<T: Send + 'static>(
        &self,
        work: impl FnOnce(
            &mut Q24StageOwners,
            &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
            &Handle,
        ) -> Result<T, Error>
        + Send
        + 'static,
    ) -> Result<T, Error> {
        if self.cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        let permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| Error::CommitUncertain)?;
        let mut fence = FenceAggregateOnDrop {
            cancelled: Arc::clone(&self.cancelled),
            armed: true,
        };
        let owners = Arc::clone(&self.owners);
        let training = Arc::clone(&self.training);
        let prepared: Arc<CellQ24PreparedLearningV1> = Arc::clone(&self.prepared);
        let cancelled = Arc::clone(&self.cancelled);
        let runtime = Handle::current();
        let result = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            let mut locked = owners.try_lock().map_err(|_| Error::CommitUncertain)?;
            let owners: &mut Q24StageOwners = &mut locked;
            prepared.revalidate_source().map_err(unavailable)?;
            runtime
                .block_on(owners.factory.require_current())
                .map_err(unavailable)?;
            if cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            let result = work(owners, &training, &runtime)?;
            prepared.revalidate_source().map_err(unavailable)?;
            runtime
                .block_on(owners.factory.require_current())
                .map_err(unavailable)?;
            if cancelled.load(Ordering::Acquire) {
                return Err(Error::CommitUncertain);
            }
            Ok(result)
        })
        .await
        .map_err(|_| Error::CommitUncertain)?;
        fence.armed = false;
        result
    }
}

impl Q24StageOwners {
    fn source_receipt(
        &mut self,
        stage: LearningIterationStageV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let completed = match stage {
            LearningIterationStageV1::Experience => {
                self.experience.read_experience().map_err(unavailable)?
            }
            LearningIterationStageV1::Dataset => self
                .dataset
                .read_dataset(&mut self.experience)
                .map_err(unavailable)?,
            _ => return Err(Error::WrongScope),
        };
        Ok((completed.receipt().clone(), completed.attestation().clone()))
    }

    fn require_receipt(
        &mut self,
        inner: &Q24StageState,
        training: &OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        runtime: &Handle,
        snapshot: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<Option<SignedLearningEvidenceV1>, Error> {
        let (receipt, attestation) = match expected.observation.stage() {
            LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset => {
                let (receipt, signed) = self.source_receipt(expected.observation.stage())?;
                (receipt, Some(signed))
            }
            LearningIterationStageV1::Training => {
                let original = runtime
                    .block_on(crate::read_cell_q24_training_snapshot_v1(
                        training, snapshot, expected,
                    ))
                    .map_err(unavailable)?;
                (original.receipt, Some(original.attestation))
            }
            LearningIterationStageV1::Evaluation => {
                let eval: &mut OriginalCellQ24EvaluationStageV1 = self
                    .evaluation
                    .as_mut()
                    .ok_or(Error::OwnerUnavailable("original B handoff"))?;
                let (receipt, signed) =
                    runtime.block_on(eval.complete(snapshot, /*read_only*/ true))?;
                (receipt, Some(signed))
            }
            LearningIterationStageV1::Proposal => (
                self.model_action(
                    inner,
                    training,
                    runtime,
                    snapshot,
                    model::Action::ReadProposal,
                )?
                .0,
                None,
            ),
            LearningIterationStageV1::Selection
                if matches!(
                    expected.observation,
                    LearningIterationObservationV1::LocalDecisionV2(_)
                ) =>
            {
                let result = self.model_action(
                    inner,
                    training,
                    runtime,
                    snapshot,
                    model::Action::ReadDecision,
                )?;
                (result.0, result.1)
            }
            LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse => {
                let (selection, next_use) = self
                    .generation
                    .as_mut()
                    .ok_or(Error::OwnerUnavailable("original C handoff"))?;
                let source: &mut OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore> =
                    if expected.observation.stage() == LearningIterationStageV1::Selection {
                        selection
                    } else {
                        next_use
                    };
                let (receipt, signed) = runtime
                    .block_on(source.readback(snapshot))
                    .map_err(unavailable)?;
                (receipt, Some(signed))
            }
        };
        if &receipt != expected {
            return Err(Error::WrongScope);
        }
        Ok(attestation)
    }
}

impl LearningIterationStageOwnerPortsV1 for OriginalCellQ24LearningStageOwnersV1 {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async move {
            self.inner.require_snapshot(snapshot)?;
            let snapshot = snapshot.clone();
            let inner = Arc::clone(&self.inner);
            self.inner
                .in_lane(
                    move |owners,
                          training: &OriginalCellQ24TrainingStageV1<
                        FileAnchorWitnessStore,
                        FileAnchorWitnessStore,
                    >,
                          runtime| {
                        for receipt in &snapshot.receipts {
                            owners
                                .require_receipt(&inner, training, runtime, &snapshot, receipt)?;
                        }
                        Ok(())
                    },
                )
                .await
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            self.inner.require_snapshot(snapshot)?;
            if LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?.next_stage()
                != Some(stage)
            {
                return Err(Error::WrongScope);
            }
            let snapshot = snapshot.clone();
            let inner = Arc::clone(&self.inner);
            let cancellation = Arc::new(AtomicBool::new(/*val*/ false));
            let _cancel_on_drop = CancelTrainingOnDrop(Arc::clone(&cancellation));
            self.inner
                .in_lane(
                    move |owners,
                          training: &OriginalCellQ24TrainingStageV1<
                        FileAnchorWitnessStore,
                        FileAnchorWitnessStore,
                    >,
                          runtime| match stage {
                        LearningIterationStageV1::Experience
                        | LearningIterationStageV1::Dataset => Ok(owners.source_receipt(stage)?.0),
                        LearningIterationStageV1::Training => Ok(runtime
                            .block_on(training.execute_training(&snapshot, cancellation))
                            .map_err(unavailable)?
                            .receipt),
                        LearningIterationStageV1::Evaluation => {
                            let evaluation: &mut OriginalCellQ24EvaluationStageV1 = owners
                                .evaluation
                                .as_mut()
                                .ok_or(Error::OwnerUnavailable("original B handoff"))?;
                            runtime
                                .block_on(evaluation.complete(&snapshot, /*read_only*/ false))
                                .map(|value| value.0)
                        }
                        LearningIterationStageV1::Proposal => Err(Error::WrongScope),
                        LearningIterationStageV1::Selection => {
                            if snapshot.receipts.last().is_some_and(|receipt| {
                                receipt.observation.stage() == LearningIterationStageV1::Proposal
                            }) {
                                return Ok(owners
                                    .model_action(
                                        &inner,
                                        training,
                                        runtime,
                                        &snapshot,
                                        model::Action::CommitDecision,
                                    )?
                                    .0);
                            }
                            let (selection, _) = owners
                                .generation
                                .as_mut()
                                .ok_or(Error::OwnerUnavailable("original C publication handoff"))?;
                            let selection: &mut OriginalGenerationLearningReceiptOwnerV1<
                                FileAnchorWitnessStore,
                            > = selection;
                            runtime
                                .block_on(selection.attest_original_completion(&snapshot))
                                .map(|value| value.0)
                                .map_err(unavailable)
                        }
                        LearningIterationStageV1::NextUse => {
                            let (_, next_use) = owners.generation.as_mut().ok_or(
                                Error::OwnerUnavailable("original C committed-use handoff"),
                            )?;
                            let next_use: &mut OriginalGenerationLearningReceiptOwnerV1<
                                FileAnchorWitnessStore,
                            > = next_use;
                            runtime
                                .block_on(next_use.attest_original_completion(&snapshot))
                                .map(|value| value.0)
                                .map_err(unavailable)
                        }
                    },
                )
                .await
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async move {
            self.inner.require_snapshot(snapshot)?;
            self.require_current().await?;
            model::prepare(Arc::clone(&self.inner), snapshot)
        })
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        _now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            self.inner.require_snapshot(snapshot)?;
            let snapshot = snapshot.clone();
            let receipt = receipt.clone();
            let inner = Arc::clone(&self.inner);
            self.inner
                .in_lane(
                    move |owners,
                          training: &OriginalCellQ24TrainingStageV1<
                        FileAnchorWitnessStore,
                        FileAnchorWitnessStore,
                    >,
                          runtime| {
                        owners
                            .require_receipt(&inner, training, runtime, &snapshot, &receipt)?
                            .ok_or(Error::WrongScope)
                    },
                )
                .await
        })
    }
}
